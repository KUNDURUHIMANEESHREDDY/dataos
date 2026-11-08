"""Contract tests for the JWT-configured /api authorization boundary."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException, Request

import backend.authorization as authorization
from backend.app import get_current_user, require_production_api_token
from core.permissions.auth import UserStore, issue_jwt
from core.permissions.policy import Role


def _request(path: str, method: str = "GET", authorization_header: str | None = None, cookie: str | None = None) -> Request:
    headers = []
    if authorization_header is not None:
        headers.append((b"authorization", authorization_header.encode("utf-8")))
    if cookie is not None:
        headers.append((b"cookie", cookie.encode("latin-1")))
    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "headers": headers,
        "client": ("testclient", 12345),
        "server": ("testserver", 80),
    })


def test_capability_mapping_covers_sensitive_routes():
    assert authorization.capability_for_api_request("POST", "/api/compute/python") == "compute_python"
    assert authorization.capability_for_api_request("POST", "/api/compute/sql") == "query_sql"
    assert authorization.capability_for_api_request("POST", "/api/objects/") == "create_object"
    assert authorization.capability_for_api_request("DELETE", "/api/objects/123") == "delete_object"
    assert authorization.capability_for_api_request("POST", "/api/query/") is None  # enforcement is dynamic
    assert authorization.capability_for_api_request("OPTIONS", "/api/objects/") is None


def test_production_requires_at_least_one_auth_boundary(monkeypatch):
    monkeypatch.setenv("DATAOS_ENV", "production")
    monkeypatch.delenv("DATAOS_API_TOKEN", raising=False)
    monkeypatch.delenv("DATAOS_JWT_SECRET", raising=False)
    with pytest.raises(HTTPException) as exc:
        require_production_api_token(_request("/api/objects/"))
    assert exc.value.status_code == 503


def test_production_accepts_valid_user_jwt(monkeypatch):
    monkeypatch.setenv("DATAOS_ENV", "production")
    monkeypatch.delenv("DATAOS_API_TOKEN", raising=False)
    monkeypatch.setenv("DATAOS_JWT_SECRET", "j" * 48)
    token = issue_jwt("user-1", Role.VIEWER.value)
    assert require_production_api_token(_request("/api/objects/"), authorization=f"Bearer {token}") is None


def test_production_accepts_login_and_registration_before_authentication(monkeypatch):
    monkeypatch.setenv("DATAOS_ENV", "production")
    monkeypatch.delenv("DATAOS_API_TOKEN", raising=False)
    monkeypatch.delenv("DATAOS_JWT_SECRET", raising=False)
    assert require_production_api_token(_request("/api/auth/login", "POST")) is None
    assert require_production_api_token(_request("/api/auth/register", "POST")) is None


def test_production_accepts_a_valid_jwt_session_cookie(monkeypatch):
    monkeypatch.setenv("DATAOS_ENV", "production")
    monkeypatch.delenv("DATAOS_API_TOKEN", raising=False)
    monkeypatch.setenv("DATAOS_JWT_SECRET", "c" * 48)
    token = issue_jwt("cookie-user", Role.VIEWER.value)
    request = _request("/api/objects/", cookie=f"dataos_session={token}")
    assert require_production_api_token(request) is None


def test_get_current_user_defaults_missing_header_to_none(monkeypatch):
    monkeypatch.setenv("DATAOS_JWT_SECRET", "u" * 48)
    assert asyncio.run(get_current_user(_request("/api/objects/"))) is None


def test_production_rejects_missing_user_session_when_jwt_is_configured(monkeypatch):
    monkeypatch.setenv("DATAOS_ENV", "production")
    monkeypatch.delenv("DATAOS_API_TOKEN", raising=False)
    monkeypatch.setenv("DATAOS_JWT_SECRET", "j" * 48)
    with pytest.raises(HTTPException) as exc:
        require_production_api_token(_request("/api/objects/"))
    assert exc.value.status_code == 401


def _asgi_status(method: str, path: str, headers: dict | None = None):
    messages = []
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [(k.encode("latin-1"), v.encode("latin-1")) for k, v in (headers or {}).items()],
    }

    async def receive():
        return {"type": "http.request", "body": b""}

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def send(message):
        messages.append(message)

    async def run_middleware():
        await authorization.CapabilityMiddleware(app)(scope, receive, send)

    asyncio.run(run_middleware())
    return next(m["status"] for m in messages if m["type"] == "http.response.start")


def test_jwt_middleware_accepts_httponly_session_cookie(monkeypatch, tmp_path):
    monkeypatch.setenv("DATAOS_JWT_SECRET", "s" * 48)
    store = UserStore(db_path=str(tmp_path / "cookie-auth.db"))
    try:
        user = store.register("cookie-viewer", "cookie-viewer@example.com", "password123", role=Role.VIEWER.value)
        token = issue_jwt(user.id, user.role)
        monkeypatch.setattr(authorization, "_user_store", store)
        cookie_headers = {"cookie": f"dataos_session={token}"}
        assert _asgi_status("GET", "/api/objects/", cookie_headers) == 204
        assert _asgi_status("POST", "/api/objects/", cookie_headers) == 403
        assert _asgi_status("GET", "/api/objects/") == 401
    finally:
        store.close()


def test_jwt_middleware_enforces_role_capabilities(monkeypatch, tmp_path):
    monkeypatch.setenv("DATAOS_JWT_SECRET", "s" * 48)
    store = UserStore(db_path=str(tmp_path / "auth.db"))
    try:
        user = store.register("viewer", "viewer@example.com", "password123", role=Role.VIEWER.value)
        token = issue_jwt(user.id, user.role)
        monkeypatch.setattr(authorization, "_user_store", store)
        headers = {"authorization": f"Bearer {token}"}
        assert _asgi_status("GET", "/api/objects/", headers) == 204
        assert _asgi_status("POST", "/api/objects/", headers) == 403
        assert _asgi_status("POST", "/api/compute/python", headers) == 403
        assert _asgi_status("POST", "/api/compute/sql", headers) == 403
    finally:
        store.close()


def test_unscoped_data_routes_are_admin_only_when_jwt_is_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("DATAOS_JWT_SECRET", "a" * 48)
    store = UserStore(db_path=str(tmp_path / "unscoped-auth.db"))
    try:
        viewer = store.register("unscoped-viewer", "unscoped-viewer@example.com", "password123", role=Role.VIEWER.value)
        admin = store.register("unscoped-admin", "unscoped-admin@example.com", "password123", role=Role.ADMIN.value)
        monkeypatch.setattr(authorization, "_user_store", store)
        viewer_headers = {"authorization": f"Bearer {issue_jwt(viewer.id, viewer.role)}"}
        admin_headers = {"authorization": f"Bearer {issue_jwt(admin.id, admin.role)}"}
        routes = (
            ("GET", "/api/graph/analytics"),
            ("GET", "/api/time_travel/graph"),
            ("GET", "/api/time_travel/changes"),
            ("GET", "/api/provenance/lineage/object-1"),
            ("GET", "/api/recommendations/datasets"),
            ("GET", "/api/federation/search"),
            ("GET", "/api/io/export"),
            ("POST", "/api/ask"),
            ("POST", "/api/compute/sql"),
            ("POST", "/api/compute/python"),
            ("POST", "/api/query/"),
            ("POST", "/api/agents/execute"),
            ("POST", "/api/workflows/execute"),
            ("POST", "/api/vectors/recompute"),
            ("POST", "/api/sync/resolve_conflict"),
            ("POST", "/api/sharing/issue_token"),
            ("GET", "/api/governance/duplicates"),
            ("GET", "/api/objects/object-1/why"),
            ("GET", "/api/objects/object-1/impact"),
        )
        for method, path in routes:
            assert authorization.is_admin_only_unscoped_route(path), path
            assert _asgi_status(method, path, viewer_headers) == 403, path
            assert _asgi_status(method, path, admin_headers) == 204, path
    finally:
        store.close()


def test_production_unscoped_routes_reject_shared_token_without_user_jwt(monkeypatch):
    monkeypatch.setenv("DATAOS_ENV", "production")
    monkeypatch.setenv("DATAOS_API_TOKEN", "t" * 48)
    monkeypatch.delenv("DATAOS_JWT_SECRET", raising=False)
    headers = {"authorization": f"Bearer {'t' * 48}"}
    assert _asgi_status("GET", "/api/graph/analytics", headers) == 503


def test_local_development_without_jwt_preserves_unscoped_route_compatibility(monkeypatch):
    for name in ("DATAOS_ENV", "APP_ENV", "ENVIRONMENT", "DATAOS_JWT_SECRET"):
        monkeypatch.delenv(name, raising=False)
    assert _asgi_status("GET", "/api/graph/analytics") == 204


def test_scoped_routes_are_not_accidentally_marked_global_admin_only():
    assert not authorization.is_admin_only_unscoped_route("/api/objects/")
    assert not authorization.is_admin_only_unscoped_route("/api/objects/object-1")
    assert not authorization.is_admin_only_unscoped_route("/api/search/")
    assert not authorization.is_admin_only_unscoped_route("/api/graph/traverse/object-1")
    assert not authorization.is_admin_only_unscoped_route("/api/vectors/search")
