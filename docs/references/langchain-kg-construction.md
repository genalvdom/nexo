---
type: Reference
title: "LangChain: constructing knowledge graphs from text"
description: LangChain's walkthrough of LLM-based graph construction (schema, coreference, disambiguation), and what Nexo adopted.
resource: https://www.langchain.com/blog/constructing-knowledge-graphs-from-text-using-openai-functions
tags: [reference, knowledge-graph, extraction, langchain]
status: draft
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-19T20:14:37Z }
sources:
  - id: blog
    resource: https://www.langchain.com/blog/constructing-knowledge-graphs-from-text-using-openai-functions
    title: Constructing knowledge graphs from text using OpenAI functions
    author: team:langchain
---

# What the post recommends

- Pipeline: coreference resolution, named entity recognition, entity disambiguation ("essential but
  often overlooked"), relation extraction.[^blog]
- "For any more serious project, you should define the node labels and relationship types";
  without that, relations drift (e.g. co-founder variants).
- Use the most complete identifier for each entity.
- Do not create separate nodes for dates or numbers; keep them as properties.
- Use large enough chunks that an entity and its references share a chunk (the post uses 2048
  tokens) so coreference works.

# How Nexo applies it

| Recommendation | Nexo |
|---|---|
| Defined labels and relationship types | ✓ closed entity types; [relation ontology](../components/relation-ontology.md) with synonyms and inverses |
| Most complete identifier | ✓ extraction prompt; resolution merges into the longest name |
| Disambiguation | ✓ [entity resolution](../components/entity-resolution.md) |
| Dates as properties | ✓ `valid_at` on edges; prompt forbids date/amount entities |
| Coreference across chunks | ✓ previous-chunk tail as context (`EXTRACTION_CONTEXT_CHARS`), evidence still from the chunk |
| General node/edge properties | deferred ([ADR-0010](../decisions/adr-0010-deferred-graph-enrichment.md)) |

[^blog]: Constructing knowledge graphs from text using OpenAI functions
