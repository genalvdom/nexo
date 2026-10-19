"""Neo4j access over the Bolt driver.

Data model (every node and edge carries the chunk(s) it came from):

    (:Entity:<EntityType> {key, name, type, description, chunk_id, chunk_ids,
                           source_ids, max_sensitivity_rank, proposed_codes_json})
    (:Chunk {chunk_id, source_id, sensitivity})
    (:Entity)-[:<PREDICATE> {chunk_id, chunk_ids, evidence, certainty, valid_at}]->(:Entity)
    (:Entity)-[:MENTIONED_IN]->(:Chunk)

`chunk_id` is the chunk where the entity/edge was first extracted and
`chunk_ids` accumulates every supporting chunk across documents.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, LiteralString, cast

from neo4j import READ_ACCESS, WRITE_ACCESS, Driver, GraphDatabase, ManagedTransaction, unit_of_work
from neo4j.exceptions import ServiceUnavailable, SessionExpired
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from graphrag_stack.config import Settings
from graphrag_stack.storage.schemas import RELATION_RE, EntityType, GroundedTriple

DATA_MODEL = """\
(:Entity:<EntityType>[:PII][:PHI] {key, name, type, description, chunk_id, chunk_ids, source_ids,
                                  max_sensitivity_rank, proposed_codes_json})
