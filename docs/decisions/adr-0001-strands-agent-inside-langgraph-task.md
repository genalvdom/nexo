---
type: Architecture Decision
title: "ADR-0001: Run the Strands agent inside a LangGraph @task"
description: The fixed workflow lives in LangGraph; open-ended reasoning lives in one Strands agent called from a checkpointed task.
tags: [adr, langgraph, strands]
status: draft
decision_status: accepted
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-19T20:14:37Z }
sources:
  - id: graph
    resource: ../../src/nexo/orchestration/graph.py
    title: Orchestration graph
---

# Context

Investigations need two kinds of control: steps that must always happen in order (validate, review,
release) and reasoning that cannot be scripted (which paths to follow, when evidence suffices).

# Decision

LangGraph owns the 3-node workflow; a Strands agent owns the reasoning and is invoked from a `@task`
inside the `investigator` node.[^graph] See [the handoff](../architecture/langgraph-strands-handoff.md).

# Options considered

| Option | For | Against |
|---|---|---|
| **Strands inside a LangGraph task** (chosen) | Checkpointed agent result; retries; audit trail in graph state; agent stays free-form. | Two frameworks to learn. |
| LangGraph ReAct agent only | One framework. | Agent loop and workflow state mix; harder to keep the agent unscripted. |
| Strands only (multi-agent graph) | One framework. | No built-in durable interrupt/resume for multi-hour human review. |
| Call the agent from the node without `@task` | Simpler. | A replay re-runs the expensive, non-deterministic agent. |

# Consequences

- Resume after review never re-runs the agent.
- A retry re-runs the whole investigation, which is acceptable only because both tools are read-only.
- Agent internals (turns, tool calls) are visible through Strands spans, not graph state; the graph
  stores a summary in `agent_outputs`.

[^graph]: Orchestration graph
