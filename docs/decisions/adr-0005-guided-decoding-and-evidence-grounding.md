---
type: Architecture Decision
title: "ADR-0005: Guided decoding plus evidence grounding for extraction"
description: Triples are produced with vLLM guided JSON, validated by Pydantic with feedback retries, and kept only if their quote is in the chunk.
tags: [adr, extraction, vllm, grounding]
status: draft
decision_status: accepted
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-19T20:14:37Z }
sources:
  - id: llm
    resource: ../../src/nexo/llm.py
    title: invoke_structured
  - id: ingest
    resource: ../../src/nexo/storage/ingest.py
    title: Grounding filter
---

# Context

A 70B open-weights model is reliable at JSON only when constrained, and any extracted edge becomes a
"fact" the agent will trust.

# Decision

- Ask vLLM for `response_format: json_schema` (token-level constraint).
- Validate with Pydantic (`extra="forbid"`, normalized predicates) and feed errors back, up to 3
  attempts.[^llm]
- Require a verbatim `evidence` quote and drop triples whose quote is not in the chunk.[^ingest]

# Options considered

| Option | Against |
|---|---|
| Function/tool calling for extraction | Depends on the tool-call parser; no stronger guarantee than guided JSON. |
| `with_structured_output` (LangChain) | Hides the retry-with-feedback loop. |
| No grounding check | Hallucinated edges enter the graph silently. |

# Consequences

Paraphrased quotes are lost (counted in `dropped.evidence_not_in_chunk`). Every surviving edge
carries a quote a reviewer can check.

[^llm]: invoke_structured
[^ingest]: Grounding filter
