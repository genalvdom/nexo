# Bundle Update Log

## 2026-10-19
* **Update**: Added [entity resolution](components/entity-resolution.md), the [relation ontology](components/relation-ontology.md) and the lexical graph to the [data model](architecture/data-model.md), after reviewing five [knowledge-graph construction guides](references/).
* **Update**: Moved telemetry to the [OpenTelemetry GenAI conventions](references/opentelemetry-genai-conventions.md); documented in [Observability](operations/observability.md). Logging replaces CLI prints.
* **Creation**: [ADR-0007](decisions/adr-0007-entity-resolution.md) to [ADR-0011](decisions/adr-0011-langsmith-adoption.md); ADR-0011 (LangSmith) is proposed.
* **Creation**: Established the bundle: [architecture](architecture/), [components](components/), [operations](operations/), [decisions](decisions/) and [references](references/). All concepts start as `draft` and unverified.
* **Initialization**: Documented the code at the rename to Nexo (package `nexo`, CLI `nexo`).
