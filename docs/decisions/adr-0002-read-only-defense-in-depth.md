---
type: Architecture Decision
title: "ADR-0002: Read-only Cypher through three independent layers"
description: Agent-authored Cypher is constrained by a guard, a READ transaction and a database role, not by any one of them.
tags: [adr, security, neo4j, cypher]
status: draft
decision_status: accepted
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-19T20:14:37Z }
sources:
  - id: graph-store
    resource: ../../src/nexo/storage/graph_store.py
    title: Cypher guard and read transaction
  - id: it
    resource: ../../tests/test_neo4j_integration.py
    title: Server-side write refusal test
---

# Context

The agent writes arbitrary Cypher from model output, which can be steered by text inside the corpus
(indirect prompt injection). A single regex is easy to bypass; a single database role is not available
on Community Edition.

# Decision

Apply three layers:[^graph-store]

1. A guard that rejects writes, multiple statements and procedure calls, with literals and comments
   stripped first.
2. A READ transaction, so the server refuses writes even if the guard is bypassed (tested against
   Neo4j 5.26).[^it]
3. On Enterprise, a reader account with `DENY TRAVERSE` on `:PII` / `:PHI`.

Plus a query timeout and a row cap, so a read-only query cannot exhaust the database.

# Options considered

| Option | Against |
|---|---|
| Parameterized query templates only | Removes the agent's ability to explore multi-hop paths it was not designed for. |
| Text-to-Cypher validation with a parser | Better than regex, but still bypassable alone; adds a dependency. |
| Guard only | One bug away from writes. |

# Consequences

Some legitimate reads are rejected (a property named `set`). Errors go back to the model as data, so it
can rewrite the query.

[^graph-store]: Cypher guard and read transaction
[^it]: Server-side write refusal test
