---
type: Reference
title: "Neo4j: how to build a knowledge graph"
description: Neo4j's step-by-step method (use case first, property graph, organizing principle, entity resolution, iterate on a sample) and how Nexo maps to it.
resource: https://neo4j.com/blog/knowledge-graph/how-to-build-knowledge-graph/
tags: [reference, knowledge-graph, neo4j, modeling]
status: draft
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-19T20:14:37Z }
sources:
  - id: blog
    resource: https://neo4j.com/blog/knowledge-graph/how-to-build-knowledge-graph/
    title: How to build a knowledge graph
    author: team:neo4j
---

# What the post recommends

1. Start from a focused use case and the questions the graph must answer.[^blog]
2. Use a property graph, so relationships carry their own properties.
3. Model labels, relationship types and properties around those questions.
4. Add an organizing principle such as a taxonomy; "save ontologies for when you truly need them".
5. Clean the data: standardize formats and resolve entities before loading.
6. Start with a small sample, test simple then advanced business questions, and revise the model.

# How Nexo applies it

| Step | Nexo |
|---|---|
| Use case | Relationship tracing with cited evidence ([overview](../architecture/overview.md)) |
| Property graph | ✓ edges carry `evidence`, `certainty`, `valid_at`, provenance |
| Organizing principle | ✓ closed entity types; optional [relation ontology](../components/relation-ontology.md) |
| Entity resolution before load | ✓ [entity resolution](../components/entity-resolution.md) runs before the write transaction |
| Small sample, measured | `nexo eval-extraction` and `nexo eval` ([evaluation playbook](../operations/evaluation.md)) |

[^blog]: How to build a knowledge graph
