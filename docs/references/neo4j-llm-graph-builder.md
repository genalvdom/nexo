---
type: Reference
title: "Neo4j LLM Graph Builder"
description: Neo4j Labs' document-to-graph tool - lexical graph, schema-guided extraction, duplicate merging, GraphRAG retrieval - and what Nexo adopted.
resource: https://neo4j.com/labs/genai-ecosystem/llm-graph-builder/
tags: [reference, knowledge-graph, neo4j, lexical-graph]
status: draft
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-19T20:14:37Z }
sources:
  - id: docs
    resource: https://neo4j.com/labs/genai-ecosystem/llm-graph-builder/
    title: Neo4j LLM Graph Builder
  - id: repo
    resource: https://github.com/neo4j-labs/llm-graph-builder
    title: llm-graph-builder repository (README settings)
---

# What it does

- Builds a lexical graph: `Document` nodes, chunks connected to the document and to each other, with
  embeddings and a vector index on chunks.[^docs]
- Links extracted entities to the chunks they came from; extraction quality improves when the graph
  schema is configured (or derived from sample text).
- Post-processing: merges duplicate entities by embedding similarity plus text distance
  (`DUPLICATE_SCORE_VALUE`, `DUPLICATE_TEXT_DISTANCE`), optional entity embeddings, kNN `SIMILAR`
  edges between chunks, removal of disconnected nodes, community summaries.[^repo]
- Retrieval combines vector and full-text search, then follows entity relationships up to two hops.

# How Nexo applies it

| Feature | Nexo |
|---|---|
| `Document`, `PART_OF`, `FIRST_CHUNK`, `NEXT_CHUNK` | ✓ [data model](../architecture/data-model.md) |
| Entities linked to chunks | ✓ `MENTIONED_IN` with surface form and resolution method |
| Configured schema | ✓ entity types + [relation ontology](../components/relation-ontology.md) |
| Duplicate merging | ✓ [entity resolution](../components/entity-resolution.md), by alias and model rather than embedding score |
| Embeddings in Neo4j, kNN `SIMILAR`, communities | deferred ([ADR-0010](../decisions/adr-0010-deferred-graph-enrichment.md)); vectors live in the [chunk store](../components/chunk-store.md) |
| Full-text index | ✓ text index on `Entity.name` |

[^docs]: Neo4j LLM Graph Builder
[^repo]: llm-graph-builder repository (README settings)
