"""Contract tests for the JWT-configured /api authorization boundary."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException, Request

import backend.authorization as authorization
from backend.app import require_production_api_token
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
