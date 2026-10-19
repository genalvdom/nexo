"""Vector chunk store, cross-referenced from Neo4j by `chunk_id`.

`ChunkStore` is the contract the rest of the stack depends on: exact
get-by-id (the graph -> text hop), filtered similarity search (seeding), and
delete-by-document (re-ingestion). `LocalChunkStore` wraps LangChain's
`InMemoryVectorStore` with atomic JSON persistence for single-node use.

For production, the AWS vector-database guidance points to Aurora/RDS
PostgreSQL + pgvector for this access pattern (primary-key lookup, SQL
metadata filters, ACID writes so a chunk is readable as soon as Neo4j
references it), or OpenSearch Service when hybrid lexical+vector search or
very high query rates matter. Implement `ChunkStore` against either.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Protocol

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import InMemoryVectorStore
from pydantic import BaseModel, ConfigDict

from nexo.storage.schemas import ChunkRecord, Sensitivity
from nexo.telemetry import traced_span

DATA_SOURCE_ID = "nexo-chunks"


class ChunkFilter(BaseModel):
    """Metadata pre-filter applied before similarity ranking and on fetch."""

    model_config = ConfigDict(extra="forbid")

    doc_types: list[str] | None = None
    source_ids: list[str] | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    max_sensitivity: Sensitivity = Sensitivity.INTERNAL

    def allows(self, chunk: ChunkRecord) -> bool:
        if chunk.sensitivity.rank > self.max_sensitivity.rank:
            return False
        if self.doc_types and chunk.doc_type not in self.doc_types:
            return False
        if self.source_ids and chunk.source_id not in self.source_ids:
            return False
        if self.effective_from or self.effective_to:
            if chunk.effective_date is None:
                return False
            if self.effective_from and chunk.effective_date < self.effective_from:
                return False
            if self.effective_to and chunk.effective_date > self.effective_to:
                return False
        return True


class ChunkStore(Protocol):
    def upsert(self, chunks: Sequence[ChunkRecord], embedding_texts: Sequence[str]) -> None: ...
    def get_by_ids(self, chunk_ids: Sequence[str]) -> list[ChunkRecord]: ...
    def search(self, query: str, k: int, chunk_filter: ChunkFilter) -> list[ChunkRecord]: ...
    def delete_source(self, source_id: str, keep: set[str] | frozenset[str] = frozenset()) -> int: ...


class LocalChunkStore:
    """In-process vector index persisted to a JSON file (atomic replace)."""

    def __init__(self, embeddings: Embeddings, path: Path | None = None) -> None:
        self._embeddings = embeddings
        self._path = path
        self._lock = threading.RLock()
        if path is not None and path.exists():
            self._store = InMemoryVectorStore.load(str(path), embeddings)
        else:
            self._store = InMemoryVectorStore(embeddings)

    def upsert(self, chunks: Sequence[ChunkRecord], embedding_texts: Sequence[str]) -> None:
        if len(chunks) != len(embedding_texts):
            raise ValueError("chunks and embedding_texts must align")
        if not chunks:
            return
        documents = [
            # The embedded text carries headers/glossary; the record keeps the
            # exact chunk text for evidence checks and display.
            Document(id=c.chunk_id, page_content=t, metadata={"record": c.model_dump(mode="json")})
            for c, t in zip(chunks, embedding_texts, strict=True)
        ]
        with self._lock:
            self._store.add_documents(documents, ids=[c.chunk_id for c in chunks])
            self._persist()

    def get_by_ids(self, chunk_ids: Sequence[str]) -> list[ChunkRecord]:
        with traced_span("chunk_store get_by_ids", {"nexo.chunks.requested": len(chunk_ids)}) as span, self._lock:
            documents = self._store.get_by_ids(list(chunk_ids))
            span.set_attribute("nexo.chunks.found", len(documents))
        by_id = {d.id: ChunkRecord.model_validate(d.metadata["record"]) for d in documents}
        return [by_id[i] for i in chunk_ids if i in by_id]

    def search(self, query: str, k: int, chunk_filter: ChunkFilter) -> list[ChunkRecord]:
        def _allowed(document: Document) -> bool:
            return chunk_filter.allows(ChunkRecord.model_validate(document.metadata["record"]))

        # GenAI `retrieval` operation; INTERNAL because this store is in-process
        # (a pgvector/OpenSearch backend would be a CLIENT span).
        attributes = {"gen_ai.operation.name": "retrieval", "gen_ai.data_source.id": DATA_SOURCE_ID,
                      "gen_ai.retrieval.top_k": k}
        with traced_span(f"retrieval {DATA_SOURCE_ID}", attributes) as span, self._lock:
            documents = self._store.similarity_search(query, k=k, filter=_allowed)
            span.set_attribute("nexo.chunks.found", len(documents))
        return [ChunkRecord.model_validate(d.metadata["record"]) for d in documents]

    def delete_source(self, source_id: str, keep: set[str] | frozenset[str] = frozenset()) -> int:
        """Delete a document's chunks except `keep` (the current version's ids)."""
        with self._lock:
            stale = [
                doc_id
                for doc_id, entry in self._store.store.items()
                if entry["metadata"]["record"]["source_id"] == source_id and doc_id not in keep
            ]
            if stale:
                self._store.delete(stale)
                self._persist()
        return len(stale)

    def _persist(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        self._store.dump(str(tmp))
        os.replace(tmp, self._path)  # readers never see a half-written index
