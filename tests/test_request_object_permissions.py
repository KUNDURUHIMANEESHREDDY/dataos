"""Regression tests for request-scoped ingestion authorization."""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import backend.app as api


def test_request_object_permissions_assigns_private_owner_acl():
    permissions = api._request_object_permissions(SimpleNamespace(id="alice"))

    assert permissions == {
        "owner": "alice",
        "read": ["alice"],
        "write": ["alice"],
    }


def test_request_object_permissions_requires_user_when_jwt_is_configured(monkeypatch):
    monkeypatch.setattr(api, "jwt_configured", lambda: True)
    monkeypatch.setattr(api, "_production_mode", lambda: False)

    with pytest.raises(HTTPException) as exc:
        api._request_object_permissions(None)

    assert exc.value.status_code == 401
    assert exc.value.headers["WWW-Authenticate"] == "Bearer"


def test_request_object_permissions_fails_closed_in_production_without_jwt(monkeypatch):
    monkeypatch.setattr(api, "jwt_configured", lambda: False)
    monkeypatch.setattr(api, "_production_mode", lambda: True)

    with pytest.raises(HTTPException) as exc:
        api._request_object_permissions(None)

    assert exc.value.status_code == 503
    assert "DATAOS_JWT_SECRET" in exc.value.detail


def test_ingest_text_forwards_authenticated_owner_acl(monkeypatch):
    captured = {}

    def ingest(content, filename, discover_relations, permissions=None):
        captured.update(
            content=content,
            filename=filename,
            discover_relations=discover_relations,
            permissions=permissions,
        )
        return {"status": "ingested"}

    monkeypatch.setattr(api.dataos, "ingest", ingest)
    result = asyncio.run(
        api.ingest_text(
            filename="private.txt",
            content="private report",
            current_user=SimpleNamespace(id="alice"),
        )
    )

    assert result == {"status": "ingested"}
    assert captured == {
        "content": "private report",
        "filename": "private.txt",
        "discover_relations": True,
        "permissions": {
            "owner": "alice",
            "read": ["alice"],
            "write": ["alice"],
        },
    }


@pytest.mark.parametrize(
    ("handler", "kwargs", "expected_filename", "expected_discovery"),
    [
        ("ingest_notebook_api", {"filename": "private.ipynb", "content": "{}"}, "private.ipynb", True),
        ("extract_rich_document_api", {"filename": "private.md", "content": "# Private"}, "private.md", True),
        ("universal_ingest_api", {"filename": "private.json", "content": "{}", "discover_relations": False}, "private.json", False),
    ],
)
def test_all_ingestion_routes_forward_creator_acl(
    monkeypatch, handler, kwargs, expected_filename, expected_discovery
):
    captured = {}

    def ingest(content, filename, discover_relations, permissions=None):
        captured.update(
            content=content,
            filename=filename,
            discover_relations=discover_relations,
            permissions=permissions,
        )
        return {"status": "ingested"}

    monkeypatch.setattr(api.dataos, "ingest", ingest)
    route = getattr(api, handler)
    result = asyncio.run(route(**kwargs, current_user=SimpleNamespace(id="alice")))

    assert result == {"status": "ingested"}
    assert captured["filename"] == expected_filename
    assert captured["discover_relations"] is expected_discovery
    assert captured["permissions"] == {
        "owner": "alice",
        "read": ["alice"],
        "write": ["alice"],
    }
