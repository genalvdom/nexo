---
type: Interface
title: Chunk store
description: Get-by-id, filtered similarity search and delete-by-document for chunk text and vectors.
resource: ../../src/nexo/storage/vector_store.py
tags: [module-a, vector-store, embeddings]
status: draft
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-19T20:14:37Z }
sources:
  - id: vector-store
    resource: ../../src/nexo/storage/vector_store.py
    title: ChunkStore and LocalChunkStore
  - id: aws-vdb
    resource: ../references/aws-vector-database-choice.md
    title: AWS guidance, choosing a vector database for RAG
---

# Contract

```python
class ChunkStore(Protocol):
    def upsert(self, chunks, embedding_texts) -> None: ...
    def get_by_ids(self, chunk_ids) -> list[ChunkRecord]: ...       # graph -> text hop
    def search(self, query, k, chunk_filter) -> list[ChunkRecord]: ...  # vector seeding
    def delete_source(self, source_id, keep=frozenset()) -> int: ...  # re-ingestion
```

`get_by_ids` returns records in request order and silently skips unknown ids.[^vector-store]

# Schema

`ChunkRecord`:

| Field | Description |
|---|---|
| `chunk_id` | `chk_` + 16 hex; deterministic. |
| `source_id`, `ordinal` | Document and position. |
| `text` | Exact chunk text (evidence). |
| `section_path`, `title` | Heading path and document title. |
| `doc_type`, `source_uri`, `effective_date` | Document metadata, filterable. |
| `sensitivity` | `public`, `internal`, `pii` or `phi`. |
| `ingested_at`, `schema_version` | Bookkeeping. |

`ChunkFilter` (`doc_types`, `source_ids`, `effective_from`, `effective_to`, `max_sensitivity`) is
applied before ranking in `search` and again when the agent fetches chunks. Undated chunks fail any
date-bounded filter.

# Implementations

| Backend | Status | Use |
|---|---|---|
| `LocalChunkStore` | implemented | Wraps LangChain `InMemoryVectorStore`; persisted to `VECTOR_STORE_PATH` with an atomic file replace. Single node only. |
| Aurora/RDS PostgreSQL + pgvector | recommended next | Primary-key lookup, SQL metadata filters, ACID writes, so a chunk is readable as soon as Neo4j references it. |
| Amazon OpenSearch Service | alternative | When hybrid lexical + vector search or very high query rates matter; eventual consistency after writes. |

The recommendation follows the AWS vector database guidance's decision criteria.[^aws-vdb] See
[ADR-0004](../decisions/adr-0004-chunk-store-interface-and-pgvector.md).

[^vector-store]: ChunkStore and LocalChunkStore
[^aws-vdb]: AWS guidance, choosing a vector database for RAG
