"""Contract tests for the JWT-configured /api authorization boundary."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException, Request

import backend.authorization as authorization
from backend.authorization import get_current_user, require_capability
from backend.app import RegisterRequest, register_user, require_production_api_token
from core.permissions.auth import UserStore, issue_jwt
from core.permissions.policy import Role


def _request(path: str, method: str = "GET", authorization_header: str | None = None) -> Request:
    headers = []
    if authorization_header is not None:
        headers.append((b"authorization", authorization_header.encode("utf-8")))
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



def test_jwt_configured_routes_require_identity_except_auth_me(monkeypatch):
    monkeypatch.setenv("DATAOS_JWT_SECRET", "j" * 48)
    assert get_current_user(_request("/api/auth/me"), authorization=None) is None
    with pytest.raises(HTTPException) as exc:
        get_current_user(_request("/api/query/"), authorization=None)
    assert exc.value.status_code == 401


def test_get_current_user_resolves_registered_jwt_principal(monkeypatch, tmp_path):
    monkeypatch.setenv("DATAOS_JWT_SECRET", "j" * 48)
    store = UserStore(db_path=str(tmp_path / "principal.db"))
    try:
        user = store.register("analyst", "analyst@example.com", "password123", role=Role.ANALYST.value)
        monkeypatch.setattr(authorization, "_user_store", store)
        token = issue_jwt(user.id, user.role)
        resolved = get_current_user(_request("/api/query/"), authorization=f"Bearer {token}")
        assert resolved is not None
        assert resolved.id == user.id
        assert resolved.role == Role.ANALYST.value
    finally:
        store.close()


def test_self_registration_rejects_role_escalation():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RegisterRequest(
            username="attacker",
            email="attacker@example.com",
            password="password123",
            role="admin",
        )


def test_registration_always_creates_viewer(monkeypatch, tmp_path):
    monkeypatch.setenv("DATAOS_JWT_SECRET", "j" * 48)
    store = UserStore(db_path=str(tmp_path / "registration.db"))
    try:
        monkeypatch.setattr(authorization, "_user_store", store)
        result = asyncio.run(
            register_user(
                RegisterRequest(
                    username="new-user",
                    email="new-user@example.com",
                    password="password123",
                )
            )
        )
        assert result["role"] == Role.VIEWER.value
        assert "password_hash" not in result
    finally:
        store.close()


def test_capability_dependency_rejects_viewer_write(monkeypatch, tmp_path):
    monkeypatch.setenv("DATAOS_JWT_SECRET", "j" * 48)
    store = UserStore(db_path=str(tmp_path / "capability.db"))
    try:
        user = store.register("viewer", "viewer2@example.com", "password123", role=Role.VIEWER.value)
        dependency = require_capability("create_object")
        with pytest.raises(HTTPException) as exc:
            dependency(user)
        assert exc.value.status_code == 403
    finally:
        store.close()
