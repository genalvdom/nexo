"""Module A - document ingestion: chunks -> vectors, triples -> Neo4j.

Pipeline for one document:

1. Lint + flatten tables, heading-aware chunking (`chunking.py`).
2. Sensitivity classification per chunk (declared floor + PII/PHI detector),
   optional redaction before anything is embedded or extracted.
3. Upsert chunks into the vector store under deterministic `chunk_id`s.
4. LLM triple extraction per chunk (bounded concurrency - vLLM's continuous
   batching turns parallel requests into throughput), Pydantic-validated.
   The tail of the previous chunk is shown as context so cross-chunk
   references resolve; evidence must still come from the chunk itself.
5. Drop triples whose evidence quote is not in the chunk (hallucination
   guard); map predicates onto the ontology (synonyms, inverses, type
   constraints, RELATED_TO fallback).
6. Resolve entities against each other and the existing graph.
7. Replace the document's lexical + domain subgraph in one transaction.
8. Delete superseded vector chunks.

Steps 3 -> 7 -> 8 keep the invariant that every `chunk_id` in Neo4j resolves
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
from nexo.storage.ontology import FALLBACK_RELATION, Ontology
from nexo.storage.resolution import EntityResolver
from nexo.storage.schemas import (
    ChunkRecord,
    DocumentMetadata,
    EntityType,
    ExtractionResult,
    GroundedTriple,
    ResolvedEntity,
    Triple,
)
from nexo.storage.sensitive_data import SensitiveDataDetector, classify, redact
from nexo.storage.vector_store import ChunkStore
from nexo.telemetry import traced_span

logger = logging.getLogger(__name__)

EXTRACTION_SYSTEM_PROMPT = """\
You extract a knowledge graph from one passage of a document.

Return entity-relation-entity triples as JSON matching the schema.
- Entity types: {entity_types}. Pick the most specific type; skip entities that fit none.
- Use the most complete name for each entity ("Acme Holdings Inc.", not "the company" or "Acme"),
  including names introduced in the preceding text; resolve pronouns.
- aliases: other names the passage itself uses for the same entity (acronyms, short or former names).
- Predicates are short, specific, directional verbs in UPPER_SNAKE_CASE, oriented head -> tail.
  Avoid vague predicates like RELATED_TO.{relation_rule}
