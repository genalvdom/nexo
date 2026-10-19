---
type: Reference
title: "Memgraph: knowledge graph creation"
description: Memgraph's guidance on modeling and building knowledge graphs for GraphRAG, and what Nexo adopted.
resource: https://memgraph.com/docs/ai-ecosystem/graph-rag/knowledge-graph-creation
tags: [reference, knowledge-graph, modeling, graph-rag]
status: draft
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-19T20:14:37Z }
sources:
  - id: guide
    resource: https://memgraph.com/docs/ai-ecosystem/graph-rag/knowledge-graph-creation
    title: Memgraph, knowledge graph creation
  - id: modeling
    resource: https://memgraph.com/docs/data-modeling/modeling-guides/model-a-knowledge-graph
    title: Memgraph, model a knowledge graph
---

# What the guide recommends

- Model first: a good model supports multi-hop reasoning; make things you traverse nodes, not
  properties.[^modeling]
- Import already-structured data directly rather than through an LLM.
- Pipeline: preprocessing, entity recognition, relation extraction, contextual understanding and
  disambiguation, then post-processing to refine and validate.[^guide]
- Lexical structure (Unstructured2Graph): chunk nodes, entities linked to the chunks that mention
  them, chunks linked in order; retrieval finds a vector "pivot" and expands a few hops.

# How Nexo applies it

| Recommendation | Nexo |
|---|---|
| Model for traversal | ✓ closed entity types, [relation ontology](../components/relation-ontology.md) |
| Disambiguation, validation | ✓ [entity resolution](../components/entity-resolution.md), evidence check, ontology mapping |
| Chunks, `MENTIONED_IN`, ordered `NEXT_CHUNK` | ✓ [data model](../architecture/data-model.md) |
| Vector pivot, then graph expansion | ✓ seeds for `vector`/`hybrid` strategies |
| Direct import of structured data | deferred ([ADR-0010](../decisions/adr-0010-deferred-graph-enrichment.md)); tables are flattened and extracted |

[^guide]: Memgraph, knowledge graph creation
[^modeling]: Memgraph, model a knowledge graph
