---
type: Component
title: Relation ontology
description: Canonical relation types with synonyms, inverses and type constraints; out-of-ontology predicates become RELATED_TO with the original wording.
resource: ../../src/nexo/storage/ontology.py
tags: [module-a, ontology, schema, knowledge-graph]
status: draft
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-19T20:14:37Z }
sources:
  - id: ontology
    resource: ../../src/nexo/storage/ontology.py
    title: Ontology
  - id: example
    resource: ../../deploy/ontology.example.json
    title: Example ontology
  - id: langchain
    resource: ../references/langchain-kg-construction.md
    title: LangChain, constructing knowledge graphs from text
---

# Why

Free-form predicates drift: `CO_FOUNDED`, `COFOUNDER_OF` and `FOUNDED_BY` describe one fact in three
shapes and two directions, and Cypher that follows one misses the others. Defining relationship types
is the first recommendation of the LangChain and Neo4j guidance.[^langchain]

# Schema

`ONTOLOGY_PATH` points at a JSON file:[^example]

```json
{"relations": [
  {"name": "FOUNDED", "description": "The person founded or co-founded the organization.",
   "source_types": ["Person"], "target_types": ["Organization"],
   "synonyms": ["CO_FOUNDED", "COFOUNDER_OF"], "inverses": ["FOUNDED_BY"]}
]}
```

| Field | Meaning |
|---|---|
| `name` | Canonical relationship type written to Neo4j. |
| `source_types` / `target_types` | Allowed head and tail entity types; empty means any. |
| `synonyms` | Same meaning, same direction. |
| `inverses` | Same meaning, head and tail swapped. |

A predicate may belong to only one relation; conflicting files fail to load.

# Mapping

`Ontology.map(predicate, head_type, tail_type)`:[^ontology]

1. Look up the predicate (canonical, synonym or inverse); inverses swap head and tail.
2. If the types fit, use the canonical relation; if they fit only reversed, swap (the model extracted
   it backwards).
3. Otherwise, or if the predicate is unknown: `RELATED_TO`, keeping the original in `predicate`.

Edges record every predicate that produced them in `extracted_as`. `RELATED_TO` edges are keyed by
`predicate`, so different unknown relations between the same pair stay distinct. The extraction
prompt lists the relations with their types, and the ingestion report counts `canonical`,
`remapped` and `fallback` relations.

Without `ONTOLOGY_PATH`, predicates are only normalized to UPPER_SNAKE_CASE.

[^ontology]: Ontology
[^example]: Example ontology
[^langchain]: LangChain, constructing knowledge graphs from text
