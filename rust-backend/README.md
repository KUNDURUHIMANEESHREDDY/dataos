# DataOS Rust Backend

This is the default container backend for the production-hardening line. It is a Rust/Axum implementation of the DataOS API surface. It is **not yet a full feature-for-feature replacement** for the Python implementation.

## Implemented

- SQLite storage compatible with the existing `objects`, `relationships`, `object_versions`, and `dataos_users` tables
- `/health` and `/api/catalog/health`
- JWT register/login/me/users routes, PBKDF2 password verification, role capability checks
- Objects list/create/read/delete, relationships list/create
- Graph neighbors, multi-hop traversal (`/api/graph/traverse/{id}`), basic analytics (PageRank + degree centrality)
- Provenance lineage upstream/downstream (`/api/provenance/lineage/{id}`)
- Time-travel object/graph/changes queries (`/api/time_travel/*`)
- Dataset profiling (`/api/profiling/{id}`) and quality-rule evaluation with first-class `quality_report` objects (`/api/quality/{id}`)
- Sharing tokens: HMAC-SHA256 issue/verify with tamper + expiry detection (`/api/sharing/*`)
- Vector index recompute + cosine search over deterministic 128-dim embeddings (`/api/vectors/*`)
- Sync conflict resolution (`/api/sync/resolve_conflict`)
- Bounded built-in workflow execution (`/api/workflows/execute`) — `noop`/`set_variable`/`log` only, with cycle detection and payload limits
- Agent dispatch (`/api/agents/execute`) — deterministic capabilities execute for real
- 4-stage research pipeline (`/api/agents/pipeline/research`) — search, SQL analysis, quality contract, grounded report with `derived_from` linkage
- Scoped evidence retrieval (`/api/knowledge/query`) — one-hop related files, ranked excerpts, `generation_available: false`
- Notebook/document ingest (`/api/notebooks/ingest`, `/api/documents/extract_rich`)
- Hybrid-ish text search by substring over serialized objects
- Safe read-only SQL execution against registered tabular dataset objects
- CSV/JSON ingest into DataOS objects
- Exact-hash duplicate detection
- JSON graph export, recommendations, federation-search local fallback
- Capability authorization middleware with JWT auth
- Contract test suite (`src/api_tests.rs`, 14 tests) covering the router end to end
- **Route parity:** every route declared in `backend/app.py` and `backend/knowledge_rag.py` exists in the Rust router

## Not implemented yet

- Python sandbox / unified Python execution (returns 403 by policy; research-pipeline stage 2 returns 501 for non-SELECT analysis)
- Natural-language Ask/RAG intelligence (`/api/ask`, `query_type: ask|natural_language`)
- LLM-backed agent behaviours (`agent_research` reasoning, report generation) — the deterministic provider is used instead
- Model-backed semantic embeddings — the vector index uses a documented lexical (hashed bag-of-words) method
- Blob storage, Postgres backend, and cloud storage parity

Routes whose backing engine has no Rust equivalent return HTTP 501 with an explicit message; they do not silently fabricate results.

## Run locally

```bash
cd rust-backend
DATAOS_DB_PATH=/tmp/dataos-rust.db \
DATAOS_JWT_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')" \
cargo run --release
```

Container:

```bash
docker build -t dataos-rust .
docker run --rm -p 8000:8000 \
  -e DATAOS_JWT_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')" \
  dataos-rust
```
