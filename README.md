# DataOS

A Python data platform built around three ideas: a **universal object model**, a **first-class relationship
graph**, and **first-class provenance** — every derived result traceable back to its real source.

The design principle, stated in `context/ai-workflow-rules.md`: **AI is an operator over the graph, never an
authority over it.**

> ⚠️ **The library is real. Everything above it is unfinished.** ~180 Python files, 12 engine packages, and ~670
> unit tests form a coherent, substantial core. The package imports cleanly and **653 correctness tests pass**.
> However, the FastAPI layer calls an API that no longer exists, and the CLI and demo script do not run. See
> [Current blockers](#current-blockers).

---

## Current blockers

### ✅ Resolved

Two bugs that made the package unusable were fixed in `dab962b`:

- **`import dataos_system` failed with `NameError: name 'Union' is not defined`.** `core/permissions/policy.py:7`
  imported from `typing` without `Union`, which lines 56 and 61 used in eagerly-evaluated annotations. Because
  `core/__init__.py:11` imports that module, this took down the kernel, backend, CLI, demo, and every test.
- **`ActionResult.execution_time_ms` measured as `0.0`.** `engines/actions/registry.py` used `time.time()`, whose
  clock granularity on Windows is ~16 ms, so any fast action timed as zero. Now uses `time.perf_counter()`.

### Still open

#### 1. The FastAPI backend targets an API that no longer exists

`backend/app.py` makes 52 `dataos.*` attribute accesses; only about 13 resolve. **Roughly 22 of ~35 endpoints
return HTTP 500.** It was written against an older, richer `DataOS` and never updated.

Broken calls include `dataos.execute_sql` (the real name is `DataOS.sql`), `dataos.execute_python` (`.python`),
`dataos.ingest_file`, `dataos.get_object`, `dataos.graph.traverse` (`GraphNamespace` has no `traverse`),
`dataos.create_agent`, `dataos.get_system_health`, `dataos.run_multi_agent_pipeline`, and
`dataos.query.execute_query` (where `dataos.query` is actually a bound method, not a namespace).

Working endpoints: `/api/objects` CRUD, `/api/relationships`, `/api/vectors/search`,
`/api/provenance/lineage/{id}`, `/api/profiling/{id}`, `/api/quality/{id}`, `/api/objects/{id}/why`,
`/api/objects/{id}/impact`, `/api/ask`, `/api/ingest/universal`, `/api/io/export`, `/health`.

#### 2. `scenario_demo.py` cannot run

It calls six methods that do not exist on `DataOS` — `ingest_file`, `get_object`, `execute_sql`,
`traverse_graph`, `graph_analytics`, `get_system_health` — and dies at line 83. It also passes `onexc=` to
`shutil.rmtree`, which requires Python 3.12+.

#### 3. The CLI is 4/4 broken

All four subcommands call the same nonexistent methods. There is also **no `pyproject.toml`, `setup.py`, or
`requirements.txt`** — the project is not installable.

#### 4. `npm install` will fail

`package.json` declares versions that were never published:

```json
"django": "^99.99.99",
"fastapi": "^0.0.8",
"uvicorn": "^0.0.1-security"
```

These are Python packages listed as npm dependencies. There is no `@prisma/client`, and Prisma — despite a
224-line `prisma/schema.prisma` — is **entirely unused**: nothing in `src/` imports it, there are no Prisma
scripts, and the schema's `datasource` has no `url`.

---

## Quick start

No dependency manifest exists. Install what the import path needs:

```bash
pip install pandas numpy scipy scikit-learn networkx fastapi uvicorn
```

```bash
# The Union import bug is fixed — the kernel now imports cleanly.
python -m pytest tests/          # the gate: must pass with zero failures
python scenario_demo.py          # currently broken, see Current blockers
```

### Library

```python
from dataos_system import DataOS

d = DataOS(db_path="dataos.db")
obj = d.ingest("data.csv")
d.why(obj.id)       # why does this exist?
d.impact(obj.id)    # what breaks if this changes?
d.ask("which majors have the highest average GPA?")
d.sql("SELECT major, AVG(gpa) FROM objects GROUP BY major")
d.search("query text")
```

Convenience methods that genuinely exist: `from_url`, `ingest`, `why`, `impact`, `ask`, `sql`, `python`,
`search`, `search_vector`, `profile`, `embed`, `embed_batch`, `classify`, `ingest_source`, `export_data`, `mask`,
`check_rate_limit`, `close`.

### Backend

```bash
python -m uvicorn backend.app:app --reload    # port 8000, must run from repo root
```

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

**6 of the 12 are not reachable from the kernel or the API.** `dataos_system.py` imports only 11 engine classes;
`catalog`, `diff`, `usage`, `actions`, and `governance` are fully implemented and tested but never wired in.

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

There is exactly **one environment variable** in the product: `DATAOS_MASTER_KEY`
(`infrastructure/privacy/encryption.py:54`).

Everything else is a constructor argument: `db_path="dataos.db"`, `blob_dir=".dataos_blobs"`, and
`PostgresStorage`'s connection string (hardcoded default, no `DATABASE_URL` lookup).

**No external service is required.** SQLite is the default. Postgres, S3, GCS, and Azure are optional and
degrade gracefully — notably, `PostgresStorage` **silently falls back to an in-memory SQLite** if `psycopg2`
fails to connect (`postgres_store.py:31-41`), which means a misconfigured Postgres looks like a working one.

**By default no LLM is wired in.** `MultiAgentPipeline` defaults to `MockDeterministicProvider`, a
string-templating stub. Embeddings default to `HashEmbeddingProvider(dimension=128)` — a feature hash, not a
model.

---

## Storage and contract issues

`PostgresStorage` has drifted from `SQLiteStorage`: `delete_object()` lacks the `soft` kwarg and `list_objects()`
lacks `source`. The backend passes both, so those routes raise `TypeError` under Postgres — while
`tests/test_storage_backends.py` asserts backend parity **only against mock mode**, so the tests miss it.

The frontend reads `r.source_id` / `r.target_id` from relationship JSON, but `Relationship.to_dict()` emits
`source` / `target`. Every graph edge renders as `undefined`.

CORS is `allow_origins=["*"]` with `allow_credentials=True`, and no endpoint has auth despite `Depends` being
imported.

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

**Current result: 653 passed** excluding `tests/test_benchmarks.py`, which is a separate matter.

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
