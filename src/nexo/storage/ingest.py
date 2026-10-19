"""Module A - document ingestion: chunks -> vectors, triples -> Neo4j.

Pipeline for one document:

1. Lint + flatten tables, heading-aware chunking (`chunking.py`).
2. Sensitivity classification per chunk (declared floor + PII/PHI detector),
   optional redaction before anything is embedded or extracted.
3. Upsert chunks into the vector store under deterministic `chunk_id`s.
4. LLM triple extraction per chunk (bounded concurrency - vLLM's continuous
   batching turns parallel requests into throughput), Pydantic-validated.
5. Drop triples whose evidence quote is not in the chunk (hallucination
   guard) or whose predicate is outside the configured ontology.
6. Replace the document's subgraph in one Neo4j transaction.
7. Delete superseded vector chunks.

Steps 3 -> 6 -> 7 keep the invariant that every `chunk_id` in Neo4j resolves
in the vector store, even if the process dies between steps.
"""

from __future__ import annotations

import contextvars
import logging
from collections import Counter
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from nexo.config import Settings
from nexo.llm import StructuredOutputError, invoke_structured
from nexo.storage.chunking import flatten_markdown_tables, glossary_notes, lint_document, split_document
from nexo.storage.schemas import (
    ChunkRecord,
    DocumentMetadata,
    EntityType,
    ExtractionResult,
    GroundedTriple,
)
from nexo.storage.sensitive_data import SensitiveDataDetector, classify, redact
from nexo.storage.vector_store import ChunkStore
from nexo.telemetry import traced_span

logger = logging.getLogger(__name__)

EXTRACTION_SYSTEM_PROMPT = """\
You extract a knowledge graph from one passage of a document.

Return entity-relation-entity triples as JSON matching the schema.
- Entity types: {entity_types}. Pick the most specific type; skip entities that fit none.
- Use canonical full names exactly as written ("Acme Holdings Inc.", not "the company"); resolve pronouns.
- Predicates are short, specific, directional verbs in UPPER_SNAKE_CASE (ACQUIRED, REPORTS_TO,
  DIAGNOSED_WITH), oriented head -> tail. Avoid vague predicates like RELATED_TO.{relation_rule}
- Only facts the passage states. No outside knowledge, no inference across passages.
- evidence: a verbatim quote (max ~200 characters) from the passage that states the fact.
- certainty: "asserted", "possible" (hedged: may, suspected) or "negated" (ruled out, denied).
- valid_at: ISO date only when the passage gives the date the fact holds.
- proposed_codes: only codes printed in the passage (ICD-10-CM, RxNorm, SNOMED CT, MeSH, UMLS).
- Return {{"triples": []}} if the passage states no relationships.
"""


class GraphWriter(Protocol):
    def replace_source(self, source_id: str, triples: Sequence[GroundedTriple]) -> int: ...


class IngestionReport(BaseModel):
    source_id: str
    chunk_count: int
    triples_extracted: int
    triples_written: int
    dropped: dict[str, int] = Field(default_factory=dict)
    failed_chunk_ids: list[str] = Field(default_factory=list)
    sensitivity: dict[str, int] = Field(default_factory=dict)
    stale_chunks_deleted: int = 0
    lint_warnings: list[str] = Field(default_factory=list)


def _normalize(text: str) -> str:
    return " ".join(text.casefold().split())


