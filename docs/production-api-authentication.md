# Production API authentication boundary

## Current backend contract

When any supported environment marker (DATAOS_ENV, APP_ENV, or ENVIRONMENT) is set to
production or prod, the FastAPI application requires a bearer credential on every
/api/* request. The credential is read from the server-side DATAOS_API_TOKEN environment
variable and must contain at least 32 UTF-8 bytes without surrounding whitespace.

The health route outside /api/* is intentionally not covered by this dependency. It is
a liveness endpoint, not proof that the API is ready to serve authenticated user requests.

## Browser security boundary

DATAOS_API_TOKEN is a service credential. It must remain in a server-side secret store
and must never be copied into:

- NEXT_PUBLIC_* or VITE_* environment variables;
- browser JavaScript, source maps, HTML, or client-visible configuration;
- URLs, query strings, browser storage, or client-side logs.

A browser request must not receive the shared service credential.

The current main-branch browser API client uses same-origin fetch without a bearer token,
and the repository does not currently contain a Next.js src/app/api/* BFF route. Therefore,
a production deployment must not assume that the browser-to-FastAPI path is complete.
An external ingress could inject the service credential server-side, but that deployment
contract must be explicitly configured and verified; it is not established by this repository source.

## Required production architecture

Before enabling the production browser journey, implement and verify one of:

1. An authenticated server-side BFF/session boundary that keeps the service credential
   on the server and enforces per-user authorization; or
2. A documented, tested server-side ingress that injects the service credential without
   exposing it to the browser, together with a separate user identity and resource-authorization boundary.

A shared service token alone is not user authentication, RBAC, or tenant isolation.
Do not use it as a substitute for those controls.

## Acceptance checklist

- [ ] The service token is sourced only from a server-side secret manager.
- [ ] No client bundle, source map, HTML response, or browser storage contains the service token.
- [ ] Browser requests authenticate to a BFF/session boundary, not with the service token.
- [ ] The BFF/ingress validates the user session and authorizes each resource.
- [ ] Cross-tenant object and relationship access is denied.
- [ ] Missing/invalid server credentials fail closed with actionable server diagnostics that do not disclose the credential.
- [ ] Browser-to-BFF-to-FastAPI integration tests cover success, expiry, unauthorized resources, and service-token misconfiguration.
- [ ] A deployed smoke test confirms the same contract in the actual production ingress configuration.

The source-level regression test in tests/test_browser_service_credential_boundary.py prevents
the known service-token environment variable names from being introduced into browser-bundled
source. It is a guardrail, not a replacement for the BFF, user authentication, or deployed acceptance tests.
