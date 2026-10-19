---
type: Reference
title: "AWS guidance: RAG for healthcare use cases"
description: AWS Prescriptive Guidance on multi-retriever (graph + vector) RAG, controls and evaluation for healthcare; what Nexo adopted.
resource: https://docs.aws.amazon.com/prescriptive-guidance/latest/rag-healthcare-use-cases/introduction.html
tags: [reference, aws, healthcare, graph-rag, evaluation]
status: draft
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-19T20:14:37Z }
sources:
  - id: guide
    resource: https://docs.aws.amazon.com/prescriptive-guidance/latest/rag-healthcare-use-cases/introduction.html
    title: Retrieval Augmented Generation for healthcare use cases
    author: team:aws-prescriptive-guidance
---

# What the guide recommends

- A multi-retriever RAG: a knowledge graph (Amazon Neptune) for patient-centric and temporal questions,
  a vector knowledge base (Amazon OpenSearch Service) for diagnostic, procedural and research questions,
  and a hybrid strategy that merges both, chosen by query intent.[^guide]
- LLM entity extraction capturing temporal relationships and certainty, normalized to clinical
  terminologies (RxNorm, ICD-10-CM, SNOMED CT, MeSH, UMLS), with a schema-validation step before
  triples are stored.
- Graph querying by direct Cypher with the schema and few-shot examples in the prompt.
- Controls: encryption, fine-grained access control, guardrails, and human review by clinicians and
  subject-matter experts.
- Evaluation: extraction accuracy, precision and an adjusted recall ("capture rate") that penalizes
  false values; retrieval relevancy, context precision and faithfulness; LLM-as-a-judge (pairwise,
  single-answer, reference-guided).

# How Nexo applies it

| Recommendation | Where |
|---|---|
| Intent-based graph / vector / hybrid routing | [Orchestration graph](../components/orchestration-graph.md) router `strategy` |
| Certainty and temporal qualifiers on edges | [Triple extraction](../components/triple-extraction.md) `certainty`, `valid_at` |
| Terminology codes | `proposed_codes`, marked unverified |
| Schema validation before storage | Closed entity types, normalized predicates, optional [relation ontology](../components/relation-ontology.md) |
| Schema + few-shot Cypher in the prompt | [Investigator agent](../components/investigator-agent.md) |
| Fine-grained access control | [Sensitive data detection](../components/sensitive-data-detection.md) |
| Human review | [Human review](../operations/human-review.md) |
| Evaluation metrics | [Evaluation](../components/evaluation.md) |

# Not adopted

- The "previous questions" cache: caching answers that passed human review has release-control
  implications; deferred.
- Managed AWS services (Neptune, Bedrock agents): Nexo uses self-hosted vLLM and Neo4j.

[^guide]: Retrieval Augmented Generation for healthcare use cases
