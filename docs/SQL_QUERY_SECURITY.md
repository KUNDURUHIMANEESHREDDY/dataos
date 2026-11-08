# SQL query execution security

**Status: defense in depth; the parser-backed SQL compiler is still outstanding.**

DataOS registers only the dataset tables available to the current execution context, then enables SQLite query-only mode, a deny-by-default authorizer for database mutations, a query deadline, and a result-row limit. The Python reference engine and Rust/Axum engine now also share an explicit SQLite function allowlist.

## Shared policy manifest

Both engines load `security/sqlite_allowed_functions.txt` as the single source of truth. The Python and Rust tests verify that the manifest is sorted, unique, and consumed by the reference engine; the Rust engine embeds the same file at compile time. Add or remove a function only through this manifest and review its SQLite capability and determinism before changing it.

## Allowed function families

The allowlist currently includes reviewed aggregate, scalar, window, date/time, pattern-matching, and JSON functions:

- Aggregates: `avg`, `count`, `group_concat`, `max`, `min`, `sum`, `total`.
- Scalar/text: `abs`, `coalesce`, `ifnull`, `instr`, `length`, `lower`, `ltrim`, `nullif`, `replace`, `round`, `rtrim`, `substr`, `trim`, `typeof`, `upper`.
- Window: `dense_rank`, `first_value`, `lag`, `last_value`, `lead`, `nth_value`, `ntile`, `percent_rank`, `rank`, `row_number`.
- Date/time: `date`, `datetime`, `julianday`, `strftime`, `time`, `unixepoch`.
- Pattern matching: `glob`, `like`.
- JSON: `json`, `json_array`, `json_array_length`, `json_extract`, `json_insert`, `json_object`, `json_patch`, `json_quote`, `json_remove`, `json_replace`, `json_set`, `json_type`, `json_valid`, `json_group_array`, `json_group_object`.

Any SQLite function outside this list is denied by the authorizer in both runtimes. The lists must remain identical; update the parity tests whenever a function is added or removed.

## Explicit release limitation

This allowlist does **not** replace parsing or query compilation. The current API still accepts SQL text and passes it to SQLite's parser. It therefore does not satisfy the parser-backed, principal/schema-aware query compiler acceptance criteria in [issue #75](https://github.com/KUNDURUHIMANEESHREDDY/dataos/issues/75), and it does not by itself resolve CodeQL findings #32 and #37. Do not close #75, dismiss either alert, or certify SQL execution as production-safe on the basis of this change.

The required follow-up is a restricted AST/query-plan parser that resolves table and column identifiers against the principal's readable schemas, compiles only trusted identifiers, binds literal values as parameters, and has equivalent Python/Rust behavior with adversarial regression coverage.
