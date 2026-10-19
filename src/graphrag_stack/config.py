"""Runtime configuration, loaded from environment variables (or `.env`).

Every infrastructure endpoint is configurable so the same code runs against
in-cluster services (`vllm-inference-service`, `neo4j`) and local fakes.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- vLLM (OpenAI-compatible chat completions) ---------------------------
    vllm_base_url: str = "http://vllm-inference-service:8000/v1"
    vllm_api_key: SecretStr = SecretStr("EMPTY")
    vllm_model: str = "meta-llama/Llama-3.3-70B-Instruct"
    llm_timeout_s: float = 120.0
    llm_max_retries: int = Field(default=3, ge=0)
    agent_temperature: float = 0.1
    agent_max_tokens: int = 2048

    # --- Embeddings (a separate OpenAI-compatible pooling server) ------------
    # A 70B generative deployment should not also serve embeddings; run a
    # dedicated embedding model. `fake` is deterministic and for local/tests.
    embedding_provider: Literal["openai_compatible", "fake"] = "openai_compatible"
    embedding_base_url: str = "http://vllm-embedding-service:8000/v1"
    embedding_api_key: SecretStr = SecretStr("EMPTY")
    embedding_model: str = "BAAI/bge-m3"
    embedding_dimensions: int = 1024

    # --- Neo4j --------------------------------------------------------------
    neo4j_uri: str = "neo4j://neo4j:7687"
    neo4j_database: str = "neo4j"
    neo4j_user: str = "neo4j"
    neo4j_password: SecretStr = SecretStr("")
    # The agent's Cypher tool should use a reader-role account (Enterprise).
    # Falls back to the writer account; READ access mode still applies.
    neo4j_read_user: str | None = None
    neo4j_read_password: SecretStr | None = None
    neo4j_query_timeout_s: float = 15.0
    neo4j_max_rows: int = Field(default=50, ge=1, le=1000)

    # --- Vector store (local index, persisted between processes) -------------
    vector_store_path: Path = Path(".data/vector_store.json")

    # --- Ingestion ------------------------------------------------------------
    chunk_size: int = 1200
    chunk_overlap: int = 150
    extraction_attempts: int = Field(default=3, ge=1)
    extraction_concurrency: int = Field(default=8, ge=1)
    require_grounded_evidence: bool = True

    # --- Investigator agent budget -------------------------------------------
    agent_max_turns: int = Field(default=12, ge=1)
    agent_max_total_tokens: int = Field(default=120_000, ge=1)
    agent_max_tool_calls: int = Field(default=16, ge=1)
    agent_timeout_s: float = 300.0
    agent_max_chunks_per_call: int = Field(default=10, ge=1)
    tool_result_max_chars: int = 12_000

    # --- Orchestration ---------------------------------------------------------
    max_query_chars: int = 2000
    checkpoint_backend: Literal["sqlite", "postgres", "memory"] = "sqlite"
    checkpoint_sqlite_path: Path = Path(".data/checkpoints.sqlite")
    checkpoint_postgres_uri: SecretStr | None = None

    # --- Observability ---------------------------------------------------------
    otel_service_name: str = "graphrag-stack"
    # OTLP/HTTP base URL, e.g. http://otel-collector:4318. Unset = no export.
    otel_exporter_otlp_endpoint: str | None = None
    otel_console_export: bool = False
    # Prompts, answers and Cypher text can carry PII; keep them out of spans
    # unless the trace backend is cleared for that data.
    otel_capture_content: bool = False
    deployment_environment: str = "dev"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
