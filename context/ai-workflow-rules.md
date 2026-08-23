# DataOS — AI Workflow Rules

## Approach

**Spec-Driven Development** — DataOS is built incrementally using these context files that define what to build, how to build it, and the current state of progress. Always implement against these specs — do not infer or invent behavior from scratch. Every engineering rule from the 74-rule specification is represented in the installed dependency stack and must be traceable to implementation.

**Data-First Philosophy** — All analysis, computation, and AI operation grounded in actual data. Never fabricate results. All AI outputs must include claims, evidence, computations, and source references. Generated content must be clearly distinguishable from: original data, computed data, derived data, user-created data, model-generated data, and external data.

## Scoping Rules

**Work on one feature unit at a time.** DataOS features are modular and independent:

- **Feature Unit: Object Model** — Universal object structure (id, type, schema, relations, provenance, permissions, timestamps, version, source, metadata, indexes)
- **Feature Unit: Relationship Graph** — Relationship discovery, traversal, confidence scoring, provenance
- **Feature Unit: Provenance System** — Full traceability from inputs through transformations to execution context
- **Feature Unit: Computation Engine** — Pluggable engines (SQL, Python, statistical analysis)
- **Feature Unit: Query Engine** — Unified interface across files, databases, APIs, natural language
- **Feature Unit: AI Agent Layer** — Agent configurations with capability maps and permission profiles
- **Feature Unit: Workflow Engine** — trigger → conditions → actions → outputs pipelines
- **Feature Unit: Search System** — Hybrid search (full-text, metadata, semantic, graph, structured)

**Prefer small, verifiable increments over large speculative changes.** Each feature unit must work end-to-end within its defined scope before moving to the next.

**Do not combine unrelated system boundaries in a single implementation step.** Combining UI + backend + DB + AI in one step = too broad. Split by feature boundary.

**Split an implementation step if it combines:**

- [Concern one] UI implementation + backend API implementation + database schema change
- [Concern two] AI agent capability + permission model + execution trace logging
- [Concern three] Schema evolution + affected dataset impact analysis + query recompilation

**If a change cannot be verified end to end quickly, the scope is too broad — split it.**

## DataOS Feature Scoping Matrix

| Feature Unit | Dependencies | Estimated Scope | Verification Method |
|-------------|--------------|-----------------|---------------------|
| Object Model | Prisma, FastAPI, PostgreSQL | Object CRUD + schema validation | Create object → validate schema → read back → verify integrity |
| Relationship Graph | networkx, FastAPI, provenance system | Relationship discovery + traversal + confidence | Import artifacts → discover relationships → traverse graph → verify confidence scores |
| Provenance System | mlflow, celery, Prisma | Full lineage tracking + traversal | Transform data → verify provenance recorded → traverse lineage tree → verify all steps |
| Computation Engine | pandas, sqlalchemy, DuckDB | Real computation against data | Compute statistics → verify against raw data → compare results |
| Query Engine | FastAPI, unified interface | Natural language + structured queries | Query "show related objects" → verify results grounded in graph |
| AI Agent Layer | FastAPI, permission system | Agent capabilities + traces | Agent execute task → verify API calls → check execution trace completeness |
| Workflow Engine | celery, django-celery-beat | trigger→conditions→actions→outputs | Trigger data change → verify workflow executes → check outputs + provenance |
| Search System | exa-js, embeddings index | Hybrid search across types | Search "find related datasets" → verify hybrid results (full-text + metadata + semantic) |

## When to Split Work

Split an implementation step if it combines unrelated concerns:

- **Concern one** — UI changes and backend API changes (separate components/repos)
- **Concern two** — Multiple unrelated API routes (each route its own PR/implementation)
- **Concern three** — Behavior not clearly defined in context files (define scope before implementing)

**Rule of thumb:** If you cannot describe the verification method in one sentence, the scope is too broad.

## Handling Missing Requirements

- **Do not invent product behavior not defined in the context files.** If a requirement is ambiguous, resolve it in the relevant context file before implementing.
- **If a requirement is missing, add it as an open question in `progress-tracker.md` before continuing.** Do not guess — document the open question and resolve before proceeding.
- **If a requirement conflicts with an engineering rule, the engineering rule takes precedence.** All 74 engineering rules are non-negotiable.

