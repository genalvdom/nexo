---
type: Component
title: Structure-aware chunking
description: Heading-aware splits, table flattening, glossary notes and document lint.
resource: ../../src/nexo/storage/chunking.py
tags: [module-a, chunking, authoring]
status: draft
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-19T20:14:37Z }
sources:
  - id: chunking
    resource: ../../src/nexo/storage/chunking.py
    title: Chunking module
  - id: aws-writing
    resource: ../references/aws-rag-writing-best-practices.md
    title: AWS guidance, writing best practices for RAG
---

# Behavior

| Function | What it does |
|---|---|
| `split_document` | Splits on `#`–`####` headings (`MarkdownHeaderTextSplitter`), then by size inside each section (`RecursiveCharacterTextSplitter`). Each chunk keeps its `section_path`, e.g. `["Policy", "Scope"]`. |
| `flatten_markdown_tables` | Rewrites each table row as `- Row N: Col=value; Col=value`, so a row stays meaningful when split from its header. |
| `glossary_notes` | Appends `Definitions: ALB = Application Load Balancer` for whole-word acronyms found in the chunk (from `GLOSSARY_PATH`). |
| `lint_document` | Warns about no headings, images or links, and sections over 6000 characters. |

The chunk **text** is kept exactly as split, since it is the evidence extraction is checked against.
Only the **embedded** text gets the `title > section path` header and glossary notes, which makes each
chunk self-contained for retrieval.[^chunking]

# Authoring guidance

Lint warnings point authors at the fixes the AWS writing guidance recommends:[^aws-writing] use real
headings, replace tables with lists, describe images in text, define abbreviations, and split long
documents into self-contained sections with clear titles.

[^chunking]: Chunking module
[^aws-writing]: AWS guidance, writing best practices for RAG
