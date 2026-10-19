// Neo4j Enterprise: least-privilege reader for the agent's Cypher tool.
// Point NEO4J_READ_USER / NEO4J_READ_PASSWORD at this account. Entities that
// came from PII/PHI chunks carry :PII / :PHI labels, so the database itself
// hides them - including from scalar projections the Python redaction cannot see.
// Run with the system database selected. Set the password via a parameter, never in this file.
CREATE ROLE graphrag_internal_reader IF NOT EXISTS AS COPY OF reader;
DENY TRAVERSE ON GRAPH neo4j NODES PII TO graphrag_internal_reader;
DENY TRAVERSE ON GRAPH neo4j NODES PHI TO graphrag_internal_reader;
CREATE USER graphrag_agent IF NOT EXISTS SET PASSWORD $password CHANGE NOT REQUIRED;
GRANT ROLE graphrag_internal_reader TO graphrag_agent;
