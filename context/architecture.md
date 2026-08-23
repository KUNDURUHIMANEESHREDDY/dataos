# DataOS — Architecture Context

## Stack

| Layer | Technology | Role |
|-------|-----------|------|
| **Framework** | Next.js 16 + React 19 + TypeScript | Primary web application framework (per frontend-dev skill default) |
| **UI** | Tailwind CSS v4 + shadcn/ui + Framer Motion + Three.js + @react-three/fiber + @react-three/drei | Visual interface, animations, 3D capabilities |
| **Backend** | FastAPI + uvicorn + Python 3.11 | REST API layer, computation engine, API-first architecture |
| **Database** | PostgreSQL + Prisma ORM | Core data store for universal object model, relationships, provenance |
| **ML/ computation** | TensorFlow + PyTorch + scikit-learn + mlflow + pandas + numpy | Data science, statistical analysis, ML production pipelines |
| **Graph Analysis** | networkx + python-louvain | Graph algorithms, traversal, clustering, centrality, pathfinding |
| **Search** | exa-js + custom embeddings | Hybrid search: full-text, metadata, semantic embeddings, graph traversal, structured queries |
| **Workflow** | celery + django-celery-beat | Background job processing, scheduled events, triggers |
| **File Processing** | reportlab + pypdf + python-docx + openpyxl | PDF, DOCX, XLSX, CSV, JSON, XML intelligence |
| **Notebooks** | ipython + jupyter + nbconvert | Notebook integration as structured executable objects |
| **Auth/Authorization** | Django permissions + custom RBAC | Fine-grained access control, object-level and collection-level permissions |
| **Versioning** | Prisma migrations + mlflow runs | All critical entities versioned — objects, schemas, graph states, analyses, workflows, agents |
| **Observability** | OpenTelemetry integration | Logs, metrics, traces across all system components |

## System Boundaries

- **`api/`** — FastAPI routes and middleware (owns all HTTP endpoints, request validation, response formatting)
- **`core/`** — Universal object model, graph engine, provenance system (owns data model, relationship management, lineage tracking)
- **`db/`** — Prisma schemas and migrations (owns database schema, migration strategy, version tracking)
- **`frontend/`** — Next.js pages and components (owns UI, user interactions, local state)
- **`workflows/`** — Transformation pipelines and orchestration (owns trigger→conditions→actions→outputs chains)
- **`search/`** — Hybrid search engine (owns indexing, query processing, result ranking)
- **`agents/`** — AI agent layer (owns agent configurations, capability maps, permission profiles)
- **`plugins/`** — Extensibility plugins (owns plugin registry, connector interfaces, AI provider abstractions)
- **`imports/`** — Ingestion system (owns artifact import, metadata extraction, provenance initialization)
- **`exports/`** — Export system (owns data/graph/export formatting, portability guarantees)

## Storage Model

| Storage Type | What Lives Here | Example Data |
|--------------|-----------------|--------------|
| **Database (PostgreSQL via Prisma)** | Object metadata, relationship definitions, provenance records, schema versions, permissions, quality metrics, catalog entries | Object records: `{id, type, schema, relations, provenance, permissions, timestamps, version, source, metadata, indexes}`; Relationship records: `{source, target, relation_type, metadata, confidence, provenance, created_at, updated_at}`; Schema versions with dependency graphs |
| **Object Storage (S3/GCS/Azure)** | Raw artifacts, generated files, media, large binary objects | Original files: `paper.pdf`, `dataset.csv`, `lecture.mp4`; Generated: `transcript.txt`, `concepts.json`, `summary.md`; Exports: JSON dumps, CSV files, Parquet files |
| **Graph Database/Structure** | Runtime graph structure for traversal queries | In-memory graph: `networkx.DiGraph` with nodes as object IDs, edges as relationship tuples; Index structures for confidence, timestamps, relation types |
| **Cache Layer** | Frequently accessed data, computation results, search indexes | Dependency-aware cache: `{key: "object:123", ttl: computed from usage frequency, dependencies: ["query:456"]}`; Search result cache with invalidation on parent object changes |
| **Event Log** | System-wide event bus entries | Object lifecycle events: `ObjectCreated`, `ObjectUpdated`, `ObjectDeleted`; Schema changes: `SchemaVersioned`, `SchemaDeprecated`; Query executions: `QueryExecuted` with provenance; Workflow executions: `WorkflowStarted`, `WorkflowCompleted`, `WorkflowFailed` |

