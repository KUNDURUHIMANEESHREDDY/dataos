"""Consistent /api authorization boundary for DataOS.

The shared production bearer token is a deployment gate, not a per-user
boundary. When DATAOS_JWT_SECRET is configured, every /api request is mapped
to the minimum Capability required for the method and path. Routes that cannot
be safely represented statically, such as /api/query/, opt out here and perform
dynamic capability enforcement in the handler.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from starlette.types import ASGIApp, Receive, Scope, Send

from core.permissions.auth import UserStore, decode_jwt, jwt_configured
from core.permissions.policy import Capability

PUBLIC_ALLOWLIST = {
    ("POST", "/api/auth/register"),
    ("POST", "/api/auth/login"),
    ("GET", "/api/auth/me"),
    ("GET", "/api/auth/users"),  # role enforcement remains in the handler (admin only)
}

# Route families where the required capability differs by body/payload.
DYNAMIC_REVIEW = {
    ("POST", "/api/query/"),
    ("POST", "/api/agents/execute"),
}

_user_store: Optional[UserStore] = None


def _get_user_store() -> UserStore:
    global _user_store
    if _user_store is None:
        _user_store = UserStore(db_path=os.getenv("DATAOS_DB_PATH", "dataos.db"))
    return _user_store


def get_user_store() -> UserStore:
    """Return the process-wide user store shared by routes and middleware."""
    return _get_user_store()


def _matches(path: str, prefix: str) -> bool:
    normalized = prefix if prefix.endswith("/") else prefix + "/"
    return path == prefix.rstrip("/") or path == prefix or path.startswith(normalized)


def capability_for_api_request(method: str, path: str) -> Optional[str]:
    """Return the minimum Capability required, or None when no gating applies."""
    method = method.upper()
    if method == "OPTIONS":
        return None
    if (method, path) in PUBLIC_ALLOWLIST:
        return None
    if (method, path) in DYNAMIC_REVIEW:
        return None

    # High-risk execution routes.
    if method == "POST" and path == "/api/compute/python":
        return Capability.COMPUTE_PYTHON.value
    if method == "POST" and path == "/api/compute/sql":
        return Capability.QUERY_SQL.value
    if method == "POST" and path == "/api/python":
        return Capability.COMPUTE_PYTHON.value
    if method == "POST" and path == "/api/workflows/execute":
        return Capability.EXECUTE_WORKFLOW.value
    if method == "POST" and path == "/api/vectors/recompute":
        return Capability.TRANSFORM_DATA.value
    if method == "POST" and path.startswith("/api/agents/pipeline/"):
        return Capability.EXECUTE_WORKFLOW.value
    if method == "POST" and path == "/api/federation/search":
        return Capability.SEARCH.value

    # Mutation routes.
    if method == "POST" and path in {"/api/objects", "/api/objects/"}:
        return Capability.CREATE_OBJECT.value
    if method == "POST" and (path.startswith("/api/io/ingest") or path == "/api/ingest/universal" or path == "/api/ingest"):
        return Capability.CREATE_OBJECT.value
    if method == "POST" and path == "/api/notebooks/ingest":
        return Capability.CREATE_OBJECT.value
    if method == "POST" and path == "/api/documents/extract_rich":
        return Capability.EXTRACT_KNOWLEDGE.value
    if method == "POST" and (path == "/api/relationships" or path == "/api/relationships/"):
        return Capability.CREATE_RELATION.value
    if method == "POST" and path == "/api/sync/resolve_conflict":
        return Capability.UPDATE_OBJECT.value
    if method == "POST" and path.startswith("/api/quality/"):
        return Capability.UPDATE_OBJECT.value
    if method == "POST" and path.startswith("/api/knowledge/query"):
        return Capability.EXTRACT_KNOWLEDGE.value
    if method == "POST" and path == "/api/sharing/issue_token":
        return Capability.CALL_CONNECTOR.value
    if method == "POST" and path == "/api/sharing/verify_token":
        return Capability.READ_OBJECT.value
    if method == "POST":
        # Unknown /api write: require an explicit update capability rather than defaulting open.
        return Capability.UPDATE_OBJECT.value

    if method == "DELETE":
        if path.startswith("/api/objects/"):
            return Capability.DELETE_OBJECT.value
        if path.startswith("/api/relationships/"):
            return Capability.DELETE_RELATION.value
        return Capability.DELETE_OBJECT.value

    if method in {"PUT", "PATCH"}:
        return Capability.UPDATE_OBJECT.value

    if method == "GET":
        if _matches(path, "/api/io/export"):
            return Capability.EXPORT_DATA.value
        if (
            _matches(path, "/api/search/")
            or _matches(path, "/api/vectors/search")
            or _matches(path, "/api/ask")
            or _matches(path, "/api/federation/search")
            or _matches(path, "/api/recommendations/")
            or _matches(path, "/api/governance/duplicates")
        ):
            return Capability.SEARCH.value
        return Capability.READ_OBJECT.value

    return None


async def _error_response(send: Send, status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode("utf-8")
    headers = [(b"content-type", b"application/json")]
    if status == 401:
        headers.append((b"www-authenticate", b"Bearer"))
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": headers,
        }
    )
    await send({"type": "http.response.body", "body": body})


class CapabilityMiddleware:
    """Pure-ASGI per-user capability enforcement for JWT-configured deployments.

    When DATAOS_JWT_SECRET is unset, the middleware is deliberately a no-op so
    existing local development and tests retain current behavior. The separate
    production shared-bearer dependency still fails closed for /api routes.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not path.startswith("/api/"):
            await self.app(scope, receive, send)
            return

        capability = capability_for_api_request(scope.get("method", "GET"), path)
        if capability is None or not jwt_configured():
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        authorization = headers.get("authorization", "")
        token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
        if not token:
            # Browser clients use the HttpOnly session cookie; non-browser clients
            # may continue to send an explicit Bearer token.
            for part in headers.get("cookie", "").split(";"):
                name, separator, value = part.strip().partition("=")
                if separator and name == "dataos_session":
                    token = value.strip()
                    break
        if not token:
            await _error_response(send, 401, "A bearer token or session cookie is required.")
            return
        try:
            payload = decode_jwt(token)
            user = _get_user_store().get_by_id(payload.get("sub", ""))
        except (ValueError, RuntimeError) as exc:
            await _error_response(send, 401, str(exc))
            return
        except Exception:
            await _error_response(send, 401, "Unable to resolve the authenticated user.")
            return
        if user is None:
            await _error_response(send, 401, "Unknown user.")
            return
        if not user.has_capability(capability):
            await _error_response(send, 403, f"Capability '{capability}' is not permitted for role '{user.role}'.")
            return
        await self.app(scope, receive, send)
