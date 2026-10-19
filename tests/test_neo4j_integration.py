"""Runs the real Cypher against Neo4j. Skipped unless NEO4J_TEST_URI is set, e.g.

    podman run -d -p 127.0.0.1:7688:7687 -e NEO4J_AUTH=neo4j/graphrag-test-pass neo4j:5.26-community
    NEO4J_TEST_URI=bolt://127.0.0.1:7688 NEO4J_TEST_PASSWORD=graphrag-test-pass pytest tests/test_neo4j_integration.py
"""

from __future__ import annotations

import json
import os

import pytest
from neo4j import GraphDatabase
from neo4j.exceptions import ClientError

from graphrag_stack.agents.models import InvestigationScope
from graphrag_stack.agents.tools import InvestigationContext, build_investigation_tools
from graphrag_stack.storage.graph_store import GraphStore
from graphrag_stack.storage.schemas import EntityRef, GroundedTriple, Sensitivity, Triple
from graphrag_stack.storage.vector_store import ChunkFilter

URI = os.environ.get("NEO4J_TEST_URI")
pytestmark = pytest.mark.skipif(not URI, reason="NEO4J_TEST_URI not set")

C1, C2, C3 = ("chk_" + c * 16 for c in "123")


def _triple(head, rel, tail, evidence, head_type="Organization", tail_type="Organization"):
    return Triple(head=EntityRef(name=head, type=head_type), relation=rel,
                  tail=EntityRef(name=tail, type=tail_type), evidence=evidence)


@pytest.fixture
def store():
    driver = GraphDatabase.driver(URI, auth=("neo4j", os.environ["NEO4J_TEST_PASSWORD"]))
    driver.execute_query("MATCH (n) DETACH DELETE n")
    graph = GraphStore(driver, database="neo4j", query_timeout_s=10, max_rows=50)
    graph.ensure_schema()
    yield graph
    graph.close()


def test_replace_source_merges_provenance_and_cleans_up(store):
    doc_a = [GroundedTriple(triple=_triple("Acme", "acquired", "Beta Labs", "Acme acquired Beta Labs"),
                            chunk_id=C1, source_id="a", sensitivity=Sensitivity.INTERNAL),
             GroundedTriple(triple=_triple("Beta Labs", "treats", "Jane Roe", "Beta Labs treats Jane Roe",
                                           tail_type="Person"),
                            chunk_id=C2, source_id="a", sensitivity=Sensitivity.PHI)]
    doc_b = [GroundedTriple(triple=_triple("acme", "ACQUIRED", "beta labs", "acme acquired beta labs"),
                            chunk_id=C3, source_id="b", sensitivity=Sensitivity.INTERNAL)]
    assert store.replace_source("a", doc_a) == 2
    store.replace_source("b", doc_b)

    acme = store.run_read_query(
        "MATCH (e:Entity:Organization {key: 'Organization:acme'}) RETURN e.chunk_id AS first, e.chunk_ids AS ids"
    ).rows
    assert acme == [{"first": C1, "ids": [C1, C3]}]  # resolved across documents, provenance merged
    edge = store.run_read_query("MATCH (:Entity)-[r:ACQUIRED]->(:Entity) RETURN r.chunk_ids AS ids").rows
    assert edge == [{"ids": [C1, C3]}]
    labels = store.run_read_query("MATCH (e:Entity {name: 'Jane Roe'}) RETURN labels(e) AS l").rows[0]["l"]
    assert {"Entity", "Person", "PII", "PHI"} <= set(labels)
    hops = store.run_read_query(
        "MATCH p = (a:Entity {name: 'Acme'})-[*..2]->(b:Entity {name: 'Jane Roe'}) RETURN length(p) AS n").rows
    assert hops == [{"n": 2}]

    store.replace_source("a", [])  # document a withdrawn
    remaining = store.run_read_query("MATCH (e:Entity) RETURN e.name AS name, e.chunk_id AS first ORDER BY name").rows
    assert remaining == [{"name": "Acme", "first": C3}, {"name": "Beta Labs", "first": C3}]
    assert store.run_read_query("MATCH (c:Chunk) RETURN collect(c.chunk_id) AS ids").rows == [{"ids": [C3]}]


def test_read_transaction_rejects_writes_server_side(store):
    with pytest.raises(ClientError):
        store.run_read_query("CREATE (:Entity {key: 'x'})")  # guard bypassed: the server still refuses


