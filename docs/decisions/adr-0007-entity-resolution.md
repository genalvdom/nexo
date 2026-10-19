---
type: Architecture Decision
title: "ADR-0007: Conservative entity resolution with recorded merges"
description: Resolve mentions by normalized key, alias, then a model arbiter over token-blocked candidates; record every merge on MENTIONED_IN so it is auditable and reversible.
tags: [adr, entity-resolution, knowledge-graph]
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
---

# Context

Exact-key matching left "Acme Holdings Inc." and "Acme" as two nodes, breaking multi-hop paths across
documents. All five knowledge-graph sources treat resolution as essential. The domain includes
conditions and medications, where a wrong merge is worse than a missed one.

# Decision

See [Entity resolution](../components/entity-resolution.md): type-safe normalization, alias matching,
then an LLM arbiter limited to candidates it was shown, defaulting to "no match" when unsure. Surface
forms and methods are stored per mention; aliases are derived from them.[^cookbook]

# Options considered

| Option | For | Against |
|---|---|---|
| **Alias + model arbiter, token blocking** (chosen) | Uses descriptions; no extra infrastructure; auditable. | One model call per batch of unresolved mentions. |
| Embedding similarity threshold (Graph Builder style)[^builder] | Fast at scale. | Needs entity embeddings; thresholds over-merge near-synonyms (drug classes, subsidiaries). |
| String similarity only | Cheap. | Fails on "Buzz Aldrin" / "Edwin Aldrin" and acronyms. |
| No resolution | Simplest. | Fragmented graph. |

# Consequences

- Blocking is token-based; synonyms with no shared token (acronyms not stated as aliases) are
  missed. Embedding blocking is the next step if recall is too low
  ([ADR-0010](adr-0010-deferred-graph-enrichment.md)).
- A merge into the wrong entity can be found from `MENTIONED_IN.resolution = 'llm'` and undone by
  re-ingesting the document with `ENTITY_RESOLUTION=deterministic`.

[^cookbook]: Claude Cookbook, knowledge graph guide
[^builder]: Neo4j LLM Graph Builder