## Auth and Access Model

- **Authentication** — Every user/service signs in via integrated auth provider (OAuth, API key, or self-hosted credentials); token validated on each API request
- **Object-Level Permissions** — Every DataOS object has explicit permissions: `read`, `read-write`, `delete`, `modify-provenance`; permissions attached to object record, inherited by related objects per relation_type
- **Collection-Level Permissions** — Collections (folders, projects, datasets) have ownership and collaborator lists; permissions propagate to contained objects per defined hierarchy
- **Operation-Level Restrictions** — Specific API operations gated per role: e.g., `agent-can-query`, `agent-can-transform`, `agent-can-create`, `agent-can-delete`; operation permissions separate from read/write
- **Time-Bound Access** — Permissions can have expiration timestamps; time-bound access automatically revoked after expiry; useful for temporary collaborators, short-term projects
- **Approval-Based Execution** — Certain operations require approval workflow: e.g., schema changes, relationship modifications, destructive operations; approval tracked in provenance, granted/rejected recorded
- **Agent Permissions** — AI agents have capability maps defining allowed operations per agent type: research agents → search+read; analysis agents → query+transform; coding agents → read+execute+create; data quality agents → validate+report
- **Inheritance Model** — Permissions inherit from parent to child per graph structure; explicit overrides possible at any level; revocation propagates down per dependency graph

**Invariants (never violate):**

1. **Never fabricate data or results** — All computation executed against real data sources; zero tolerance for fabricated outputs
2. **Always preserve lineage** — Every derived result includes complete provenance; source data never silently modified
3. **Maintain transparency** — All system operations visible and traceable; no hidden provenance or transformation steps
4. **Ensure reproducibility** — All analyses reproducible with inputs, code, environment, and data versions; deterministic execution where possible
5. **Support portability** — Full portability of data, models, and workflows; no vendor lock-in; export formats retain completeness
6. **Domain neutrality** — Core system free of domain-specific logic; all specialized workflows emerge from general-purpose primitives
7. **Provenance is first-class** — Provenance metadata never omitted, truncated, or silently dropped; full traceability maintained from origin to final output
8. **Graph consistency** — All relationship records include required fields: source, target, relation_type, metadata, confidence, provenance, created_at, updated_at; no orphaned relationships
9. **Schema version backward compatibility** — Schema migrations maintain backward compatibility; deprecated fields remain readable; breaking changes require explicit opt-in
10. **AI outputs include grounding** — All AI outputs include claims, evidence, computations, source references; no unsupported assertions allowed

## Invariants (Detailed)

```yaml
invariants:
  - never_fabricate_data: "All computation must be against real data sources; zero fabricated results"
  - always_preserve_lineage: "Every derived result must include full provenance traceability"
  - maintain_transparency: "No hidden transformation steps; all operations visible and traceable"
  - ensure_reproducibility: "Deterministic execution where possible; reproducible with inputs/code/environment/data versions"
  - support_portability: "Full portability of data, models, workflows; no vendor lock-in"
  - domain_neutrality: "Core system free of domain-specific logic; workflows from primitives only"
  - provenance_first_class: "Provenance never omitted, truncated, or silently dropped"
  - graph_consistency: "All relationships include required fields; no orphaned relationships"
  - schema_version_bwc: "Migrations maintain backward compatibility; breaking changes require explicit opt-in"
  - ai_answer_grounding: "All AI outputs include claims, evidence, computations, source references"
```