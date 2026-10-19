"""OpenTelemetry wiring for every layer of the stack.

Three span sources share one global TracerProvider, so a single trace shows
the whole request:

* `OTelCallbackHandler`  - LangChain/LangGraph callbacks: one span per graph
  node (with the state keys it changed), per LangChain LLM call and per
  LangChain tool.
* Strands Agents SDK     - emits its own GenAI semantic-convention spans
  (agent invocation, event-loop cycle, model call, tool call) through the
  global provider; nothing extra to wire.
* Explicit spans         - Neo4j and vector-store access inside the agent tools
  and the LangGraph -> Strands handoff (see `traced_span`).

LangSmith is optional and orthogonal: set `LANGSMITH_TRACING=true` and
`LANGSMITH_API_KEY` and LangChain reports the same runs there natively.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.trace import Span, Status, StatusCode

from graphrag_stack.config import Settings

TRACER_NAME = "graphrag_stack"

_setup_lock = threading.Lock()
_provider: TracerProvider | None = None


def setup_telemetry(settings: Settings) -> TracerProvider:
    """Install the process-wide TracerProvider once (idempotent)."""
    global _provider
    with _setup_lock:
        if _provider is not None:
            return _provider
        resource = Resource.create(
            {
                "service.name": settings.otel_service_name,
                "deployment.environment.name": settings.deployment_environment,
            }
        )
        provider = TracerProvider(resource=resource)
        if settings.otel_exporter_otlp_endpoint:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            endpoint = settings.otel_exporter_otlp_endpoint.rstrip("/") + "/v1/traces"
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        if settings.otel_console_export:
            provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        trace.set_tracer_provider(provider)
        _provider = provider
        return provider


def shutdown_telemetry() -> None:
    """Flush pending spans; call before process exit (CLI, worker shutdown)."""
    if _provider is not None:
        _provider.shutdown()


def get_tracer() -> trace.Tracer:
    return trace.get_tracer(TRACER_NAME)


@contextmanager
def traced_span(name: str, attributes: Mapping[str, Any] | None = None, **kwargs: Any) -> Iterator[Span]:
    """Start a current span; exceptions are recorded and set ERROR status."""
    with get_tracer().start_as_current_span(name, attributes=clean_attributes(attributes or {}), **kwargs) as span:
        yield span


def clean_attributes(attributes: Mapping[str, Any]) -> dict[str, Any]:
    """Drop None values and coerce to OTEL-supported attribute types."""
    cleaned: dict[str, Any] = {}
    for key, value in attributes.items():
        if value is None:
            continue
        if isinstance(value, (str, bool, int, float)):
            cleaned[key] = value
        elif isinstance(value, (list, tuple, set, frozenset)):
            cleaned[key] = [str(v) for v in value]
        else:
            cleaned[key] = str(value)
    return cleaned


class OTelCallbackHandler(BaseCallbackHandler):
    """Bridges LangChain/LangGraph callback events to OpenTelemetry spans.

    Spans are keyed by LangChain `run_id` and parented by `parent_run_id`, so
    the trace tree mirrors graph -> node -> LLM call. Root runs attach to
    whatever OTEL span is current (the request span opened by the service).
    """

    raise_error = False  # telemetry must never break the workflow

    def __init__(self, *, capture_content: bool = False) -> None:
        self._capture_content = capture_content
        self._spans: dict[UUID, Span] = {}
        self._lock = threading.Lock()

    # -- span bookkeeping ---------------------------------------------------
    def _start(self, name: str, run_id: UUID, parent_run_id: UUID | None, attributes: Mapping[str, Any]) -> None:
        with self._lock:
            parent = self._spans.get(parent_run_id) if parent_run_id else None
        context = trace.set_span_in_context(parent) if parent is not None else None
        span = get_tracer().start_span(name, context=context, attributes=clean_attributes(attributes))
        with self._lock:
            self._spans[run_id] = span

    def _end(self, run_id: UUID, *, error: BaseException | None = None,
             attributes: Mapping[str, Any] | None = None) -> None:
        with self._lock:
            span = self._spans.pop(run_id, None)
        if span is None:
            return
        if attributes:
            span.set_attributes(clean_attributes(attributes))
        if error is not None:
            if _is_graph_interrupt(error):
                # A human-in-the-loop pause is control flow, not a failure.
                span.set_attribute("langgraph.interrupted", True)
            else:
                span.record_exception(error)
                span.set_status(Status(StatusCode.ERROR, type(error).__name__))
        span.end()

    # -- chains / graph nodes ------------------------------------------------
    def on_chain_start(self, serialized: dict[str, Any] | None, inputs: Any, *, run_id: UUID,
                       parent_run_id: UUID | None = None, metadata: dict[str, Any] | None = None,
                       **kwargs: Any) -> None:
        metadata = metadata or {}
        node = metadata.get("langgraph_node")
        name = kwargs.get("name") or (serialized or {}).get("name") or "chain"
        self._start(
            f"langgraph.node {node}" if node and node == name else f"langchain.chain {name}",
            run_id,
            parent_run_id,
            {
                "langgraph.node": node,
                "langgraph.step": metadata.get("langgraph_step"),
                "langgraph.thread_id": metadata.get("thread_id"),
                "langgraph.input.keys": sorted(inputs) if isinstance(inputs, dict) else None,
            },
        )

    def on_chain_end(self, outputs: Any, *, run_id: UUID, **kwargs: Any) -> None:
        # The keys a node returns are exactly the graph state it changed.
        changed = sorted(outputs) if isinstance(outputs, dict) else None
        with self._lock:
            span = self._spans.get(run_id)
        if span is not None and changed:
            span.add_event("graph.state_change", {"state.keys": changed})
        self._end(run_id, attributes={"langgraph.state_update.keys": changed})

    def on_chain_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self._end(run_id, error=error)

    # -- LLM calls (vLLM via ChatOpenAI) -------------------------------------
    def on_chat_model_start(self, serialized: dict[str, Any] | None, messages: list[list[Any]], *,
                            run_id: UUID, parent_run_id: UUID | None = None,
                            metadata: dict[str, Any] | None = None, **kwargs: Any) -> None:
        params = kwargs.get("invocation_params") or {}
        attributes: dict[str, Any] = {
            "gen_ai.operation.name": "chat",
            "gen_ai.provider.name": "vllm",
            "gen_ai.request.model": params.get("model") or params.get("model_name")
            or (metadata or {}).get("ls_model_name"),
            "gen_ai.request.temperature": params.get("temperature"),
            "llm.structured_output": "response_format" in params,
        }
        if self._capture_content:
            attributes["gen_ai.prompt"] = str(messages)[:8000]
        self._start("chat", run_id, parent_run_id, attributes)

    def on_llm_start(self, serialized: dict[str, Any] | None, prompts: list[str], *, run_id: UUID,
                     parent_run_id: UUID | None = None, **kwargs: Any) -> None:
        self._start("text_completion", run_id, parent_run_id, {"gen_ai.provider.name": "vllm"})

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        usage = (response.llm_output or {}).get("token_usage") or {}
        if not usage and response.generations and response.generations[0]:
            message = getattr(response.generations[0][0], "message", None)
            meta = getattr(message, "usage_metadata", None) or {}
            usage = {"prompt_tokens": meta.get("input_tokens"), "completion_tokens": meta.get("output_tokens")}
        self._end(
            run_id,
            attributes={
                "gen_ai.usage.input_tokens": usage.get("prompt_tokens"),
                "gen_ai.usage.output_tokens": usage.get("completion_tokens"),
            },
        )

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self._end(run_id, error=error)

    # -- LangChain tools -----------------------------------------------------
    def on_tool_start(self, serialized: dict[str, Any] | None, input_str: str, *, run_id: UUID,
                      parent_run_id: UUID | None = None, **kwargs: Any) -> None:
        name = (serialized or {}).get("name") or kwargs.get("name") or "tool"
        attributes = {"gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": name}
        if self._capture_content:
            attributes["gen_ai.tool.input"] = input_str[:4000]
        self._start(f"execute_tool {name}", run_id, parent_run_id, attributes)

    def on_tool_end(self, output: Any, *, run_id: UUID, **kwargs: Any) -> None:
        self._end(run_id)

    def on_tool_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self._end(run_id, error=error)


def _is_graph_interrupt(error: BaseException) -> bool:
    from langgraph.errors import GraphBubbleUp

    return isinstance(error, GraphBubbleUp)
