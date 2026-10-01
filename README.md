# DataOS — Universal Data Operating System

A graph-based, computable data system that turns fragmented information into a connected, explainable, reproducible knowledge infrastructure for humans and AI agents.

> **Status: active development.** Core object model, graph, provenance, and permission layers are the most complete. The agent layer and UI are earlier. Architecture notes in [`context/`](context/).

---

## The problem

Information fragments. A dataset, a paper, a notebook, a video, a schema — they live apart, and nothing records where any of it came from or how it connects to the rest. Six months later you can't answer "which files support this analysis?"

Chat assistants don't solve this. They summarise text that was already disconnected, and they hallucinate the connective tissue. DataOS takes the opposite position: **everything becomes an object in a persistent graph, and every derived result is traceable to the real source it came from.**

---

## Philosophy

Built on 74 engineering rules. The load-bearing ones:

- **Data is the source of truth.** LLM output is never treated as factual data — it is a derived artefact, always.
- **Everything is an object.** Every meaningful entity conforms to a universal structure: id, type, schema, relations, provenance, permissions, timestamps, version, source, metadata, indexes.
- **AI is an operator, not an authority.** It can query, analyse, transform, summarise, classify, connect, reason, generate, and automate — through DataOS APIs with controlled capabilities. It is never the source of truth.
- **Computation is deterministic and verifiable**, executed against real data sources only.
- **Provenance is first-class.** Every derived result must trace back through its inputs, transformations, and execution context.
- **Domain neutrality.** The core contains no domain-specific logic. No hardcoded analyst, researcher, or business workflows — specialised workflows emerge from primitives.

---

## The core loop

```
INGEST → UNDERSTAND → STRUCTURE → CONNECT → QUERY → COMPUTE
   ↑                                                    ↓
  REPEAT ← RECORD PROVENANCE ← ACT ← TRANSFORM ← REASON
```

Each pass through the loop grows the graph's value.

---

## Architecture

| Layer | Directory | Responsibility |
|---|---|---|
| **Object Model** | `core/object` | Universal entity structure, schema validation |
| **Relationships** | `core/relation` | First-class graph — source, target, relation type, confidence, provenance |
| **Provenance** | `core/provenance` | Full lineage: inputs → transformations → execution context |
| **Versioning** | `core/versioning` | Entity history and diffing |
| **Permissions** | `core/permissions` | Capability-scoped access control |
| **Governance** | `core/governance` | Policy enforcement across the system |
| **Schema** | `core/schema` | Schema registry and contracts |

### Engines

`engines/` — pluggable computation backends, each independently swappable:

| Engine | Purpose |
|---|---|
| `query` | Unified querying across files, DBs, APIs, warehouses |
| `search` | Semantic and structured retrieval |
| `graph` | Graph traversal and relationship resolution |
| `compute` | SQL, Python, and DataFrame execution |
| `diff` | Structural and semantic change detection between versions |
| `provenance` | Lineage resolution and replay |
| `quality` | Data quality checks |
| `profiling` | Statistical profiling and automatic insight generation |
| `catalog` | Object catalogue and discovery |
| `actions` | Controlled side-effects, permission-gated |
| `governance` | Policy evaluation |
| `usage` | Cost and usage accounting |

### Intelligence

`intelligence/` — semantic indexing, knowledge graph construction, dataset and document understanding, code analysis, and cross-source discovery. Automatic relationship finding via structural matching, semantic matching, content analysis, and code/git analysis.

### Infrastructure

`infrastructure/` — storage, caching, connectors, federation, sync, observability, privacy, plugins, I/O.

### Runtime

`runtime/` — agent execution, event system, grounding, pipelines, workflows.

---

## Quick start

```bash
git clone https://github.com/KUNDURUHIMANEESHREDDY/dataos.git
cd dataos

npm install
npm run dev        # Next.js on http://localhost:3000

python scenario_demo.py   # end-to-end walkthrough
```

Python backend packages live under `core/`, `engines/`, `intelligence/`, `infrastructure/`, and `runtime/`. See [`context/architecture.md`](context/architecture.md) for the full breakdown.

---

## Stack

**Frontend:** Next.js 16, React 19, TypeScript, Tailwind CSS 4
**3D / visualisation:** React Three Fiber, Drei, GSAP, Framer Motion, Lottie
**Backend:** Python (FastAPI, SQLAlchemy), Node/TypeScript API layer
**Data:** PostgreSQL, Prisma, pgvector
**Integrations:** Exa

---

## Layout

```
core/              object model, relations, provenance, permissions, governance
engines/           pluggable computation, query, search, graph, diff backends
intelligence/      semantic indexing, knowledge graphs, discovery
infrastructure/    storage, caching, connectors, federation, observability
runtime/           agent execution, events, grounding, workflows
backend/           API services
cli/               command line interface
context/           architecture, standards, project overview, progress
skills/            400 bundled agent skill definitions
tests/             test suite
```

---

## A note on `skills/`

This directory contains ~400 bundled agent skill definitions (34MB) vendored as a runtime resource for the agent layer. **It is not authored as part of DataOS** and dominates repository weight. It is a candidate for extraction into a separate package or submodule — tracked here because DataOS ships them as a bundle.

---

## License

MIT — see [`LICENSE`](LICENSE).