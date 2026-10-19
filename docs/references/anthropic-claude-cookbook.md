---
type: Reference
title: "Claude Cookbook: knowledge graph guide"
description: Anthropic's guide to building a knowledge graph with an LLM - typed extraction, LLM entity resolution with descriptions, profiles and evaluation - and what Nexo adopted.
resource: https://platform.claude.com/cookbook/capabilities-knowledge-graph-guide
tags: [reference, knowledge-graph, extraction, entity-resolution]
status: draft
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-19T20:14:37Z }
sources:
  - id: guide
    resource: https://platform.claude.com/cookbook/capabilities-knowledge-graph-guide
    title: Claude Cookbook, knowledge graph guide
    author: team:anthropic
  - id: notebook
    resource: https://github.com/anthropics/claude-cookbooks/blob/main/capabilities/knowledge_graph/guide.ipynb
    title: Source notebook
---

# What the guide recommends

- Extract with a closed set of entity types and structured output; every relation must connect two
  extracted entities.[^guide]
- Give each entity a one-sentence description, "used later to disambiguate entities with similar
  names".
- Resolve entities with an LLM per type, because string similarity fails ("Edwin Aldrin" vs "Buzz
  Aldrin"); at scale, block candidates first (shared tokens, embedding similarity) in blocks of 50-100,
  resolve new documents against the existing canonical set, and keep an alias table.[^notebook]
- Build profiles for hub entities from their excerpts, without inventing facts.
- Measure extraction precision and recall against a gold set and iterate on the prompt.

# How Nexo applies it

| Recommendation | Nexo | Where |
|---|---|---|
| Closed types, structured output | ✓ | [Triple extraction](../components/triple-extraction.md) |
| Descriptions as tie-breakers | ✓ | Passed to the resolution model |
| LLM resolution with blocking, against the existing set | ✓ | [Entity resolution](../components/entity-resolution.md) |
| Alias table | ✓ | `MENTIONED_IN.surface`, derived `Entity.aliases` |
| Embedding-based blocking | deferred | Token blocking today; see [ADR-0007](../decisions/adr-0007-entity-resolution.md) |
| Hub profiles | deferred | [ADR-0010](../decisions/adr-0010-deferred-graph-enrichment.md) |
| Gold-set extraction scoring | ✓ | `nexo eval-extraction` ([evaluation](../components/evaluation.md)) |

Nexo also checks each evidence quote against its chunk, which the guide does not do.

[^guide]: Claude Cookbook, knowledge graph guide
[^notebook]: Source notebook
