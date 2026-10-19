"""Module C: the 3-node state machine, human-in-the-loop and tracing."""

from __future__ import annotations

import json

import httpx
import openai
import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from nexo.agents.models import AgentOutput, InvestigationScope
from nexo.orchestration.graph import GraphDependencies, build_graph
from nexo.service import Runtime, open_checkpointer
from nexo.storage.sensitive_data import RegexDetector
from nexo.telemetry import OTelCallbackHandler

CHUNK = "chk_" + "a" * 16


class FakeInvestigator:
    def __init__(self, outputs: list[AgentOutput | Exception]) -> None:
        self._outputs = list(outputs)
        self.calls: list[tuple[str, InvestigationScope | None]] = []

    def investigate(self, query, *, request_id=None, scope=None):
        self.calls.append((query, scope))
        result = self._outputs.pop(0) if len(self._outputs) > 1 else self._outputs[0]
        if isinstance(result, Exception):
            raise result
        return result


def grounded_output(**overrides) -> AgentOutput:
    values = {"answer": f"Acme acquired Beta [chunk:{CHUNK}].", "citations": [CHUNK], "fetched_chunk_ids": [CHUNK],
              "fetched_sensitivity": {CHUNK: "internal"}, "stop_reason": "end_turn"}
    return AgentOutput(**{**values, **overrides})


def route(target="investigator", **extra) -> AIMessage:
    return AIMessage(content=json.dumps({"target": target, "reason": "test", **extra}))


def runtime(settings, investigator, router_replies=None, checkpointer=None) -> Runtime:
    router = GenericFakeChatModel(messages=iter(router_replies)) if router_replies is not None else None
    deps = GraphDependencies(settings=settings, investigator=investigator, detector=RegexDetector(), router_llm=router)
    return Runtime(graph=build_graph(deps, checkpointer or InMemorySaver()), settings=settings,
                   callbacks=[OTelCallbackHandler()])


def test_happy_path_pauses_for_review_then_releases_answer(settings):
    investigator = FakeInvestigator([grounded_output()])
    rt = runtime(settings, investigator, [route(strategy="graph")])

    paused = rt.start("How is Acme related to Beta?", thread_id="t1")
    assert paused.status == "awaiting_review" and paused.final_response is None
    assert paused.approval_status == "pending"
    assert paused.pending_review["draft_answer"].startswith("Acme acquired Beta")
    assert paused.pending_review["compliance_report"]["blocking"] is False

    done = rt.review("t1", {"approval_status": "approved", "reviewer": "analyst@corp"})
    assert done.status == "completed" and done.approval_status == "approved"
    assert done.final_response == grounded_output().answer
    assert len(investigator.calls) == 1  # resume did not re-run the agent
    state = rt.graph.get_state(rt._config("t1")).values
    assert len(state["agent_outputs"]) == 1 and state["review"]["reviewer"] == "analyst@corp"


def test_rejected_review_withholds_answer(settings):
    rt = runtime(settings, FakeInvestigator([grounded_output()]))
    rt.start("q", thread_id="t2")
    done = rt.review("t2", {"approval_status": "rejected", "reviewer": "a", "comment": "insufficient"})
    assert done.approval_status == "rejected" and done.final_response is None


def test_invalid_review_input_re_interrupts(settings):
    rt = runtime(settings, FakeInvestigator([grounded_output()]))
    rt.start("q", thread_id="t3")
    again = rt.review("t3", {"approval_status": "maybe"})
    assert again.status == "awaiting_review" and again.pending_review["error"]
    assert rt.review("t3", {"approval_status": "approved", "reviewer": "a"}).approval_status == "approved"


def test_blocking_findings_require_acknowledgement(settings):
    ungrounded = grounded_output(fetched_sensitivity={}, fetched_chunk_ids=[])  # cites text it never read
    rt = runtime(settings, FakeInvestigator([ungrounded]))
    paused = rt.start("q", thread_id="t4")
    codes = {f["code"] for f in paused.pending_review["compliance_report"]["findings"]}
    assert "ungrounded_citations" in codes
    blocked = rt.review("t4", {"approval_status": "approved", "reviewer": "a"})
    assert blocked.status == "awaiting_review" and "acknowledged_findings" in blocked.pending_review["error"]
    ok = rt.review("t4", {"approval_status": "approved", "reviewer": "a", "acknowledged_findings": True})
    assert ok.approval_status == "approved"