**Example:** If a stakeholder requests "hide provenance to simplify UI," the response is: "Provenance is first-class per engineering rule #10; cannot be hidden. Instead, implement progressive disclosure in UI."

## Protected Files

**Do not modify the following unless explicitly instructed (or resolving a rule violation):**

- **`prisma/schema.prisma`** — Universal object model schema; migration strategy; never modify without updating all dependent components
- **`fastapi` route files** — API endpoints for object CRUD, graph queries, provenance tracking; never modify without updating contracts
- **`tailwind.config.js`** — Design system configuration (Geist/Outfit/Satoshi fonts, design dials); never mix v3/v4 syntax
- **`package.json`** — Dependency manifest; never add packages without reviewing engineering rule coverage
- **`context/` folder** — All context markdown files; these define what to build, changing them changes the spec
- **`tailwind.config.js` quality gates** — Design, motion, and general checklists; STOP if any quality gate fails before delivering

**Files that CAN be modified during implementation:**

- Any new files added to support a feature unit
- API route additions (not modifications to existing endpoints without review)
- Component additions to `components/ui/`
- Test files and verification scripts
- Documentation updates that maintain spec alignment

## Keeping Docs in Sync

**Update the relevant context file whenever implementation changes:**

- System architecture or boundaries (add/remove system boundaries)
- Storage model decisions (change database schema, add storage type)
- Code conventions or standards (update if new pattern adopted)
- Feature scope (add removed feature units from scoping matrix)
- Engineering rule coverage (add new rule mappings as skills installed)

**Never modify context files to match incomplete implementation.** If implementation cannot meet a spec requirement, document as open question in `progress-tracker.md` and resolve before proceeding.

**Version correlation:** Context file version should correlate with Prisma schema version and FastAPI version. Track in `progress-tracker.md`.

## Before Moving to the Next Feature Unit

**All of the following must be true before moving forward:**

1. **The current feature unit works end to end within its defined scope.** Verified via integration test or manual validation.
2. **No invariant defined in `architecture.md` was violated.** Check: never fabricate data, always preserve lineage, maintain transparency, ensure reproducibility, support portability, domain neutrality, provenance first-class, graph consistency, schema version BWC, AI answer grounding.
3. **`progress-tracker.md` reflects the completed work.** Current goal checked off; next up identified; open questions documented.
4. **`npm run build` passes** (frontend) **and** `python -m pytest tests/` passes (backend) **with zero failures.**
5. **All new dependencies added have engineering rule coverage documented.** Each new package/skill maps to at least one DataOS engineering rule.
6. **Provenance tracking is functional for the feature unit.** End-to-end test: create → transform → query → verify provenance at each step.

**If any of the above is false, do not move to the next feature unit.** Resolve outstanding issues, document in `progress-tracker.md`, and re-verify.

## DataOS AI Workflow Non-Negotiables

| Rule | Description | Enforcement |
|------|-------------|-------------|
| **No Fabricated Results** | All computation against real data; zero fabricated outputs | Automated test: compute statistic on subset → compare to full; must match |
| **Provenance First-Class** | Every derived result fully traceable | Automated test: trace provenance from final result to all root inputs |
| **AI Not Authoritative** | AI is operator, not truth source | Policy: all AI outputs include grounding (claims + evidence + computations + sources) |
| **Deterministic Computation** | Arithmetic, statistics, SQL, Python all verifiable | Automated test: run computation twice → results identical (same data, same version) |
| **Domain Neutrality** | No hardcoded workflows | Audit: verify no student/analyst/researcher/business workflows in core |
| **Provenance Visibility** | Never hidden or silently dropped | Automated test: delete provenance field → system rejects or marks incomplete |
| **Reproducible Analysis** | Inputs, code, environment, data versions | Automated test: reproduce analysis from saved state → results match |
| **Permission-Controlled AI** | All agent actions API-gated | Automated test: agent attempts unauthorized action → denied + logged |
| **Evidence Grounding** | Claims grounded to files/rows/cells/timestamps/code | Automated test: extract claim → verify evidence source exists and matches |
| **Caching Dependency-Aware** | Cache invalidates on dependency change | Automated test: modify parent object → cache invalidated → fresh results on re-query |