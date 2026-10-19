---
type: Reference
title: "AWS guidance: choosing a vector database for RAG"
description: AWS Prescriptive Guidance comparing AWS vector stores, and how its criteria apply to Nexo's chunk store.
resource: https://docs.aws.amazon.com/prescriptive-guidance/latest/choosing-an-aws-vector-database-for-rag-use-cases/introduction.html
tags: [reference, aws, vector-store]
status: draft
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-19T20:14:37Z }
sources:
  - id: guide
    resource: https://docs.aws.amazon.com/prescriptive-guidance/latest/choosing-an-aws-vector-database-for-rag-use-cases/introduction.html
    title: Choosing an AWS vector database for RAG use cases
    author: team:aws-prescriptive-guidance
---

# Options compared

| Service | Recommended when (per the guide) |
|---|---|
| Amazon Kendra | Enterprise search with minimal setup. |
| Amazon OpenSearch Service | High-throughput queries with low latency; full-text alongside vector search. |
| Aurora / RDS PostgreSQL + pgvector | Combine relational queries with vector search; strong (ACID) consistency. |
| Amazon DocumentDB | MongoDB-compatible applications. |
| Amazon MemoryDB | Ultra-low latency; semantic caching. |
| Amazon Neptune Analytics | Graph-based knowledge with vector search (GraphRAG). |
| Amazon S3 Vectors | Billions of vectors, infrequent retrieval, lowest cost. |
| Bedrock Knowledge Bases | Managed RAG; choose a database directly when you need full control of the pipeline. |

[^guide]

# Applied to Nexo

Nexo's chunk store must return chunks by id right after ingestion, filter on metadata, and
occasionally rank by similarity, while Neo4j holds the graph and the LLM is self-hosted. That points
to pgvector first and OpenSearch second; see
[ADR-0004](../decisions/adr-0004-chunk-store-interface-and-pgvector.md). The guide does not discuss
get-by-id directly; that ranking is inferred from its consistency and relational-query criteria.

[^guide]: Choosing an AWS vector database for RAG use cases
