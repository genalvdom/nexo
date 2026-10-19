from __future__ import annotations

import json

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from graphrag_stack.storage.ingest import KnowledgeGraphIngestor
from graphrag_stack.storage.schemas import DocumentMetadata, Sensitivity
from graphrag_stack.storage.sensitive_data import RegexDetector
from graphrag_stack.storage.vector_store import ChunkFilter

DOC = "# Deals\n\nAcme Holdings acquired Beta Labs in 2024. Contact: cfo@acme.example."


class RecordingGraphWriter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list]] = []

    def replace_source(self, source_id, triples):
        self.calls.append((source_id, list(triples)))
        return len(triples)


def _triple(evidence: str, relation: str = "acquired") -> dict:
    return {
        "head": {"name": "Acme Holdings", "type": "Organization"},
        "relation": relation,
        "tail": {"name": "Beta Labs", "type": "Organization"},
        "evidence": evidence,
        "valid_at": "2024-01-01",
    }


def _ingestor(settings, chunk_store, replies, writer):
    llm = GenericFakeChatModel(messages=iter([AIMessage(content=r) for r in replies]))
    return KnowledgeGraphIngestor(llm=llm, chunk_store=chunk_store, graph_writer=writer,
                                  detector=RegexDetector(), settings=settings)


def test_ingest_validates_grounds_and_links_chunks(settings, chunk_store):
    writer = RecordingGraphWriter()
    replies = [
        json.dumps({"triples": [], "confidence": 1}),  # schema violation -> fed back, retried
        json.dumps({"triples": [_triple("Acme Holdings acquired  Beta Labs"),  # whitespace-tolerant match
                                _triple("Acme bought Beta for $1B", "valued")]}),  # not in text -> dropped
    ]
    report = _ingestor(settings, chunk_store, replies, writer).ingest(
        DOC, DocumentMetadata(source_id="deals", title="Deals memo"))

    assert report.failed_chunk_ids == []
    assert report.triples_extracted == 2 and report.triples_written == 1
    assert report.dropped == {"evidence_not_in_chunk": 1}
    assert report.sensitivity == {"pii": 1}  # email detected, floor was internal
    [(source_id, triples)] = writer.calls
    assert source_id == "deals"
    # The graph/vector contract: every chunk_id written to Neo4j resolves in the vector store.
    [stored] = chunk_store.get_by_ids([triples[0].chunk_id])
    assert stored.sensitivity is Sensitivity.PII and "Acme Holdings acquired" in stored.text


def test_ingest_reports_failed_chunks_without_aborting(settings, chunk_store):
    writer = RecordingGraphWriter()
    report = _ingestor(settings, chunk_store, ["not json"] * 3, writer).ingest(
        DOC, DocumentMetadata(source_id="deals"))
    assert len(report.failed_chunk_ids) == 1 and report.triples_written == 0
    assert chunk_store.get_by_ids(report.failed_chunk_ids)  # chunk kept for re-extraction


def test_reingest_replaces_stale_chunks(settings, chunk_store):
    writer = RecordingGraphWriter()
    empty = json.dumps({"triples": []})
    first = _ingestor(settings, chunk_store, [empty], writer).ingest(DOC, DocumentMetadata(source_id="deals"))
    second = _ingestor(settings, chunk_store, [empty], writer).ingest(
        DOC.replace("2024", "2025"), DocumentMetadata(source_id="deals"))
    assert second.stale_chunks_deleted == 1
    assert first.chunk_count == second.chunk_count == 1


def test_redact_policy_removes_detected_values(settings, chunk_store):
    settings.sensitive_data_policy = "redact"
    writer = RecordingGraphWriter()
    _ingestor(settings, chunk_store, [json.dumps({"triples": []})], writer).ingest(
        DOC, DocumentMetadata(source_id="deals"))
    [chunk] = chunk_store.search("Acme", 1, ChunkFilter())
    assert "cfo@acme.example" not in chunk.text and "[EMAIL]" in chunk.text