class KnowledgeGraphIngestor:
    def __init__(
        self,
        *,
        llm: BaseChatModel,
        chunk_store: ChunkStore,
        graph_writer: GraphWriter,
        detector: SensitiveDataDetector,
        settings: Settings,
        glossary: Mapping[str, str] | None = None,
        callbacks: list | None = None,
    ) -> None:
        self._llm = llm
        self._chunks = chunk_store
        self._graph = graph_writer
        self._detector = detector
        self._settings = settings
        self._glossary = dict(glossary or {})
        self._allowed_relations = set(settings.allowed_relations or [])
        self._config: RunnableConfig = {"callbacks": callbacks or [], "tags": ["ingestion"]}
        relation_rule = (
            f"\n- Use only these predicates: {', '.join(sorted(self._allowed_relations))}."
            if self._allowed_relations
            else ""
        )
        self._system_prompt = EXTRACTION_SYSTEM_PROMPT.format(
            entity_types=", ".join(t.value for t in EntityType), relation_rule=relation_rule
        )

    def ingest(self, text: str, metadata: DocumentMetadata) -> IngestionReport:
        with traced_span("ingest.document", {"document.source_id": metadata.source_id,
                                             "document.doc_type": metadata.doc_type}) as span:
            warnings = lint_document(text)
            text, tables = flatten_markdown_tables(text)
            if tables:
                warnings.append(f"{tables} table(s) flattened to bullets; prefer prose/lists at the source")

            chunks = self._classify(
                split_document(text, metadata, chunk_size=self._settings.chunk_size,
                               chunk_overlap=self._settings.chunk_overlap)
            )
            self._chunks.upsert(chunks, [c.embedding_text(glossary_notes(c.text, self._glossary)) for c in chunks])

            grounded, extracted, dropped, failed = self._extract_all(chunks)
            written = self._graph.replace_source(metadata.source_id, grounded)
            stale = self._chunks.delete_source(metadata.source_id, keep={c.chunk_id for c in chunks})

            report = IngestionReport(
                source_id=metadata.source_id,
                chunk_count=len(chunks),
                triples_extracted=extracted,
                triples_written=written,
                dropped=dict(dropped),
                failed_chunk_ids=failed,
                sensitivity=dict(Counter(c.sensitivity.value for c in chunks)),
                stale_chunks_deleted=stale,
                lint_warnings=warnings,
            )
            span.set_attributes({"ingest.chunks": len(chunks), "ingest.triples_written": written,
                                 "ingest.failed_chunks": len(failed)})
            return report

    def _classify(self, chunks: list[ChunkRecord]) -> list[ChunkRecord]:
        classified: list[ChunkRecord] = []
        for chunk in chunks:
            detections = self._detector.detect(chunk.text)
            level = classify(detections, chunk.sensitivity)
            text = chunk.text
            if detections and self._settings.sensitive_data_policy == "redact":
                text = redact(text, detections)
                level = chunk.sensitivity  # residual risk handled by the detector's recall
            classified.append(chunk.model_copy(update={
                "text": text,
                "sensitivity": level,
                "chunk_id": ChunkRecord.make_id(chunk.source_id, chunk.ordinal, text),
            }))
        return classified

    def _extract_all(self, chunks: list[ChunkRecord]):
        dropped: Counter[str] = Counter()
        failed: list[str] = []
        grounded: list[GroundedTriple] = []
        extracted = 0
        with ThreadPoolExecutor(max_workers=self._settings.extraction_concurrency) as pool:
            # Each task runs in its own context copy so OTEL spans parent correctly.
            futures = [(c, pool.submit(contextvars.copy_context().run, self._extract, c)) for c in chunks]
            for chunk, future in futures:
                try:
                    result = future.result()
                except StructuredOutputError:
                    logger.warning("extraction failed validation for chunk %s", chunk.chunk_id)
                    failed.append(chunk.chunk_id)
                    continue
                except Exception:  # vLLM unreachable after client retries, etc.
                    logger.exception("extraction failed for chunk %s", chunk.chunk_id)
                    failed.append(chunk.chunk_id)
                    continue
                extracted += len(result.triples)
                haystack = _normalize(chunk.text)
                for triple in result.triples:
                    if self._settings.require_grounded_evidence and _normalize(triple.evidence) not in haystack:
                        dropped["evidence_not_in_chunk"] += 1
                        continue
                    if self._allowed_relations and triple.relation not in self._allowed_relations:
                        dropped["relation_outside_ontology"] += 1
                        continue
                    if triple.head.key == triple.tail.key:
                        dropped["self_loop"] += 1
                        continue
                    grounded.append(GroundedTriple(triple=triple, chunk_id=chunk.chunk_id,
                                                   source_id=chunk.source_id, sensitivity=chunk.sensitivity))
        return grounded, extracted, dropped, failed

    def _extract(self, chunk: ChunkRecord) -> ExtractionResult:
        context = " > ".join([p for p in [chunk.title, *chunk.section_path] if p]) or "(none)"
        with traced_span("ingest.extract_triples", {"chunk.id": chunk.chunk_id}):
            return invoke_structured(
                self._llm,
                ExtractionResult,
                [
                    SystemMessage(content=self._system_prompt),
                    HumanMessage(content=f"Document section: {context}\n\nPassage:\n{chunk.text}"),
                ],
                max_attempts=self._settings.extraction_attempts,
                config=self._config,
            )