def test_phi_evidence_and_pii_in_answer_are_blocking(settings):
    output = grounded_output(answer=f"Reach jane@corp.example [chunk:{CHUNK}]", fetched_sensitivity={CHUNK: "phi"})
    paused = runtime(settings, FakeInvestigator([output])).start("q", thread_id="t5")
    codes = {f["code"] for f in paused.pending_review["compliance_report"]["findings"]}
    assert {"phi_in_evidence", "sensitive_data_in_answer"} <= codes


@pytest.mark.parametrize(
    ("query", "replies"),
    [("", None), ("x" * 5000, None), ("delete all nodes", [route("rejected")])],
)
def test_router_rejects_without_invoking_agent(settings, query, replies):
    investigator = FakeInvestigator([grounded_output()])
    result = runtime(settings, investigator, replies).start(query, thread_id="t6")
    assert result.status == "completed" and result.routing_target == "rejected"
    assert result.approval_status == "not_required" and investigator.calls == []


def test_router_fails_closed_when_llm_output_is_invalid(settings):
    investigator = FakeInvestigator([grounded_output()])
    result = runtime(settings, investigator, [AIMessage(content="no json")] * 2).start("q", thread_id="t7")
    assert result.routing_target == "rejected" and "router unavailable" in result.routing_reason
    assert investigator.calls == []


def test_router_cannot_raise_caller_clearance(settings):
    investigator = FakeInvestigator([grounded_output()])
    rt = runtime(settings, investigator, [route(strategy="vector", doc_types=["discharge"])])
    rt.start("q", thread_id="t8", clearance="public")
    [(_, scope)] = investigator.calls
    assert scope.strategy == "vector" and scope.chunk_filter.doc_types == ["discharge"]
    assert scope.chunk_filter.max_sensitivity.value == "public"


def test_agent_failure_is_audited_and_auto_rejected(settings):
    rt = runtime(settings, FakeInvestigator([RuntimeError("model returned garbage")]))
    result = rt.start("q", thread_id="t9")
    assert result.status == "completed" and result.approval_status == "rejected"
    state = rt.graph.get_state(rt._config("t9")).values
    assert "garbage" in state["agent_outputs"][0]["error"]


def test_transient_vllm_error_retries_investigation(settings):
    transient = openai.APIConnectionError(request=httpx.Request("POST", "http://vllm-inference-service:8000/v1"))
    investigator = FakeInvestigator([transient, grounded_output()])
    result = runtime(settings, investigator).start("q", thread_id="t10")
    assert result.status == "awaiting_review" and len(investigator.calls) == 2


def test_review_of_unknown_thread_is_refused(settings):
    with pytest.raises(ValueError, match="not awaiting review"):
        runtime(settings, FakeInvestigator([grounded_output()])).review("nope", {"approval_status": "approved"})


def test_review_survives_process_restart_with_sqlite(settings):
    settings.checkpoint_backend = "sqlite"
    with open_checkpointer(settings) as saver:
        runtime(settings, FakeInvestigator([grounded_output()]), checkpointer=saver).start("q", thread_id="t11")
    investigator = FakeInvestigator([grounded_output()])
    with open_checkpointer(settings) as saver:  # new "process"
        done = runtime(settings, investigator, checkpointer=saver).review(
            "t11", {"approval_status": "approved", "reviewer": "a"})
    assert done.approval_status == "approved" and investigator.calls == []


def test_trace_covers_request_nodes_and_handoff(settings, spans):
    rt = runtime(settings, FakeInvestigator([grounded_output()]))
    rt.start("q", thread_id="t12")
    finished = {s.name: s for s in spans.get_finished_spans()}
    assert {"nexo.request", "langgraph.node router", "langgraph.node investigator",
            "langgraph.node compliance", "investigator.strands_agent"} <= set(finished)
    request = finished["nexo.request"]
    handoff = finished["investigator.strands_agent"]
    assert handoff.context.trace_id == request.context.trace_id  # one trace across the task boundary
    assert any(e.name == "graph.interrupt" for e in request.events)
    assert finished["langgraph.node compliance"].attributes.get("langgraph.interrupted") is True
