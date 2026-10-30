# DataOS

A Python data platform built around three ideas: a **universal object model**, a **first-class relationship
graph**, and **first-class provenance** — every derived result traceable back to its real source.

The design principle, stated in `context/ai-workflow-rules.md`: **AI is an operator over the graph, never an
authority over it.**

> **Verification status (PR branch):** the latest source-verification head `e8cd5bfc9adb7967213ac7ff06c5c1349dc68965` passed frontend workflow [#41066979558](https://github.com/KUNDURUHIMANEESHREDDY/dataos/actions/runs/41066979558) and backend/security workflow [#41066979353](https://github.com/KUNDURUHIMANEESHREDDY/dataos/actions/runs/41066979353). Frontend: 13 pagination/relationship tests, TypeScript, Next.js production build, `npm audit` with zero vulnerabilities, and CycloneDX SBOM. Backend/security: 720 tests passed, 1 skipped; 74/74 scenario invariants; live PostgreSQL migration/source-filter/soft-delete contract; workflow-integrity tests; Gitleaks; dependency audit; SBOM; CodeQL; and both required aggregates. These are pull-request checks, not deployed-production evidence. Remaining blockers include per-user/resource authorization, encryption-key lifecycle, backup/restore and rollback, deployed acceptance, and verified branch-protection enforcement. See [Current blockers](#current-blockers).

---

## Current blockers

### ✅ Resolved

Six bugs that made the project unusable, fixed in `dab962b` and `4193152`:

- **`import dataos_system` failed with `NameError: name 'Union' is not defined`.** `core/permissions/policy.py:7`
  imported from `typing` without `Union`, which lines 56 and 61 used in eagerly-evaluated annotations. Because
  `core/__init__.py:11` imports that module, this took down the kernel, backend, CLI, demo, and every test.
- **`ActionResult.execution_time_ms` measured as `0.0`.** `engines/actions/registry.py` used `time.time()`, whose
  clock granularity on Windows is ~16 ms, so any fast action timed as zero. Now uses `time.perf_counter()`.
- **`graph.analytics()` raised `AttributeError`.** It called
  `GraphAnalyticsEngine.compute_all_metrics()`, which has never existed. It now aggregates the real methods
  (PageRank, degree/betweenness centrality, communities).
- **All 4 CLI commands called methods that no longer exist** — `ingest_file`, `execute_sql`, `search.search`,
  `get_system_health`. Now mapped to `ingest()`, `sql()`, `search()`, with `health` assembled from live storage
  state. Added `cli/__main__.py` so `python -m cli` runs without a `runpy` warning.
- **`scenario_demo.py` died at line 83.** Six nonexistent calls, a wrong ingest return shape, and
  `shutil.rmtree(onexc=)` which needs Python 3.12 (`onerror=` works on 3.11).
- **`npm install` failed.** `django: ^99.99.99`, `fastapi: ^0.0.8`, and `uvicorn: ^0.0.1-security` are Python
  packages pinned to versions never published. Removed, along with `cors` and `pg` (Node server libs a Next.js
  frontend cannot use). Now resolves 252 packages.
- **No Python dependency manifest existed.** Added `requirements.txt`.

### Still open

#### 1. Production API authorization is not yet multi-user safe

The current PR repairs the FastAPI-to-kernel method contracts and verifies the backend through the current CI suite. The old claim that roughly 22 endpoints are known to return HTTP 500 is stale and should not be used as the current status.

Remaining authorization work is still material:

- Production `/api/*` requests use a single shared bearer token; this is not per-user identity, role-based access control, or resource-level authorization.
- The library's capability policy and grounding checks are not consistently enforced at the HTTP boundary.
- Python compute is disabled by default in production unless `DATAOS_ALLOW_PYTHON_COMPUTE=true`; that opt-in does not prove the sandbox is safe.
- The live PostgreSQL CI contract now covers additive migration, source filtering, and soft-delete visibility; the Dataspace relationship serializer mismatch is normalized and regression-tested on this PR branch. Broader cloud-adapter parity, backup/restore, and deployed acceptance remain open.

Treat these as release blockers until the corresponding API and deployment tests exist.

#### 2. Prisma is dead weight

There is a 224-line `prisma/schema.prisma` and `prisma` in `devDependencies`, but **nothing in `src/` imports
Prisma**, there is no `@prisma/client`, there are no Prisma scripts, and the schema's `datasource` has no `url`.
SQLite is the default store; the schema is unused.

---

## CI verification

`.github/workflows/backend-verification.yml` verifies the Python correctness suite, scenario invariants, CLI health, live PostgreSQL contract, and backend/security gates. The `Backend required` aggregate fails closed when its required backend/security jobs fail, are cancelled, or are skipped.

The PR branch also contains `.github/workflows/frontend-verification.yml`. It performs a clean `npm ci`, high-severity dependency audit, pagination/relationship contract tests, TypeScript validation, Next.js production build, and CycloneDX SBOM generation/upload. The current lockfile is reproducible with `npm ci`, and the latest exact-head audit reported zero vulnerabilities. These are separate required workflow aggregates; repository branch-protection settings have not been verified, so do not assume GitHub enforces both checks before merge.

---

## Runtime security configuration

DataOS sharing-token signing has no built-in/default secret. Configure `DATAOS_SHARING_TOKEN_SECRET` with a randomly generated value of at least 32 UTF-8 bytes through your deployment secret manager before using `/api/sharing/issue_token` or `/api/sharing/verify_token`. If it is missing, the API returns HTTP 503 and token support remains disabled. Never commit the value to the repository or include it in logs.

For local development, generate a value without printing it separately:

```bash
export DATAOS_SHARING_TOKEN_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
```

This secret protects sharing-token signatures only. It does **not** authenticate the rest of the FastAPI API. SQL/Python execution, writes, ingestion, and data-reading routes still need an explicit authentication/authorization boundary; do not expose the API to untrusted networks until that work is completed.

### Production API authentication

When any of `DATAOS_ENV`, `APP_ENV`, or `ENVIRONMENT` is set to `production` or `prod`, every `/api/*` route requires an `Authorization: Bearer …` header. Configure `DATAOS_API_TOKEN` as a high-entropy secret of at least 32 UTF-8 bytes through the deployment secret manager. If the token is absent, padded with accidental whitespace, or too short, API requests fail closed with HTTP 503; missing or incorrect bearer credentials return HTTP 401. Environment markers are checked independently, so a conflicting `development` marker does not disable the production guard. The non-`/api` health route remains available for liveness monitoring.

Generate a token without committing or printing it to logs:

```bash
export DATAOS_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
```

Python execution is a separate high-risk capability. In production, both `/api/compute/python` and unified-query `query_type=python` are disabled unless `DATAOS_ALLOW_PYTHON_COMPUTE=true` is explicitly configured. Keep it disabled unless the execution sandbox and access controls have been reviewed. This flag is an opt-in, not proof that the sandbox is safe.

This is a single shared bearer-token boundary, not per-user identity or role-based authorization. Rotate it through secret management and do not expose it to browser bundles. If a public browser client needs access, place a properly authenticated backend-for-frontend or identity-aware gateway in front of DataOS rather than embedding this token in frontend code.


---

## Quick start

```bash
pip install -r requirements.txt
```

There is no `pyproject.toml`/`setup.py` — the package runs from the repo root.

```bash
python -m pytest tests/ --ignore=tests/test_benchmarks.py   # correctness suite (CI reports the current test count)
python scenario_demo.py                                      # 10-step end-to-end demo
python -m cli health                                         # CLI
```

### CLI

```bash
python -m cli ingest data.csv
python -m cli sql "SELECT name, score FROM demo_csv"
python -m cli search "alpha" --limit 3
python -m cli health
python -m cli export --format dot
```

The kernel imports cleanly with no extra setup — SQLite is the default store, no external service is required.

### Library

```python
from dataos_system import DataOS

d = DataOS(db_path="dataos.db")

# ingest() returns a result dict — the new object id is primary_object_id
obj_id = d.ingest("data.csv")["primary_object_id"]

d.why(obj_id)       # why does this exist?
d.impact(obj_id)    # what breaks if this changes?
d.profile(obj_id)   # statistical profile
d.ask("which majors have the highest average GPA?")
d.sql("SELECT major, AVG(gpa) FROM dataset GROUP BY major")
d.search("query text")
d.graph.neighbors(obj_id)
d.graph.analytics()
d.close()
```

Convenience methods that genuinely exist: `from_url`, `ingest`, `why`, `impact`, `ask`, `sql`, `python`,
`search`, `search_vector`, `profile`, `embed`, `embed_batch`, `classify`, `ingest_source`, `export_data`, `mask`,
`check_rate_limit`, `close`.

### Backend

```bash
python -m uvicorn backend.app:app --reload    # port 8000, must run from repo root
```

For direct browser-to-API development, set `DATAOS_CORS_ORIGINS` to a comma-separated
list of exact origins (scheme, host, and optional port), for example
`http://localhost:3000,http://127.0.0.1:3000`. Wildcards, paths, credentials in
origins, query strings, and malformed values are rejected at startup. If the variable
is unset, only the two local frontend origins are allowed; setting it to an empty
string disables cross-origin access. The Next.js rewrite proxy remains same-origin.

`backend/app.py` has no `__main__` block, so the uvicorn CLI is the only way to start it.

### Frontend

```bash
npm run dev      # next dev -p 3000
```

`next.config.js` proxies `/api/:path*` to `http://127.0.0.1:8000`. `src/lib/api.ts` uses an empty `API_BASE`, so
all calls are same-origin.

---

## The 12 engines

`engines/` contains exactly 12 sub-packages:

| Engine | Contents |
|---|---|
| `graph/` | `GraphEngine`, `GraphAnalyticsEngine`, `GraphRecommendationEngine` — multi-hop traversal, path finding, PageRank/centrality/communities via NetworkX |
| `compute/` | `SQLExecutionEngine`, `PythonSandbox`, `StatisticalEngine`, `TransformationEngine` — 16 built-in pipeline transforms |
| `search/` | `HybridSearchEngine` — BM25/TF-IDF + vector similarity + graph proximity, default weights `0.45 / 0.35 / 0.20`; SQLite-backed vector index |
| `profiling/` | `DataProfiler` — "all results computed from actual data — NEVER simulated" |
| `quality/` | `DataQualityEngine`, `DataContract` — `not_null`/`unique`/`range`/`regex`/`row_count_min`, KS-2-sample drift |
| `query/` | `UnifiedQueryEngine`, `AskDataOSEngine` — SQL/Python/graph/NL dispatch with intent classification |
| `provenance/` | `ExplanationEngine` — "why does this exist", "what breaks if I change this" |
| `governance/` | `DuplicateDetectionEngine` (Levenshtein + MinHash Jaccard, never silently deletes), `ContractValidator` |
| `diff/` | `SemanticDiffEngine`, `DataDiffEngine`, `DiffEngineManager` |
| `catalog/` | `DataCatalog`, `DataCatalogEngine` — asset inventory, freshness, health score |
| `actions/` | `ActionsRegistry`, `ObjectAction` — dynamic per-type capabilities |
| `usage/` | `UsageTracker` — consumption, popularity, hourly timeline |

**Kernel wiring is not equivalent to API exposure.** `dataos_system.py` currently imports and instantiates the graph, search, compute, profiling, quality, provenance, and query engines, alongside discovery, lineage, grounding, embedding, federation, ingestion, and other subsystems. The `governance`, `diff`, `catalog`, `actions`, and `usage` packages are separate engine areas; their presence or importability does not establish that a supported HTTP route exposes them. Treat API reachability as a route/contract inventory rather than inferring it from the number of imported classes.

---

## The object model

`core/object/model.py` defines a 13-field `DataObject`:

```python
id, type, schema, properties, content, relations, provenance,
permissions, timestamps, version, source, metadata, indexes
```

`ObjectType` has 22 values (`DATASET`, `DOCUMENT`, `QUERY`, `AGENT`, `EVIDENCE`, `WORKFLOW`, `METRIC`,
`QUALITY_REPORT`, `CONTRACT`, …). `compute_hash()` is SHA-256 over sorted JSON of
type/schema/properties/content/source/version; `create_new_version()` appends to
`provenance["transformations"]`.

`core/relation/` provides 23 relation types (`DERIVED_FROM`, `SUPPORTED_BY`, `CONTRADICTS`, `SUPERSEDES`, …) and a
`Relationship` dataclass whose `confidence` is clamped to `0.0–1.0` in `__post_init__`.

**Note:** `prisma/schema.prisma` mirrors this model with 11 tables and 17 columns — but no code uses it.

---

## Provenance: what is actually enforced

Three layers exist; only two are real.

**Enforced — automatic version snapshots.** `infrastructure/storage/sqlite_store.py` writes an `object_versions`
row on **every** `save_object()`, capturing the full data snapshot, content hash, author, and change summary.
This is the one provenance guarantee that is genuinely automatic on the write path.

**Enforced — OpenLineage export.** `ProvenanceEvent.to_openlineage_run_event()` produces valid OpenLineage
RunEvent JSON, and `tests/test_kernel.py` asserts on it.

**Not enforced — the event log.** `record_provenance_event()` exists on all three storage backends but is called
**only from tests**. Lineage traversal reconstructs ancestry purely from graph edges
(`DERIVED_FROM`, `TRANSFORMS_TO`, `READS_FROM`, `PRODUCES`, `DEPENDS_ON`) and never reads `provenance_events`.
So "provenance traversal" is really dependency-graph traversal, not an audit trail.

---

## "AI as operator, never authority"

Two real mechanisms enforce this — both in the library layer, **neither wired into the HTTP API**.

### Capability gating

`core/permissions/policy.py` defines 15 capabilities and a `PermissionPolicy` with an
`allowed_capabilities` default of `{SEARCH, READ_OBJECT, CREATE_RELATION, QUERY_SQL, COMPUTE_PYTHON}` and
`requires_approval_for = {DELETE_OBJECT, DELETE_RELATION}`. `runtime/agents/agent.py:44-54` enforces it:

```python
if not self.policy.has_capability(cap_val):
    raise PermissionError(f"Permission denied: Agent '{self.agent_id}' does not have capability '{cap_val}'")
```

`MultiAgentPipeline` builds four harnesses with explicit least-privilege allowlists: research, analysis,
quality, and report.

### Grounding gate — fails loud

`runtime/grounding/grounder.py` refuses to emit any AI assertion without evidence or computation:

```python
unverified_claims = [a.claim for a in assertions if not a.is_verified]
if unverified_claims:
    raise ValueError(f"DataOS Grounding Violation (Rule #73): The following claims lack "
                     f"supporting evidence or computation: {unverified_claims}")
```

This is the strongest guarantee in the codebase and it is covered by
`tests/test_no_fabricated_results.py`. It is called from the orchestrator and the demo — **but not from
`backend/app.py`**.

### Sandbox

`engines/compute/python_sandbox.py` validates AST, allowlists builtins, blocks `__subclasses__`/`__globals__`/
`__code__`, denies `eval`/`exec`/`open`/`__import__`/`getattr`, rejects `async def`/`for`/`with`, and caps
execution at 10s and 10 MB output.

---

## Configuration

Core encryption reads `DATAOS_MASTER_KEY` (`infrastructure/privacy/encryption.py:54`). The FastAPI
deployment layer also reads environment markers (`DATAOS_ENV`, `APP_ENV`, `ENVIRONMENT`), the production
API bearer secret (`DATAOS_API_TOKEN`), CORS configuration (`DATAOS_CORS_ORIGINS`), sharing-token secret
(`DATAOS_SHARING_TOKEN_SECRET`), and the high-risk Python-compute opt-in
(`DATAOS_ALLOW_PYTHON_COMPUTE`). Check the relevant module before deploying; this list describes the
current core/API controls, not every optional provider's configuration.

Storage defaults remain constructor arguments: `db_path="dataos.db"`, `blob_dir=".dataos_blobs`, and
`PostgresStorage`'s connection string (currently no `DATABASE_URL` lookup).

**No external service is required for the default SQLite store.** Postgres, S3, GCS, and Azure are optional.
A requested PostgreSQL store now **fails closed** if the driver, connection, or schema initialization fails; it
does not silently downgrade to ephemeral in-memory SQLite. That avoids reporting successful writes to a temporary
store when the operator configured durable PostgreSQL. `mock_mode=True` is explicit SQLite emulation for tests
only; do not use it as a production fallback.

**By default no LLM is wired in.** `MultiAgentPipeline` defaults to `MockDeterministicProvider`, a
string-templating stub. Embeddings default to `HashEmbeddingProvider(dimension=128)` — a feature hash, not a
model.

---

## Storage and contract status

The live PostgreSQL CI integration test now creates a pre-soft-delete schema and verifies the additive
`deleted_at` migration, source-filtered object counts/listing, and soft-delete visibility against a real
PostgreSQL service. The ordinary dual-backend suite still uses PostgreSQL mock mode for broad contract
coverage, so this does not establish full production parity for every storage method or cloud adapter.
Backup/restore, failover, and rollback drills remain release blockers.

The backend relationship serializer emits canonical `source` and `target` fields. The Dataspace PR branch
normalizes those fields into graph edges, retains `source_id` / `target_id` compatibility for older
integrations, and rejects malformed endpoints. The frontend regression suite covers the canonical and
legacy contracts; confidence is now constrained to the API's inclusive `0..1` range.

CORS uses an explicit `DATAOS_CORS_ORIGINS` allowlist (defaulting to local frontend origins), rejects wildcard or malformed origins, and does not enable credentialed cross-origin requests. In production, `/api/*` routes require the configured shared bearer token; this is not per-user identity or resource-level authorization, which remains a high-priority production blocker.

---

## Tests

48 files, ~660 test methods — 39 unit files plus `tests/e2e/` (4 scenario tests) and `tests/benchmarks/`.
Plain `unittest`, each file self-contained with `tempfile.mktemp` in `setUp`. No `conftest.py`, no pytest config.

```bash
python -m pytest tests/                              # the documented gate
python -m pytest tests/ --ignore=tests/test_benchmarks.py   # correctness only
python -m unittest discover -s tests
python -m tests.benchmarks.run_all
```

**Current PR-head result (2026-10-26): 708 passed in the backend correctness suite and 74/74 end-to-end invariants verified**; the benchmark module remains outside this correctness gate.

### `test_benchmarks.py` is flaky

`BenchmarkSQL` contains three wall-clock assertions with a **50 ms budget** (`assertLess(median_ms, 50)`) for
1000-row queries. On shared or virtualised hardware these straddle the threshold — three consecutive runs measured
**36 ms, 45 ms, and 76 ms**, so the file fails intermittently regardless of the code.

These are performance targets, not correctness checks, and they will make CI non-deterministic on any machine
slower than the one they were written on. Move them behind a benchmark-only marker, or make the budget
environment-overridable, rather than letting them gate correctness.

---

## Documentation is aspirational, not descriptive

`AGENTS.md` is a **9-line auto-generated Next.js stub** that says nothing about DataOS. `CLAUDE.md` is one line:
`@AGENTS.md`. The real prose lives in `context/` — and diverges from the code substantially:

| `context/` claims | Reality |
|---|---|
| Layers are `api/ core/ db/ frontend/ workflows/ search/ agents/ plugins/` | **None of those directories exist** |
| PostgreSQL + Prisma is the core store | SQLite is the default; Prisma is entirely unused |
| Django, Celery, TensorFlow, PyTorch, mlflow, python-louvain, reportlab, openpyxl | None are imported anywhere |
| Tailwind v4 + shadcn/ui | No `components/ui/`, no shadcn; v3 and v4 configs both present and contradictory |
| "Supports DuckDB" | No DuckDB reference anywhere |
| "74 Engineering Rules" | Rules are cited by number in docstrings (`Rule #73`), but no rule list, audit, or enforcement harness exists |
| ui-context: dark mode only, `#0a0a0f`, accent `#d97757`, never `#8b5cf6`, never Inter | `globals.css` is a **light** theme, sets `--color-entity: #8b5cf6` — the explicitly banned purple — and `--font-body: "Inter"` |

`context/progress-tracker.md` is also stale by several phases: it still lists the Prisma schema and FastAPI
routes as unchecked, though both exist.

Also: `skills/` is a ~400-entry vendored library of unrelated third-party agent `SKILL.md` files. It is not part
of the product and dominates the repo's file count.

---

## Scale

~181 Python files excluding `skills/`: `core/` 22, `engines/` 35, `infrastructure/` 36, `intelligence/` 20,
`runtime/` 14, `tests/` 48, `backend/` 1, `cli/` 2.


## API pagination contract

- `GET /api/objects/` accepts `limit=1..500` and `offset=0..1,000,000`. Its `total` is the count of all active objects matching `object_type` and `source`, before page slicing.
- `GET /api/relationships/` accepts `limit=1..1,000`, `offset=0..1,000,000`, and `min_confidence=0..1`. Its `total` counts all active relationships matching the filters before page slicing. Soft-deleted relationships are excluded consistently across built-in storage backends.
- Built-in SQLite, PostgreSQL, and cloud-index backends use database-level counts. Third-party storage adapters should implement efficient count methods; the base interface provides a bounded-page fallback when listing supports offsets.



## Safe Local File Ingestion

The public ingestion pipeline treats string inputs as content, not filesystem paths. This prevents a client-supplied string from causing the server to read arbitrary local files. The scenario demo now reads its own trusted artifacts and passes their content with an explicit filename.

For controlled local-file ingestion, configure `DATAOS_INGEST_ROOT` to an existing directory owned by the service and pass a `pathlib.Path` containing only a filename (for example, `Path("report.csv")`). The pipeline resolves that filename under the configured root and rejects directory traversal, absolute paths, symlinks that resolve outside the root, and path inputs when no trusted root is configured. Do not point this setting at a home directory, repository root, or directory containing credentials.
