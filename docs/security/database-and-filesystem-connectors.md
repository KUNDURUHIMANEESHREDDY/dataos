# Database and filesystem connector security

## Database connector

Database resource reads resolve a caller-supplied resource ID against the database catalog before constructing a quoted identifier. Table names are never accepted as raw SQL fragments. PostgreSQL schema filters are bound as query parameters, and row limits are bounded.

When `read_only=true`, the connector applies database-enforced read-only behavior:
- SQLite uses a fail-closed authorizer that permits only SELECT/READ/function/recursive actions and denies ATTACH, DDL, DML, PRAGMA, transaction control, and extension/file functions.
- PostgreSQL uses read-only transactions.
- MySQL sets the session's default transaction access mode to READ ONLY.

The keyword check in `execute_query` is an early error message only; it is not the security boundary.

## Filesystem connector

Resource IDs are relative paths beneath the configured root. Absolute paths, parent traversal, symlink components, and resolved paths outside the root are rejected. Directory listings omit symlinks and remain bounded.

## Universal ingestion

String inputs are content, never implicit filesystem paths. PathLike ingestion requires an explicit existing `DATAOS_INGEST_ROOT` (or constructor-supplied root) and accepts only a basename directly within that root.

Run the focused regressions with:

```sh
python -m pytest tests/test_connector_security.py tests/test_universal_ingestion_security.py tests/test_connector_system.py -q
```
