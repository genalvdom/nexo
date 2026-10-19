---
type: Reference
title: OpenTelemetry GenAI semantic conventions
description: The OpenTelemetry conventions for generative AI telemetry (spans, attributes, content capture, metrics) and where Nexo follows or deviates.
resource: https://github.com/open-telemetry/semantic-conventions-genai
tags: [reference, observability, opentelemetry, genai]
status: draft
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-19T20:14:37Z }
stale_after: 2027-01-19T00:00:00Z
sources:
  - id: genai-repo
    resource: https://github.com/open-telemetry/semantic-conventions-genai
    title: OpenTelemetry GenAI semantic conventions (development)
  - id: core
    resource: https://github.com/open-telemetry/semantic-conventions
    title: OpenTelemetry semantic conventions (database spans, v1.44.0)
  - id: python-genai
    resource: https://github.com/open-telemetry/opentelemetry-python-genai
    title: OpenTelemetry Python GenAI instrumentations
---

# Status

The GenAI conventions moved out of the core specification after v1.41.1 into their own repository.
Every GenAI attribute, span and metric there is still **Development** (unstable): names can change.
`stale_after` on this page is short for that reason.[^genai-repo]

# What applies to Nexo

| Operation | Span | Kind | Who emits it in Nexo |
|---|---|---|---|
| Workflow run | `invoke_workflow {gen_ai.workflow.name}` | INTERNAL | `Runtime` (`invoke_workflow nexo-investigation`) |
| Agent run | `invoke_agent {gen_ai.agent.name}` | INTERNAL | Strands |
| Tool call | `execute_tool {gen_ai.tool.name}` | INTERNAL | Strands |
| Inference | `chat {gen_ai.request.model}` | CLIENT | `opentelemetry-instrumentation-genai-openai`[^python-genai] |
| Embeddings | `embeddings {gen_ai.request.model}` | CLIENT | same instrumentation |
| Retrieval | `retrieval {gen_ai.data_source.id}` | CLIENT (INTERNAL in-process) | `LocalChunkStore.search` |
| Database call | `{db.query.summary}` with `db.system.name=neo4j` | CLIENT | `GraphStore` (core database conventions)[^core] |

Key attributes: `gen_ai.operation.name`, `gen_ai.provider.name` (not the deprecated `gen_ai.system`),
`gen_ai.conversation.id` (a real thread id, never a generated fallback), `gen_ai.usage.*`,
`error.type`.

# Content capture

Message content is opt-in. Nexo uses the standard
`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` (`no_content` default; `span_only`,
`event_only`, `span_and_event`) and, for Strands, `OTEL_SEMCONV_STABILITY_OPT_IN` with
`gen_ai_unredacted_attributes=` (empty list = redact all) when capture is off.

# Known deviations

- Strands names its model span `chat` without the model and adds legacy usage keys
  (`gen_ai.usage.prompt_tokens`, ...); it also emits `execute_event_loop_cycle` spans the spec does not
  define.
- Strands' `chat` span and the instrumentation's `chat {model}` span both exist for an agent model
  call: the first is Strands' wrapper, the second the actual HTTP call.
- LangGraph node spans (`langgraph.node {name}`) have no GenAI equivalent; they carry
  `gen_ai.conversation.id` and Nexo-specific attributes.

[^genai-repo]: OpenTelemetry GenAI semantic conventions (development)
[^core]: OpenTelemetry semantic conventions (database spans, v1.44.0)
[^python-genai]: OpenTelemetry Python GenAI instrumentations
