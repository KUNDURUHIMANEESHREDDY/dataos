# Python Reference Backend Object ACL Boundary

Status: **partial parity; not a production tenant-isolation certification**

The Rust/Axum production backend has an indexed `object_acl_grants` implementation merged in PR #70. This document describes the separate Python reference-backend enforcement added in PR #71 and, equally importantly, the routes that remain outside that boundary.

## Permission semantics

For an authenticated principal:

- The object owner can read and write.
- A principal listed in `permissions.read` can read.
- A principal listed in `permissions.write` can write but does not gain read access.
- An explicit `*` in `permissions.read` grants public read access.
- An administrator has an explicit administrative bypass.
- Missing or malformed ACL metadata is not treated as an implicit grant by the Python helper.

New objects created through the authenticated object API or ingestion routes receive:

    {
      "owner": "<authenticated-principal-id>",
      "read": ["<authenticated-principal-id>"],
      "write": ["<authenticated-principal-id>"]
    }

The same ACL is propagated to all derived objects created by notebook and rich-document ingestion, including notebook cells, extracted tables and citations. Client-supplied ACL fields are not accepted by the object-create request.

## Enforced Python routes

The current implementation applies principal checks to:

- Object list and object-get.
- Object delete and relationship creation.
- Relationship list (both endpoints must be readable).
- Hybrid and vector search (candidate IDs are scoped before returning results).
- Search context objects (unreadable context IDs are concealed with 404).
- Graph neighbors and BFS traversal (unreadable nodes are filtered before an edge is followed).
- Knowledge retrieval (selected and one-hop related objects are filtered before evidence construction).
- Object creation and all API ingestion routes (creator ACL propagation).

Unreadable direct object and selected-knowledge reads use the same 404 contract as missing objects.

## Bounded Python-reference authorization

The Python reference storage interface does not provide an indexed ACL query across every supported adapter. To avoid paginating before authorization, the helper scans in pages of 500 and caps a request at 20,000 objects. Relationship enumeration has the same 20,000-row cap.

If a non-admin authenticated request would require scanning beyond the cap, the API returns 503 with a retry hint rather than returning a partially authorized page. This is an explicit fail-closed compatibility limit, not a scalable substitute for the Rust indexed ACL implementation.

## Production identity requirement

Authenticated per-user reads and writes require a resolved user principal. If JWT authentication is configured but no session is present, the API returns 401. In production without per-user JWT configuration, object reads/writes and ingestion fail closed with 503; configure DATAOS_JWT_SECRET and use per-user sessions.

Unauthenticated local development retains the existing local behavior. That mode must not be exposed as a shared production service.

## Explicitly not covered by object-level ACLs yet

The following Python routes still need route-by-route authorization before the Python backend can be considered tenant-isolated:

- Graph analytics and aggregate graph metrics.
- Time-travel graph and global change history.
- Lineage, explain/impact and provenance surfaces that can traverse unscoped relationships.
- Recommendations and global Ask.
- Federation search.
- Graph/object export.
- SQL and Python compute over registered datasets.
- General agent/workflow execution, global conflict resolution, sharing-token operations, and global governance/profiling/quality surfaces.
- Any additional route that returns object IDs, object metadata, graph edges, embeddings or derived evidence.

### Temporary administrator-only containment

Until those handlers become principal-scoped, the Python `CapabilityMiddleware` now restricts the unscoped route families above to a resolved `admin` principal whenever JWT authentication is enabled. This includes graph analytics, time-travel graph/changes, provenance/lineage, recommendations, federation, export, Ask, SQL/Python compute, dynamic query/agent/workflow execution, vector recomputation, conflict resolution, sharing-token operations, global governance/duplicates, profiling/quality, and object `why`/`impact` views.

In production, these routes return HTTP 503 when per-user JWT authentication is not configured, even if the deployment-wide shared API bearer token is present. A shared application credential is not an administrator identity. With JWT configured, missing/invalid sessions return 401 and non-admin principals receive 403. Local development without JWT retains its existing behavior.

This is a containment measure, not a claim that the underlying routes are tenant-isolated. It deliberately limits non-admin access until each route has object-aware authorization and adversarial cross-user tests. The regression suite covers viewer denial, administrator access, production shared-token rejection, and preservation of scoped object/search/traversal routes.

The PR intentionally does not claim these routes are safe for non-admin use. They remain tracked under Issue #69.

## Legacy data and migration risk

This change does not rewrite existing object ACLs and does not perform a data migration. Historical objects may carry legacy system/public defaults. Before enabling authenticated multi-tenant access, operators must inventory existing ACLs and explicitly decide which objects remain public, which are assigned to a user, and which are restricted to administrators. Do not bulk-convert ownership without a verified mapping and backup/restore plan.

The Rust ACL migration and Python compatibility layer must be tested against the same legacy-data policy before production certification.

## Verification required for release

- Cross-user negative tests for every read and write route.
- Explicit-reader and write-only-grant tests.
- Search, graph and knowledge evidence isolation.
- Legacy ACL inventory and migration plan.
- PostgreSQL migration/rollback and backup/restore tests.
- Production deployment acceptance with per-user JWT identity.
- Zero unresolved high/critical security findings on the exact release commit.
