---
type: Architecture Decision
title: "ADR-0003: Durable checkpoints for human review"
description: Human review uses LangGraph interrupt/resume backed by SQLite or Postgres, never an in-memory saver outside tests.
tags: [adr, langgraph, human-in-the-loop, durability]
status: draft
decision_status: accepted
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-19T20:14:37Z }
sources:
  - id: service
    resource: ../../src/nexo/service.py
    title: open_checkpointer
  - id: test-graph
    resource: ../../tests/test_graph.py
    title: Restart durability test
---

# Context

A review can take hours and happen in a different process or replica from the one that started the
investigation.

# Decision

The compliance node pauses with `interrupt()`; reviewers resume with `Command(resume=decision)`. The
checkpointer is `sqlite` by default (single node) or `postgres` (multiple replicas); `memory` exists
for tests only.[^service] A test starts a run with one SQLite saver and approves it from a new one.[^test-graph]

# Options considered

| Option | Against |
|---|---|
| `interrupt_before=["compliance"]` + `update_state` | Reviewer input is not validated by the node; harder to re-prompt on bad input. |
| External ticketing with a callback | More moving parts; state split across systems. |
| In-memory saver | Loses every pending review on restart. |

# Consequences

Pending reviews survive restarts and deploys. Postgres is required to run more than one replica.
Graph-state values are plain JSON, so any checkpointer can store them.

[^service]: open_checkpointer
[^test-graph]: Restart durability test
