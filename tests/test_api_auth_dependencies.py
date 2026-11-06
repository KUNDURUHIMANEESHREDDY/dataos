"""Regression tests for FastAPI's per-user JWT route dependencies."""

import asyncio

import pytest
from pydantic import ValidationError
from fastapi import HTTPException

import backend.app as api
from core.permissions.auth import UserStore, issue_jwt
from core.permissions.policy import Capability, Role


def run(coro):
    return asyncio.run(coro)


def test_get_current_user_resolves_a_valid_jwt(monkeypatch, tmp_path):
    monkeypatch.setenv("DATAOS_JWT_SECRET", "j" * 48)
    store = UserStore(db_path=str(tmp_path / "users.db"))
    try:
        user = store.register("alice", "alice@example.com", "password123", role=Role.ADMIN.value)
        monkeypatch.setattr(api, "get_user_store", lambda: store)
        token = issue_jwt(user.id, user.role)

        assert run(api.get_current_user(f"Bearer {token}")) == user
    finally:
        store.close()


def test_get_current_user_returns_none_when_jwt_auth_is_disabled(monkeypatch):
    monkeypatch.delenv("DATAOS_JWT_SECRET", raising=False)
    assert run(api.get_current_user(None)) is None


def test_get_current_user_rejects_invalid_or_unknown_jwt(monkeypatch, tmp_path):
    monkeypatch.setenv("DATAOS_JWT_SECRET", "j" * 48)
    store = UserStore(db_path=str(tmp_path / "users.db"))
    try:
        monkeypatch.setattr(api, "get_user_store", lambda: store)
        with pytest.raises(HTTPException) as invalid:
            run(api.get_current_user("Bearer not-a-jwt"))
        assert invalid.value.status_code == 401

        unknown = issue_jwt("missing-user", Role.VIEWER.value)
        with pytest.raises(HTTPException) as missing:
            run(api.get_current_user(f"Bearer {unknown}"))
        assert missing.value.status_code == 401
    finally:
        store.close()


def test_require_capability_enforces_user_role():
    dependency = api.require_capability(Capability.EXPORT_DATA.value)
    admin = api.User(
        id="admin-1",
        username="admin",
        email="admin@example.com",
        role=Role.ADMIN.value,
        password_hash="unused",
    )
    viewer = api.User(
        id="viewer-1",
        username="viewer",
        email="viewer@example.com",
        role=Role.VIEWER.value,
        password_hash="unused",
    )

    assert run(dependency(current_user=admin)) is admin
    with pytest.raises(HTTPException) as forbidden:
        run(dependency(current_user=viewer))
    assert forbidden.value.status_code == 403

    with pytest.raises(HTTPException) as unauthenticated:
        run(dependency(current_user=None))
    assert unauthenticated.value.status_code == 401

def test_public_registration_rejects_caller_selected_roles():
    with pytest.raises(ValidationError):
        api.RegisterRequest(
            username="attacker",
            email="attacker@example.com",
            password="password123",
            role=Role.ADMIN.value,
        )


def test_public_registration_always_uses_viewer_role(monkeypatch, tmp_path):
    monkeypatch.setenv("DATAOS_JWT_SECRET", "j" * 48)
    store = UserStore(db_path=str(tmp_path / "register.db"))
    try:
        monkeypatch.setattr(api, "get_user_store", lambda: store)
        result = run(api.register_user(api.RegisterRequest(
            username="new-user",
            email="new-user@example.com",
            password="password123",
        )))
        assert result["role"] == Role.VIEWER.value
    finally:
        store.close()
