# Object ACL contract

The Rust/Axum backend stores the complete permission document on each object. The JSON `permissions` value is authoritative; `object_acl_grants` is a normalized, indexed lookup structure maintained in the same SQLite transaction as the object and version record.

## Read and write semantics

- The object owner can read and write.
- A principal listed in `permissions.read` can read.
- `permissions.read: ["*"]` grants public read.
- A principal listed in `permissions.write` can write, but a write grant does **not** imply read.
- The administrator bypass is explicit and still requires the object to exist.
- Missing, malformed, or non-array grant lists produce no grants. They never widen access.
- A wildcard write grant is ignored.

## Enforced Rust routes in this change

- Object GET and object listing apply read ACLs before returning content or pagination totals.
- Text search uses the authenticated principal's readable-object set.
- SQL dataset registration uses the authenticated principal's readable-object set.
- Object-addressed graph/lineage checks and relationship visibility use read access. Relationship lists now apply indexed endpoint ACL predicates in SQL before pagination and counting, rather than loading a large global page and issuing per-row authorization queries.
- Relationship creation and object deletion require write access in addition to role capabilities.

The ACL index has indexes for principal/permission/object lookup and object/permission/principal lookup. Existing permission arrays are backfilled once by additive schema migration version 1. Object records are not rewritten by the backfill. Subsequent object writes replace the object's index rows atomically with the object and version update.

## Deliberately restricted operations

Vector search, graph-wide analytics, export, federation, and other aggregate endpoints that do not yet apply the same principal filter remain administrator-only in production. This change does not claim that every Python reference-backend route or every Rust route has completed resource-level authorization. Track remaining routes and parity in [Issue #69](https://github.com/KUNDURUHIMANEESHREDDY/dataos/issues/69).

## Migration and rollback

The migration is additive: it creates the ACL grant index, its indexes, and a schema-version marker, then copies existing JSON grant entries into the index. It does not delete or rewrite object content, provenance, versions, or permissions. Back up the SQLite database before upgrading as for any schema change. A code rollback to a revision that does not read `object_acl_grants` is safe; the extra tables may be left in place. Do not drop them while this code is running.
