---
type: Architecture Decision
title: "ADR-0008: Relation ontology and a lexical graph in Neo4j"
description: Map predicates onto a configurable ontology with a RELATED_TO fallback, and store Document/Chunk structure alongside the domain graph.
tags: [adr, ontology, lexical-graph, neo4j]
status: draft
decision_status: accepted
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-19T20:14:37Z }
sources:
  - id: langchain
    resource: ../references/langchain-kg-construction.md
    title: LangChain, constructing knowledge graphs from text
  - id: builder
    resource: ../references/neo4j-llm-graph-builder.md
    title: Neo4j LLM Graph Builder
  - id: memgraph
    resource: ../references/memgraph-knowledge-graph-creation.md
    title: Memgraph, knowledge graph creation
---

# Context

Free-form predicates drifted in synonym and direction; the graph had chunk nodes but no document or
ordering, so the agent could not widen context around a chunk or scope by document.

# Decision

1. A JSON [relation ontology](../components/relation-ontology.md) (synonyms, inverses, type
   constraints) maps every predicate to one canonical relation and direction. Unknown or ill-typed
   predicates become `RELATED_TO {predicate}` instead of being dropped.[^langchain]
2. A lexical graph: `Document`, `PART_OF`, `FIRST_CHUNK`, `NEXT_CHUNK`, chunk `ordinal` and
   `section_path`, written in the same transaction as the domain graph.[^builder][^memgraph]

# Options considered

| Option | Against |
|---|---|
| Guided decoding with an enum of relations | Forces a choice even when nothing fits; loses the original wording. |
| Drop out-of-ontology triples | Loses recall silently. |
| Ontology mandatory | Every deployment would need a domain model before first use. |

# Consequences

- The ontology is optional; without it Nexo behaves as before (normalized free-form predicates).
- Ontology changes apply on re-ingestion; existing edges keep their old type until then.
- The agent prompt and schema description now include the lexical relationships, which it must
  exclude from entity paths (the example queries show how).

[^langchain]: LangChain, constructing knowledge graphs from text
[^builder]: Neo4j LLM Graph Builder
[^memgraph]: Memgraph, knowledge graph creation
