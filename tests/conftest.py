from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from nexo.config import Settings
from nexo.llm import build_embeddings
from nexo.storage.graph_store import ReadResult
from nexo.storage.schemas import ChunkRecord, Sensitivity
from nexo.storage.vector_store import LocalChunkStore

_EXPORTER = InMemorySpanExporter()
_provider = TracerProvider()
_provider.add_span_processor(SimpleSpanProcessor(_EXPORTER))
trace.set_tracer_provider(_provider)


@pytest.fixture
def spans() -> InMemorySpanExporter:
    _EXPORTER.clear()
    return _EXPORTER


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        embedding_provider="fake",
        embedding_dimensions=16,
        vector_store_path=tmp_path / "vectors.json",
        checkpoint_backend="memory",
        checkpoint_sqlite_path=tmp_path / "checkpoints.sqlite",
        extraction_concurrency=1,
        chunk_size=400,
        chunk_overlap=0,
        seed_chunks=2,
    )


def make_chunk(source_id: str, ordinal: int, text: str, sensitivity: Sensitivity = Sensitivity.INTERNAL,
               **extra: Any) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=ChunkRecord.make_id(source_id, ordinal, text),
        source_id=source_id,
        ordinal=ordinal,
        text=text,
        sensitivity=sensitivity,
        ingested_at=datetime.now(UTC),
        **extra,
    )


@pytest.fixture
def chunk_store(settings) -> LocalChunkStore:
    return LocalChunkStore(build_embeddings(settings), settings.vector_store_path)


class FakeGraph:
    """Stands in for GraphStore.run_read_query; records the Cypher it receives."""

    def __init__(self, rows: list[dict[str, Any]] | None = None, error: Exception | None = None) -> None:
        self.rows = rows or []
        self.error = error
        self.queries: list[str] = []

    def run_read_query(self, cypher: str, parameters: dict[str, Any] | None = None) -> ReadResult:
        self.queries.append(cypher)
        if self.error:
            raise self.error
        return ReadResult(rows=self.rows, truncated=False)
