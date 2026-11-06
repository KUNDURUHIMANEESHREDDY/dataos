# DataOS Rust Backend

This is the default container backend for the production-hardening line. It is a Rust/Axum implementation of the DataOS API surface. It is **not yet a full feature-for-feature replacement** for the Python implementation.

## Implemented

- SQLite storage compatible with the existing `objects`, `relationships`, `object_versions`, and `dataos_users` tables
- `/health` and `/api/catalog/health`
- JWT register/login/me/users routes, PBKDF2 password verification, role capability checks
- Objects list/create/read/delete, relationships list/create
- Graph neighbors and basic analytics (PageRank + degree centrality)
- Hybrid-ish text search by substring over serialized objects
- Safe read-only SQL execution against registered tabular dataset objects
- CSV/JSON ingest into DataOS objects
- Exact-hash duplicate detection
- JSON graph export, recommendations, federation-search local fallback
- Capability authorization middleware with JWT auth

## Not implemented yet

- Python sandbox / unified Python execution
- Natural-language Ask/RAG intelligence
- Workflows/agents/governance engines beyond exact duplicate detection
- Time-travel/sync/provenance engine parity
- Blob storage, Postgres backend, and cloud storage parity
- Full semantic/vector search
- Full compatibility tests for every Python API route

Routes not yet ported return HTTP 501 with an explicit message; they do not silently fabricate results.

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