(:Chunk {chunk_id, source_id, sensitivity})
(:Entity)-[:<PREDICATE> {chunk_id, chunk_ids, evidence, certainty, valid_at}]->(:Entity)
(:Entity)-[:MENTIONED_IN]->(:Chunk)
EntityType is one of: """ + ", ".join(t.value for t in EntityType) + """
max_sensitivity_rank: 0=public 1=internal 2=pii 3=phi"""

# Connection drops surface as ServiceUnavailable/SessionExpired. Transient
# server errors inside managed transactions are already retried by the driver.
_connection_retry = retry(
    retry=retry_if_exception_type((ServiceUnavailable, SessionExpired)),
    wait=wait_exponential_jitter(multiplier=0.5, max=8),
    stop=stop_after_attempt(4),
    reraise=True,
)

_SCHEMA_STATEMENTS: tuple[LiteralString, ...] = (
    "CREATE CONSTRAINT entity_key IF NOT EXISTS FOR (e:Entity) REQUIRE e.key IS UNIQUE",
    "CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (c:Chunk) REQUIRE c.chunk_id IS UNIQUE",
    "CREATE INDEX entity_chunk_id IF NOT EXISTS FOR (e:Entity) ON (e.chunk_id)",
    "CREATE INDEX entity_name IF NOT EXISTS FOR (e:Entity) ON (e.name)",
)


@dataclass(frozen=True)
class ReadResult:
    rows: list[dict[str, Any]]
    truncated: bool


class GraphStore:
    def __init__(self, driver: Driver, *, database: str, query_timeout_s: float, max_rows: int) -> None:
        self._driver = driver
        self._database = database
        self._query_timeout_s = query_timeout_s
        self._max_rows = max_rows

    @classmethod
    def from_settings(cls, settings: Settings, *, read_only: bool) -> GraphStore:
        user, password = settings.neo4j_user, settings.neo4j_password
        if read_only and settings.neo4j_read_user and settings.neo4j_read_password:
            user, password = settings.neo4j_read_user, settings.neo4j_read_password
        driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(user, password.get_secret_value()),
            connection_timeout=10,
            max_transaction_retry_time=30,
        )
        return cls(
            driver,
            database=settings.neo4j_database,
            query_timeout_s=settings.neo4j_query_timeout_s,
            max_rows=settings.neo4j_max_rows,
        )

    def close(self) -> None:
        self._driver.close()

    @_connection_retry
    def verify(self) -> None:
        self._driver.verify_connectivity()

    @_connection_retry
    def ensure_schema(self) -> None:
        with self._driver.session(database=self._database, default_access_mode=WRITE_ACCESS) as session:
            for statement in _SCHEMA_STATEMENTS:
                session.run(statement).consume()

    # --- writes (ingestion) ------------------------------------------------------
    @_connection_retry
    def replace_source(self, source_id: str, triples: Sequence[GroundedTriple]) -> int:
        """Swap a document's subgraph atomically: detach the previous version's
        provenance (dropping what only it supported), then upsert the new triples."""
        entities, chunks, mentions, relations = _plan_writes(triples)

        def work(tx: ManagedTransaction) -> None:
            _delete_source(tx, source_id)
            if triples:
                _write_batch(tx, entities, chunks, mentions, relations)

        with self._driver.session(database=self._database, default_access_mode=WRITE_ACCESS) as session:
            session.execute_write(work)
        return len(triples)

    # --- reads (agent tool) ----------------------------------------------------
    @_connection_retry
    def run_read_query(self, cypher: str, parameters: dict[str, Any] | None = None) -> ReadResult:
        """Run agent-authored Cypher in a READ transaction with timeout and row cap.

        READ access mode makes the server reject writes; pair it with a
        reader-role account (Enterprise) for least privilege.
        """
        max_rows = self._max_rows

        @unit_of_work(timeout=self._query_timeout_s)
        def work(tx: ManagedTransaction) -> ReadResult:
            result = tx.run(cast(LiteralString, cypher), parameters or {})
            rows: list[dict[str, Any]] = []
            for record in result:
                if len(rows) == max_rows:
                    return ReadResult(rows, truncated=True)
                rows.append(record.data())
            return ReadResult(rows, truncated=False)

        with self._driver.session(database=self._database, default_access_mode=READ_ACCESS) as session:
            return session.execute_read(work)

    def describe_schema(self) -> str:
        """Live labels and relationship types, appended to the static data model."""
        try:
            labels = self.run_read_query("CALL db.labels() YIELD label RETURN collect(label) AS v").rows[0]["v"]
            rel_types = self.run_read_query(
                "CALL db.relationshipTypes() YIELD relationshipType RETURN collect(relationshipType) AS v"
            ).rows[0]["v"]
        except Exception:  # schema hints are best effort; the agent can still explore
            return DATA_MODEL
        return f"{DATA_MODEL}\n\nLabels present: {sorted(labels)}\nRelationship types present: {sorted(rel_types)}"


def _plan_writes(triples: Sequence[GroundedTriple]):
    entities: dict[str, dict[str, Any]] = {}
    chunks: dict[str, dict[str, Any]] = {}
    mentions: set[tuple[str, str]] = set()
    relations: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for grounded in triples:
        t = grounded.triple
        chunks[grounded.chunk_id] = {
            "chunk_id": grounded.chunk_id,
            "source_id": grounded.source_id,
            "sensitivity": grounded.sensitivity.value,
        }
        for ref in (t.head, t.tail):
            row = entities.setdefault(
                f"{ref.key}\x1f{grounded.chunk_id}",
                {
                    "key": ref.key,
                    "name": ref.name,
                    "type": ref.type.value,
                    "description": ref.description,
                    "chunk_id": grounded.chunk_id,
                    "source_id": grounded.source_id,
                    "sensitivity_rank": grounded.sensitivity.rank,
                    "codes": json.dumps({k.value: v for k, v in ref.proposed_codes.items()}, sort_keys=True),
                },
            )
            row["description"] = row["description"] or ref.description
            mentions.add((ref.key, grounded.chunk_id))
        if not RELATION_RE.fullmatch(t.relation):  # schema validator guarantees this; defence in depth
            raise ValueError(f"unsafe relationship type {t.relation!r}")
        relations[t.relation].append(
            {
                "head_key": t.head.key,
                "tail_key": t.tail.key,
                "chunk_id": grounded.chunk_id,
                "evidence": t.evidence,
                "certainty": t.certainty.value,
                "valid_at": t.valid_at.isoformat() if t.valid_at else None,
            }
        )
    by_label: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in entities.values():
        by_label[row["type"]].append(row)
    mention_rows = [{"key": k, "chunk_id": c} for k, c in sorted(mentions)]
    return by_label, list(chunks.values()), mention_rows, relations


def _write_batch(tx: ManagedTransaction, entities, chunks, mentions, relations) -> None:
    tx.run(
        """
        UNWIND $rows AS row
        MERGE (c:Chunk {chunk_id: row.chunk_id})
        SET c.source_id = row.source_id, c.sensitivity = row.sensitivity
        """,
        rows=chunks,
    ).consume()
    for label, rows in entities.items():
        # Labels cannot be parameters; only closed-enum literals reach here.
        EntityType(label)
        tx.run(
            cast(
                LiteralString,
                f"""
                UNWIND $rows AS row
                MERGE (e:Entity {{key: row.key}})
                  ON CREATE SET e.name = row.name, e.type = row.type, e.chunk_id = row.chunk_id,
                                e.chunk_ids = [], e.source_ids = [], e.description = row.description,
                                e.max_sensitivity_rank = row.sensitivity_rank, e.proposed_codes_json = row.codes,
                                e.created_at = datetime()
                SET e:`{label}`,
                    e.chunk_ids = CASE WHEN row.chunk_id IN e.chunk_ids THEN e.chunk_ids ELSE e.chunk_ids + row.chunk_id END,
                    e.source_ids = CASE WHEN row.source_id IN e.source_ids THEN e.source_ids ELSE e.source_ids + row.source_id END,
                    e.description = CASE WHEN coalesce(e.description, '') = '' THEN row.description ELSE e.description END,
                    e.max_sensitivity_rank = CASE WHEN row.sensitivity_rank > e.max_sensitivity_rank
                                                  THEN row.sensitivity_rank ELSE e.max_sensitivity_rank END
                // Sensitivity labels let Enterprise RBAC hide nodes per role,
                // e.g. DENY TRAVERSE ON GRAPH neo4j NODES PHI TO internal_reader.
                FOREACH (_ IN CASE WHEN e.max_sensitivity_rank >= 2 THEN [1] ELSE [] END | SET e:PII)
                FOREACH (_ IN CASE WHEN e.max_sensitivity_rank >= 3 THEN [1] ELSE [] END | SET e:PHI)
                """,
            ),
            rows=rows,
        ).consume()
    tx.run(
        """
        UNWIND $rows AS row
        MATCH (e:Entity {key: row.key}), (c:Chunk {chunk_id: row.chunk_id})
        MERGE (e)-[:MENTIONED_IN]->(c)
        """,
        rows=mentions,
    ).consume()
    for rel_type, rows in relations.items():
        tx.run(
            cast(
                LiteralString,
                f"""
                UNWIND $rows AS row
                MATCH (h:Entity {{key: row.head_key}}), (t:Entity {{key: row.tail_key}})
                MERGE (h)-[r:`{rel_type}`]->(t)
                  ON CREATE SET r.chunk_id = row.chunk_id, r.chunk_ids = [], r.evidence = row.evidence,
                                r.certainty = row.certainty, r.valid_at = row.valid_at, r.created_at = datetime()
                SET r.chunk_ids = CASE WHEN row.chunk_id IN r.chunk_ids THEN r.chunk_ids ELSE r.chunk_ids + row.chunk_id END
                """,
            ),
            rows=rows,
        ).consume()


def _delete_source(tx: ManagedTransaction, source_id: str) -> None:
    stale = tx.run(
        "MATCH (c:Chunk {source_id: $source_id}) RETURN collect(c.chunk_id) AS ids", source_id=source_id
    ).single(strict=True)["ids"]
    statements: tuple[LiteralString, ...] = (
        # Remove the document's chunks from edge/entity provenance ...
        """MATCH ()-[r]->() WHERE any(id IN r.chunk_ids WHERE id IN $stale)
           SET r.chunk_ids = [id IN r.chunk_ids WHERE NOT id IN $stale]""",
        """MATCH (e:Entity) WHERE any(id IN e.chunk_ids WHERE id IN $stale)
           SET e.chunk_ids = [id IN e.chunk_ids WHERE NOT id IN $stale],
               e.source_ids = [s IN e.source_ids WHERE s <> $source_id]""",
        # ... drop whatever only this document supported ...
        "MATCH ()-[r]->() WHERE r.chunk_ids = [] DELETE r",
        "MATCH (c:Chunk {source_id: $source_id}) DETACH DELETE c",
        "MATCH (e:Entity) WHERE e.chunk_ids = [] DETACH DELETE e",
        # ... and re-point first-seen chunk_id where that chunk is gone.
        "MATCH (e:Entity) WHERE NOT e.chunk_id IN e.chunk_ids SET e.chunk_id = e.chunk_ids[0]",
        "MATCH ()-[r]->() WHERE NOT r.chunk_id IN r.chunk_ids SET r.chunk_id = r.chunk_ids[0]",
    )
    for statement in statements:
        tx.run(statement, stale=stale, source_id=source_id).consume()


_WRITE_KEYWORDS = re.compile(
    r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|FOREACH|LOAD\s+CSV|IN\s+TRANSACTIONS|"
    r"GRANT|REVOKE|DENY|ALTER|RENAME|TERMINATE|SHOW|USE)\b",
    re.IGNORECASE,
)
# Procedure calls are blocked except read-only introspection; CALL { } and
# CALL (vars) { } subqueries are allowed.
_PROCEDURE_CALL = re.compile(r"\bCALL\s+(?![({])(?!db\.(?:labels|relationshipTypes|propertyKeys)\s*\()", re.IGNORECASE)
_STRING_LITERAL = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")
_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)


class UnsafeCypherError(ValueError):
    pass


def validate_read_only_cypher(cypher: str, *, max_chars: int = 4000) -> str:
    """Reject anything that is not a single read query.

    Defence in depth only - the authoritative controls are the READ
    transaction and the database role.
    """
    query = cypher.strip().rstrip(";").strip()
    if not query:
        raise UnsafeCypherError("query is empty")
    if len(query) > max_chars:
        raise UnsafeCypherError(f"query exceeds {max_chars} characters")
    code = _STRING_LITERAL.sub("''", _COMMENT.sub(" ", query))
    if ";" in code:
        raise UnsafeCypherError("only one statement per call")
    if match := _WRITE_KEYWORDS.search(code):
        raise UnsafeCypherError(f"read-only access: {match.group(0).upper()} is not allowed")
    if _PROCEDURE_CALL.search(code):
        raise UnsafeCypherError("procedure calls are not allowed (subqueries and db.labels() etc. are)")
    return query
