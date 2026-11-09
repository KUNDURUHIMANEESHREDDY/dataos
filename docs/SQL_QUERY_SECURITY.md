# SQL query execution security

## Current boundary

DataOS exposes SQL query execution against registered datasets through both the Python reference engine and the Rust backend. The engines currently use in-memory SQLite and apply read-only authorizers, query-size limits, execution deadlines and result-row limits.

Those controls are defense in depth; they do **not** make arbitrary caller-supplied SQL safe. The current main branch still passes request-controlled SQL directly to SQLite at:

- Python: `engines/compute/sql_engine.py` (CodeQL alert #32).
- Rust: `rust-backend/src/sql_engine.rs` (CodeQL alert #37).

Treat both as P0 security blockers. Do not expose these query paths to untrusted or cross-tenant callers as a production-safe capability until the compiler boundary below is implemented and verified.

## Required compiler boundary

The remediation must be implemented consistently in both runtimes:

1. Parse a documented, restricted read-only SQL grammar into an AST. Do not use keyword blacklists or regular expressions as the parser.
2. Resolve every table and column against the caller's authorized dataset/schema before compilation. An identifier must never select an object outside the principal's grants.
3. Compile only trusted, schema-resolved identifiers. Bind all literal values as parameters; never concatenate caller-controlled identifiers or values into executable SQL.
4. Apply explicit limits for query bytes, execution time, result rows and memory/output size.
5. Keep Python and Rust grammar, authorization semantics, error behavior and limits in parity.
6. Add adversarial tests for comments, quoted identifiers, aliases, joins, CTEs (if supported), nested expressions, multiple statements, DDL/DML, PRAGMA, extension/file functions, schema escape, cross-principal access and resource exhaustion.
7. Verify both CodeQL analyses on the exact candidate head and run the complete backend, Rust, PostgreSQL and frontend checks.

The accepted grammar and unsupported syntax must be documented. Unsupported syntax must fail closed with a stable client error; it must not fall back to raw SQL execution.

## CI release gate

The `SQL compiler boundary` job is a targeted regression sentinel for the two currently confirmed raw-input sinks. It intentionally fails while either known direct sink remains. `Backend required` must explicitly consume and require this job's result to be `success`; merely listing the job under `needs` is insufficient when the aggregate uses `if: always()`.

This sentinel is not a parser proof and is not a replacement for CodeQL or adversarial compiler tests. It must not be removed, bypassed or weakened to make unrelated PRs green. The compiler remediation should make it pass by removing both caller-controlled SQL sinks.

## Operational rule

Do not dismiss the existing high-severity CodeQL alerts or claim production readiness based on the SQLite authorizer alone. Keep the security-required aggregate fail-closed until both implementations satisfy the compiler boundary and exact-head verification passes.
