# Nexo

Graph RAG investigation service: LangGraph orchestration, a Strands Agents micro-agent, a self-hosted vLLM
model (Llama 3.3 70B), Neo4j and a vector chunk store, traced end to end with OpenTelemetry.

```
            ┌────────────── LangGraph StateGraph (checkpointed) ──────────────┐
request ──► │ router ──► investigator ─────────────► compliance ──interrupt──► │──► reviewer approves ──► answer
            │   │          │ @task: Strands Agent        (pure checks)       │
            │   ▼          │   ├─ query_knowledge_graph ──► Neo4j (READ tx)  │
            │  END         │   └─ fetch_vector_chunks  ──► chunk store       │
            └──────────────┴─────────────── vLLM (OpenAI API) ───────────────┘
ingest: document ─► heading-aware chunks ─► embeddings ─► chunk store
                                         └► vLLM triple extraction ─► evidence check ─► Neo4j (chunk_id on every node/edge)
```

| Module | Code |
| --- | --- |
| A. Storage | `storage/` — `ingest.py`, `chunking.py`, `schemas.py`, `graph_store.py`, `vector_store.py`, `sensitive_data.py` |
| B. Micro-agent | `agents/` — `investigator.py` (Strands Agent), `tools.py` (the two tools) |
| C. Orchestration | `orchestration/` — `graph.py` (3 nodes), `state.py`, `compliance.py` |
| Wiring | `service.py`, `cli.py`, `telemetry.py`, `llm.py`, `evaluation.py` |

## Run

```bash
cp .env.example .env                                   # fill in secrets
docker compose up -d neo4j otel-collector jaeger
docker compose --profile gpu up -d                     # vLLM: needs 4x80GB GPUs
pip install -e ".[dev]"
nexo ingest docs/memo.md --doc-type memo --effective-date 2025-06-30
nexo ask "How is Acme Holdings connected to Gamma Clinics?"   # prints thread_id + review packet
nexo review <thread_id> --approve --reviewer you@corp
```

Traces: http://localhost:16686 (Jaeger). Neo4j Enterprise least-privilege reader: `deploy/neo4j-rbac.cypher`.

## Test

```bash
pytest                                                  # offline: fakes for vLLM, real Strands + LangGraph
podman run -d -p 127.0.0.1:7688:7687 -e NEO4J_AUTH=neo4j/nexo-test-pass neo4j:5.26-community
NEO4J_TEST_URI=bolt://127.0.0.1:7688 NEO4J_TEST_PASSWORD=nexo-test-pass pytest tests/test_neo4j_integration.py
```

## Production notes

- `LocalChunkStore` is single-node. Implement `ChunkStore` on Aurora/RDS PostgreSQL + pgvector (exact id lookup, SQL
  metadata filters, ACID) or OpenSearch Service (hybrid lexical + vector at high QPS).
- Human review pauses must survive restarts: use `CHECKPOINT_BACKEND=postgres` with more than one replica.
- `SENSITIVE_DATA_PROVIDER=comprehend_medical` sends chunk text to Amazon Comprehend Medical; enable only where that
  flow is approved. Entity `proposed_codes` are LLM output until verified against a terminology service.
