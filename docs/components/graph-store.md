---
type: Data Store
title: Graph store
description: Neo4j access over Bolt - atomic document replacement for ingestion and bounded read-only queries for the agent.
resource: ../../src/nexo/storage/graph_store.py
tags: [module-a, neo4j, cypher, security]
status: draft
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-19T20:14:37Z }
sources:
  - id: graph-store
    resource: ../../src/nexo/storage/graph_store.py
    title: GraphStore
  - id: rbac
    resource: ../../deploy/neo4j-rbac.cypher
    title: Neo4j Enterprise reader role
---

# Interface

| Method | Used by | Behavior |
|---|---|---|
| `from_settings(settings, read_only)` | runtime, ingestor | Read-only instances use `NEO4J_READ_USER` when set. |
| `ensure_schema()` | ingestor | Creates constraints and indexes (idempotent). |
| `replace_source(document, chunks, triples)` | ingestor | Swaps one document's lexical and domain subgraph in a single write transaction. |
| `find_candidates(type, tokens, limit)` | resolver | Same-type entities whose name or alias contains a token. |
| `run_read_query(cypher)` | agent tool | READ transaction, `NEO4J_QUERY_TIMEOUT_S` (15 s) timeout, `NEO4J_MAX_ROWS` (50) cap with a `truncated` flag. |
| `describe_schema()` | runtime | Static data model plus the relation patterns present, with counts and direction, injected into the agent prompt. |

Data model: [Knowledge graph data model](../architecture/data-model.md).[^graph-store]

# Read-only enforcement

Agent-authored Cypher passes three independent layers:

1. **Guard** — `validate_read_only_cypher` strips comments and string literals, then rejects multiple
   statements, write clauses (`CREATE`, `MERGE`, `SET`, `DELETE`, `REMOVE`, `DROP`, `FOREACH`,
   `LOAD CSV`, `... IN TRANSACTIONS`, admin commands, `SHOW`, `USE`) and procedure calls other than
   `db.labels()`, `db.relationshipTypes()` and `db.propertyKeys()`. `CALL { }` subqueries are allowed.
2. **READ transaction** — the server refuses writes even if the guard is bypassed (verified against
   Neo4j 5.26).
3. **Database role** — on Enterprise, a reader account with `DENY TRAVERSE` on `:PII` / `:PHI`
   labels.[^rbac]

See [ADR-0002](../decisions/adr-0002-read-only-defense-in-depth.md).

# Failure handling

Connection drops (`ServiceUnavailable`, `SessionExpired`) are retried with jittered backoff, up to 4
attempts. Transient server errors inside managed transactions are retried by the driver itself.

# Telemetry

Each call is a CLIENT span named by its operation (`agent_query`, `replace_source`,
`find_candidates`) with `db.system.name=neo4j`, `db.namespace`, `db.query.summary` and
`server.address`/`server.port`. Agent-authored Cypher is attached as `db.query.text` only when content
capture is on. See [Observability](../operations/observability.md).

[^graph-store]: GraphStore
[^rbac]: Neo4j Enterprise reader role
