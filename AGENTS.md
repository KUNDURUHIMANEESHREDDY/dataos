# DataOS — Agent Guide

**Graph-based data operating system.** Universal object model, first-class relationship graph, first-class provenance. AI is an operator over the graph, never an authority.

## Stack

- **Backend:** FastAPI + Python, SQLite default (Postgres optional), uvicorn on `:8000`
- **Frontend:** Next.js 16 (Turbopack), React 19, Tailwind 4, Zustand — `npm run dev` on `:3000`, proxies `/api` → backend
- **Kernel:** `dataos_system.py` — single `DataOS` class exposing `ingest`, `sql`, `python`, `search`, `why`, `impact`, `ask`, `profile`

## Layout

```
core/             object model, relations, permissions, provenance, versioning
engines/          12 engines: graph, compute, search, profiling, quality, query,
                  provenance, governance, diff, catalog, actions, usage
infrastructure/   storage (sqlite/postgres/cloud), ingest, export, sync, federation
intelligence/     discovery, document parsers, semantic embeddings
runtime/          grounding, agents, workflows
backend/app.py    FastAPI app — all routes under /api, health at /health
src/              Next.js frontend
tests/            plain unittest, no conftest
cli/              `python -m cli {ingest,sql,search,health,export}`
```

## Auth (production)

- **Shared token gate:** `DATAOS_API_TOKEN` (≥32 bytes) required for all `/api/*` in production.
- **Per-user JWT:** `DATAOS_JWT_SECRET` (≥32 bytes) enables `/api/auth/register`, `/api/auth/login`, `/api/auth/me`. Roles: `viewer` < `analyst` < `operator` < `admin`, mapped to `Capability` sets in `core/permissions/policy.py` (`ROLE_CAPABILITIES`).
- **Python compute:** disabled in production unless `DATAOS_ALLOW_PYTHON_COMPUTE=true`.
- **Sharing tokens:** `DATAOS_SHARING_TOKEN_SECRET` required for `/api/sharing/*`.

All secrets come from environment (see `.env.example`). Never commit them.

## Run

```bash
pip install -r requirements.txt
python -m pytest tests/ --ignore=tests/test_benchmarks.py   # 712 tests
python scenario_demo.py                                      # end-to-end demo
python -m uvicorn backend.app:app --reload                   # backend :8000
npm run dev                                                  # frontend :3000

docker compose up --build                                    # backend only
docker compose --profile frontend up --build                 # backend + frontend
```

## Key invariants

- **Grounding:** AI assertions without evidence raise — never fabricate.
- **Provenance:** every derived result traces to real sources via graph edges.
- **Storage parity:** SQLite and Postgres backends must keep identical signatures (`relation_id`, not `rel_id`; `soft=True` on deletes, `source` on list).
- **Frontend contract:** API emits `source`/`target` (not `source_id`/`target_id`) on relationships.

<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->