def test_row_cap_and_tool_against_real_graph(store, settings):
    store.replace_source("a", [GroundedTriple(triple=_triple(f"Org{i}", "partners_with", "Hub", f"Org{i} partners"),
                                              chunk_id=C1, source_id="a", sensitivity=Sensitivity.INTERNAL)
                               for i in range(60)])
    assert store.run_read_query("MATCH (e:Entity) RETURN e.name").truncated is True
    ctx = InvestigationContext(request_id="r", max_tool_calls=5,
                               scope=InvestigationScope(chunk_filter=ChunkFilter(max_sensitivity=Sensitivity.PUBLIC)))
    query, _ = build_investigation_tools(graph=store, chunks=None, ctx=ctx, settings=settings)
    out = json.loads(query("MATCH (e:Entity {name: 'Hub'}) RETURN e"))
    assert out["rows"] == [{"e": {"redacted": "above caller clearance"}}]  # internal > public
    assert "PARTNERS_WITH" in store.describe_schema()


def _last_tool_payload(request: dict) -> dict:
    content = request["messages"][-1]["content"]
    return json.loads(content[0]["text"] if isinstance(content, list) else content)


def test_end_to_end_ingest_investigate_approve(store, settings, chunk_store):
    """Module A -> Neo4j/vector store -> Module C graph -> Module B Strands loop -> human approval."""
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from strands.models.openai import OpenAIModel

    from graphrag_stack.agents.investigator import Investigator
    from graphrag_stack.orchestration.graph import GraphDependencies, build_graph
    from graphrag_stack.service import Runtime
    from graphrag_stack.storage.ingest import KnowledgeGraphIngestor
    from graphrag_stack.storage.schemas import DocumentMetadata
    from graphrag_stack.storage.sensitive_data import RegexDetector
    from tests.test_agent import ScriptedClient, _completion, _tool_call

    doc = "# Deals\n\nAcme Holdings acquired Beta Labs in 2024. Beta Labs supplies Gamma Clinics."
    extraction = {"triples": [
        {"head": {"name": "Acme Holdings", "type": "Organization"}, "relation": "acquired",
         "tail": {"name": "Beta Labs", "type": "Organization"}, "evidence": "Acme Holdings acquired Beta Labs"},
        {"head": {"name": "Beta Labs", "type": "Organization"}, "relation": "supplies",
         "tail": {"name": "Gamma Clinics", "type": "Organization"}, "evidence": "Beta Labs supplies Gamma Clinics"},
    ]}
    ingestor = KnowledgeGraphIngestor(
        llm=GenericFakeChatModel(messages=iter([AIMessage(content=json.dumps(extraction))])),
        chunk_store=chunk_store, graph_writer=store, detector=RegexDetector(), settings=settings)
    report = ingestor.ingest(doc, DocumentMetadata(source_id="deals", title="Deals"))
    assert report.triples_written == 2
    [chunk_id] = store.run_read_query("MATCH (c:Chunk) RETURN c.chunk_id AS id").rows[0].values()

    cypher = ("MATCH p = (a:Entity {name: 'Acme Holdings'})-[*..3]->(c:Entity {name: 'Gamma Clinics'}) "
              "RETURN [n IN nodes(p) | n.name] AS path, [r IN relationships(p) | r.chunk_id] AS chunk_ids")
    client = ScriptedClient([
        _tool_call("t1", "query_knowledge_graph", {"cypher_query": cypher}),
        _tool_call("t2", "fetch_vector_chunks", {"chunk_ids": [chunk_id]}),
        _completion({"content": f"Acme owns Beta Labs, which supplies Gamma Clinics [chunk:{chunk_id}]."}, "stop"),
    ])
    investigator = Investigator(model=OpenAIModel(client=client, model_id="m", stream=False), graph=store,
                                chunks=chunk_store, settings=settings, schema_text=store.describe_schema())
    deps = GraphDependencies(settings=settings, investigator=investigator, detector=RegexDetector())
    rt = Runtime(graph=build_graph(deps, InMemorySaver()), settings=settings)

    paused = rt.start("How is Acme Holdings connected to Gamma Clinics?", thread_id="e2e")
    assert paused.status == "awaiting_review"
    assert paused.pending_review["citations"] == [chunk_id]
    assert paused.pending_review["compliance_report"]["blocking"] is False
    assert _last_tool_payload(client.requests[1])["rows"][0]["path"] == ["Acme Holdings", "Beta Labs", "Gamma Clinics"]

    done = rt.review("e2e", {"approval_status": "approved", "reviewer": "analyst"})
    assert done.final_response.startswith("Acme owns Beta Labs")
