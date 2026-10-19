---
type: Reference
title: "AWS guidance: writing best practices for RAG"
description: AWS Prescriptive Guidance on authoring source documents for retrieval, and the ingestion features that apply it.
resource: https://docs.aws.amazon.com/prescriptive-guidance/latest/writing-best-practices-rag/introduction.html
tags: [reference, aws, authoring, chunking]
status: draft
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-19T20:14:37Z }
sources:
  - id: guide
    resource: https://docs.aws.amazon.com/prescriptive-guidance/latest/writing-best-practices-rag/introduction.html
    title: Writing best practices to optimize RAG applications
    author: team:aws-prescriptive-guidance
---

# What the guide recommends

- Use headings and subheadings properly; keep numbering sequential.
- Replace tables with multi-level bullets or flat syntax.
- Describe images in text; links and graphics consume the retrieval token budget.
- Add a short summary after each heading; define abbreviations; avoid inconsistent terminology.
- Restructure large documents into smaller, self-contained documents with clear titles.
- Audit and prioritize the most-used documents, working with subject-matter experts.[^guide]

The guide gives no numeric chunk sizes and names no specific metadata fields.

# How Nexo applies it

| Recommendation | Where |
|---|---|
| Headings | Heading-aware splitting with `section_path` ([chunking](../components/chunking.md)) |
| Replace tables | `flatten_markdown_tables` |
| Define abbreviations | `GLOSSARY_PATH` notes in embedded text |
| Self-contained sections | Title and section path prepended to embedded text |
| Author feedback | `lint_warnings` in the [ingestion report](../components/ingestion-pipeline.md) |

[^guide]: Writing best practices to optimize RAG applications