- Only facts the passage states. The preceding text is context only: never extract facts from it.
- No separate entities for dates, amounts or quantities: put a date the fact holds in valid_at.
- evidence: a verbatim quote (max ~200 characters) from the passage that states the fact.
- certainty: "asserted", "possible" (hedged: may, suspected) or "negated" (ruled out, denied).
- proposed_codes: only codes printed in the passage (ICD-10-CM, RxNorm, SNOMED CT, MeSH, UMLS).
- Return {{"triples": []}} if the passage states no relationships.
"""


class GraphWriter(Protocol):
    def replace_source(self, document: DocumentMetadata, chunks: Sequence[ChunkRecord],
                       triples: Sequence[GroundedTriple]) -> int: ...


class IngestionReport(BaseModel):
    source_id: str
    chunk_count: int
    triples_extracted: int
    triples_written: int
    dropped: dict[str, int] = Field(default_factory=dict)
    relations: dict[str, int] = Field(default_factory=dict, description="canonical, remapped, fallback")
    resolution: dict[str, int] = Field(default_factory=dict, description="mentions per resolution method")
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
        ontology: Ontology | None = None,
        resolver: EntityResolver | None = None,
        callbacks: list | None = None,
    ) -> None:
        self._llm = llm
        self._chunks = chunk_store
        self._graph = graph_writer
        self._detector = detector
        self._settings = settings
        self._glossary = dict(glossary or {})
        self._ontology = ontology
        self._resolver = resolver or EntityResolver(catalog=None, llm=None, mode="deterministic")
        self._config: RunnableConfig = {"callbacks": callbacks or [], "tags": ["ingestion"]}
        relation_rule = (
            "\n- Prefer these relations (direction and types as shown); use another predicate only if none "
            f"fits:\n{ontology.prompt_block()}" if ontology else ""
        )
        self._system_prompt = EXTRACTION_SYSTEM_PROMPT.format(
            entity_types=", ".join(t.value for t in EntityType), relation_rule=relation_rule
        )

    # --- public API ---------------------------------------------------------------
    def ingest(self, text: str, metadata: DocumentMetadata) -> IngestionReport:
        with traced_span("ingest.document", {"document.source_id": metadata.source_id,
                                             "document.doc_type": metadata.doc_type}) as span:
            chunks, warnings = self._prepare(text, metadata)
            self._chunks.upsert(chunks, [c.embedding_text(glossary_notes(c.text, self._glossary)) for c in chunks])

            report = IngestionReport(source_id=metadata.source_id, chunk_count=len(chunks), triples_extracted=0,
                                     triples_written=0, lint_warnings=warnings,
                                     sensitivity=dict(Counter(c.sensitivity.value for c in chunks)))
            grounded = self._triples(chunks, report, resolve=True)
            report.triples_written = self._graph.replace_source(metadata, chunks, grounded)
            report.stale_chunks_deleted = self._chunks.delete_source(
                metadata.source_id, keep={c.chunk_id for c in chunks})
            span.set_attributes({"ingest.chunks": len(chunks), "ingest.triples_written": report.triples_written,
                                 "ingest.failed_chunks": len(report.failed_chunk_ids)})
            return report

    def extract_triples(self, text: str, metadata: DocumentMetadata) -> tuple[list[GroundedTriple], IngestionReport]:
        """Extraction only (no writes, no graph resolution) - for evaluation against gold triples."""
        chunks, warnings = self._prepare(text, metadata)
        report = IngestionReport(source_id=metadata.source_id, chunk_count=len(chunks), triples_extracted=0,
                                 triples_written=0, lint_warnings=warnings)
        return self._triples(chunks, report, resolve=False), report

    # --- stages ------------------------------------------------------------------------
    def _prepare(self, text: str, metadata: DocumentMetadata) -> tuple[list[ChunkRecord], list[str]]:
        warnings = lint_document(text)
        text, tables = flatten_markdown_tables(text)
        if tables:
            warnings.append(f"{tables} table(s) flattened to bullets; prefer prose/lists at the source")
        chunks = split_document(text, metadata, chunk_size=self._settings.chunk_size,
                                chunk_overlap=self._settings.chunk_overlap)
        return self._classify(chunks), warnings

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

    def _triples(self, chunks: list[ChunkRecord], report: IngestionReport, *, resolve: bool) -> list[GroundedTriple]:
        dropped: Counter[str] = Counter()
        relation_stats: Counter[str] = Counter()
        kept: list[tuple[ChunkRecord, Triple, str, bool, str | None]] = []
        for chunk, result in self._extract_all(chunks, report):
            report.triples_extracted += len(result.triples)
            haystack = _normalize(chunk.text)
            for triple in result.triples:
                if self._settings.require_grounded_evidence and _normalize(triple.evidence) not in haystack:
                    dropped["evidence_not_in_chunk"] += 1
                    continue
                if triple.head.key == triple.tail.key:
                    dropped["self_loop"] += 1
                    continue
                relation, swap, original = triple.relation, False, None
                if self._ontology is not None:
                    mapping = self._ontology.map(triple.relation, triple.head.type, triple.tail.type)
                    relation, swap, original = mapping.relation, mapping.swap, mapping.original
                    relation_stats["fallback" if relation == FALLBACK_RELATION
                                   else "remapped" if original else "canonical"] += 1
                kept.append((chunk, triple, relation, swap, original))

        refs = [ref for _, t, *_ in kept for ref in (t.head, t.tail)]
        resolved = self._resolver.resolve(refs) if resolve else {}

        def place(ref) -> ResolvedEntity:
            entry = resolved.get(ref.key) or ResolvedEntity(key=ref.key, surface=ref.name)
            return entry.model_copy(update={"surface": ref.name, "ref": ref})

        grounded: list[GroundedTriple] = []
        for chunk, triple, relation, swap, original in kept:
            head, tail = place(triple.head), place(triple.tail)
            if swap:
                head, tail = tail, head
            if head.key == tail.key:  # two names for one entity, now merged
                dropped["self_loop_after_resolution"] += 1
                continue
            grounded.append(GroundedTriple(triple=triple, chunk_id=chunk.chunk_id, source_id=chunk.source_id,
                                           sensitivity=chunk.sensitivity, relation=relation,
                                           original_relation=original, head=head, tail=tail))
        report.dropped = dict(dropped)
        report.relations = dict(relation_stats)
        report.resolution = dict(Counter(e.method.value for e in resolved.values()))
        return grounded

    def _extract_all(self, chunks: list[ChunkRecord], report: IngestionReport):
        with ThreadPoolExecutor(max_workers=self._settings.extraction_concurrency) as pool:
            # Each task runs in its own context copy so OTEL spans parent correctly.
            futures = [
                (c, pool.submit(contextvars.copy_context().run, self._extract, c, chunks[i - 1] if i else None))
                for i, c in enumerate(chunks)
            ]
            for chunk, future in futures:
                try:
                    yield chunk, future.result()
                except StructuredOutputError:
                    logger.warning("extraction failed validation for chunk %s", chunk.chunk_id)
                    report.failed_chunk_ids.append(chunk.chunk_id)
                except Exception:  # vLLM unreachable after client retries, etc.
                    logger.exception("extraction failed for chunk %s", chunk.chunk_id)
                    report.failed_chunk_ids.append(chunk.chunk_id)

    def _extract(self, chunk: ChunkRecord, previous: ChunkRecord | None) -> ExtractionResult:
        section = " > ".join([p for p in [chunk.title, *chunk.section_path] if p]) or "(none)"
        parts = [f"Document section: {section}"]
        limit = self._settings.extraction_context_chars
        if previous is not None and limit:
            parts.append(f"Preceding text (context only):\n...{previous.text[-limit:]}")
        parts.append(f"Passage:\n{chunk.text}")
        with traced_span("ingest.extract_triples", {"chunk.id": chunk.chunk_id}):
            return invoke_structured(
                self._llm,
                ExtractionResult,
                [SystemMessage(content=self._system_prompt), HumanMessage(content="\n\n".join(parts))],
                max_attempts=self._settings.extraction_attempts,
                config=self._config,
            )
