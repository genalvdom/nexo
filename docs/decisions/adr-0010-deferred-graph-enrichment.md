---
type: Architecture Decision
title: "ADR-0010: Deferred graph enrichment"
description: Graph-construction techniques from the reference guides that Nexo deliberately postpones, with the trigger for revisiting each.
tags: [adr, knowledge-graph, roadmap]
status: draft
decision_status: accepted
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-19T20:14:37Z }
sources:
  - id: cookbook
    resource: ../references/anthropic-claude-cookbook.md
    title: Claude Cookbook, knowledge graph guide
  - id: builder
    resource: ../references/neo4j-llm-graph-builder.md
    title: Neo4j LLM Graph Builder
  - id: langchain
    resource: ../references/langchain-kg-construction.md
    title: LangChain, constructing knowledge graphs from text
  - id: memgraph
    resource: ../references/memgraph-knowledge-graph-creation.md
    title: Memgraph, knowledge graph creation
---

# Decision

These are recommended by the reference guides but postponed; each has a trigger.

| Technique | Source | Why later | Revisit when |
|---|---|---|---|
| Entity embeddings for resolution blocking | Cookbook, Graph Builder[^cookbook][^builder] | Token blocking works without new infrastructure. | Resolution recall is low in `nexo eval-extraction` or reviewers report unmerged duplicates. |
| General node/edge properties (`properties: [{key, value}]`) | LangChain[^langchain] | Property keys drift and can carry PII outside sensitivity labels. | A use case needs attributes (doses, amounts) as query filters. |
| kNN `SIMILAR` edges between chunks | Graph Builder | Seeds already give semantic entry points. | Questions need "related passages" without shared entities. |
| Hub-entity profiles, community summaries | Cookbook, Graph Builder | Help global questions, not relationship tracing. | Broad "summarize everything about X" questions become a requirement. |
| Direct import of structured data (tables, CSV) | Memgraph[^memgraph] | Needs per-source mappings. | A structured source (registry, CRM export) is onboarded. |

[^cookbook]: Claude Cookbook, knowledge graph guide
[^builder]: Neo4j LLM Graph Builder
[^langchain]: LangChain, constructing knowledge graphs from text
[^memgraph]: Memgraph, knowledge graph creation
