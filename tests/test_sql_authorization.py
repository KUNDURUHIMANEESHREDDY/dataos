"""Tests for per-user object visibility in the legacy SQL and object APIs."""

from types import SimpleNamespace

import pytest

from backend.sql_authorization import (
    can_read_object,
    can_write_object,
    datasets_readable_by_user,
    list_objects_readable_by_user,
    requires_per_user_identity,
    user_owned_object_permissions,
)
from core.object.model import ObjectType


class FakeStorage:
    def __init__(self, objects):
        self.objects = objects
        self.calls = []

    def list_objects(self, **kwargs):
        self.calls.append(kwargs)
        offset = kwargs.get("offset", 0)
        limit = kwargs.get("limit", len(self.objects))
        return self.objects[offset:offset + limit]


def dataset(object_id, permissions):
    return SimpleNamespace(
        id=object_id,
        type=ObjectType.DATASET.value,
        permissions=permissions,
    )


def test_dataset_visibility_includes_owner_explicit_reader_and_public_data():
    storage = FakeStorage(
        [
            dataset("owned", {"owner": "alice", "read": [], "write": ["alice"]}),
            dataset("shared", {"owner": "bob", "read": ["alice"], "write": []}),
            dataset("public", {"owner": "bob", "read": ["*"], "write": []}),
            dataset("private", {"owner": "bob", "read": ["carol"], "write": []}),
        ]
    )

    visible = datasets_readable_by_user(
        storage,
        SimpleNamespace(id="alice", role="analyst"),
    )

    assert [item.id for item in visible] == ["owned", "shared", "public"]
    assert storage.calls == [{"object_type": "dataset", "limit": 100}]


def test_malformed_permissions_fail_closed_for_non_admin_users():
    storage = FakeStorage(
        [
            dataset("missing-owner", None),
            dataset("string-readers", {"owner": "bob", "read": "alice"}),
            dataset("wrong-reader-type", {"owner": "bob", "read": {"alice": True}}),
        ]
    )

    visible = datasets_readable_by_user(
        storage,
        SimpleNamespace(id="alice", role="analyst"),
    )

    assert visible == []


def test_admin_can_query_all_registered_datasets():
    objects = [
        dataset("owned", {"owner": "alice", "read": []}),
        dataset("private", {"owner": "bob", "read": ["carol"]}),
        dataset("legacy", None),
    ]
    storage = FakeStorage(objects)

    visible = datasets_readable_by_user(
        storage,
        SimpleNamespace(id="root", role="admin"),
    )

    assert visible == objects


def test_sql_requires_identity_when_production_or_jwt_auth_is_enabled():
    assert requires_per_user_identity(
        None,
        production_mode=True,
        jwt_auth_configured=False,
    )
    assert requires_per_user_identity(
        None,
        production_mode=False,
        jwt_auth_configured=True,
    )
    assert not requires_per_user_identity(
        None,
        production_mode=False,
        jwt_auth_configured=False,
    )
    assert not requires_per_user_identity(
        SimpleNamespace(id="alice", role="analyst"),
        production_mode=True,
        jwt_auth_configured=True,
    )


def test_new_objects_default_to_private_permissions_for_the_authenticated_owner():
    permissions = user_owned_object_permissions(
        SimpleNamespace(id="alice", role="analyst")
    )

    assert permissions == {
        "owner": "alice",
        "read": ["alice"],
        "write": ["alice"],
    }


def test_object_read_and_write_permissions_are_separate():
    alice = SimpleNamespace(id="alice", role="analyst")
    shared_read_only = dataset("shared", {"owner": "bob", "read": ["alice"], "write": []})
    private = dataset("private", {"owner": "bob", "read": ["carol"], "write": ["carol"]})

    assert can_read_object(alice, shared_read_only)
    assert not can_write_object(alice, shared_read_only)
    assert not can_read_object(alice, private)
    assert not can_write_object(alice, private)



def test_unresolved_fastapi_dependency_fails_closed_in_production(monkeypatch):
    import importlib

    import pytest
    from fastapi import HTTPException
    from fastapi.params import Depends as DependsParam

    api = importlib.import_module("backend.app")
    unresolved = DependsParam(dependency=api.get_current_user)
    assert api._resolved_current_user(unresolved) is None

    monkeypatch.setenv("DATAOS_ENV", "production")
    with pytest.raises(HTTPException) as exc:
        api._request_object_permissions(unresolved)
    assert exc.value.status_code == 401




def test_direct_sql_endpoint_uses_user_readable_datasets(monkeypatch):
    import asyncio
    import importlib

    api = importlib.import_module("backend.app")
    user = SimpleNamespace(id="alice", role="analyst")
    dataset = SimpleNamespace(id="owned-dataset")
    captured = {}
    monkeypatch.setattr(api, "datasets_readable_by_user", lambda storage, principal: [dataset])
    monkeypatch.setattr(
        api.dataos.sql_engine,
        "execute_sql",
        lambda query, **kwargs: captured.update(query=query, **kwargs) or {"success": True},
    )

    result = asyncio.run(
        api.compute_sql(api.SQLQueryRequest(query="SELECT * FROM sales"), current_user=user)
    )

    assert result == {"success": True}
    assert captured["table_objects"] == [dataset]
    assert captured["agent_or_user"] == "user:alice"


def test_direct_python_endpoint_intersects_requested_ids_with_user_acl(monkeypatch):
    import asyncio
    import importlib

    api = importlib.import_module("backend.app")
    user = SimpleNamespace(id="alice", role="analyst")
    captured = {}
    monkeypatch.setattr(api, "require_python_compute_enabled", lambda: None)
    monkeypatch.setattr(api, "_readable_object_ids", lambda principal: ["owned", "shared"])
    monkeypatch.setattr(
        api.dataos,
        "python",
        lambda code, **kwargs: captured.update(code=code, **kwargs) or {"success": True},
    )

    result = asyncio.run(
        api.compute_python(
            api.PythonComputeRequest(code="result = 1", input_object_ids=["owned", "private"]),
            current_user=user,
        )
    )

    assert result == {"success": True}
    assert captured["input_object_ids"] == ["owned"]
    assert captured["agent_or_user"] == "user:alice"



def test_unscoped_data_guard_allows_admin_and_rejects_other_roles():
    import asyncio
    import importlib

    from fastapi import HTTPException

    api = importlib.import_module("backend.app")
    analyst = SimpleNamespace(id="alice", role="analyst")
    admin = SimpleNamespace(id="root", role="admin")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(api.require_admin_for_unscoped_data(analyst))
    assert exc.value.status_code == 403
    assert asyncio.run(api.require_admin_for_unscoped_data(admin)) is admin


def test_authenticated_search_uses_only_readable_object_ids(monkeypatch):
    import asyncio
    import importlib

    api = importlib.import_module("backend.app")
    user = SimpleNamespace(id="alice", role="analyst", has_capability=lambda capability: True)
    captured = {}
    monkeypatch.setattr(api, "_readable_object_ids", lambda principal: ["owned", "shared"])
    monkeypatch.setattr(
        api.dataos.search_engine,
        "search",
        lambda **kwargs: captured.update(kwargs) or [{"object_id": "owned"}],
    )

    result = asyncio.run(api.hybrid_search(q="project", current_user=user))

    assert result["total_matches"] == 1
    assert captured["object_ids"] == ["owned", "shared"]


def test_authenticated_natural_language_search_fails_closed_until_scoped(monkeypatch):
    import asyncio
    import importlib

    from fastapi import HTTPException

    api = importlib.import_module("backend.app")
    user = SimpleNamespace(id="alice", role="analyst", has_capability=lambda capability: True)
    monkeypatch.setattr(api.dataos, "ask", lambda query: pytest.fail("global Ask must not run for a tenant user"))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(api.query_unified(
            api.UnifiedQueryRequest(query="summarize all files", query_type="ask"),
            current_user=user,
        ))

    assert exc.value.status_code == 501


def test_sql_api_redacts_internal_exception_details(monkeypatch):
    import asyncio
    import importlib

    api = importlib.import_module("backend.app")
    user = SimpleNamespace(id="alice", role="analyst", has_capability=lambda capability: True)
    monkeypatch.setattr(api, "datasets_readable_by_user", lambda storage, principal: [])
    monkeypatch.setattr(
        api.dataos.sql_engine,
        "execute_sql",
        lambda *args, **kwargs: {
            "success": False,
            "query": "SELECT * FROM private_table",
            "error": "Traceback: sqlite3.OperationalError at /srv/private/dataos.db",
            "provenance": {
                "engine": "sqlite_in_memory",
                "error": "Traceback: sqlite3.OperationalError at /srv/private/dataos.db",
            },
        },
    )

    result = asyncio.run(
        api.query_unified(
            api.UnifiedQueryRequest(query="SELECT * FROM private_table", query_type="sql"),
            current_user=user,
        )
    )

    assert result["error"] == "SQL query could not be executed."
    assert result["provenance"]["error"] == "SQL query could not be executed."
    assert "Traceback" not in str(result)
    assert "/srv/private" not in str(result)


def test_object_listing_paginates_after_acl_filtering():
    storage = FakeStorage(
        [
            dataset("private-1", {"owner": "bob", "read": []}),
            dataset("visible-1", {"owner": "alice", "read": []}),
            dataset("private-2", {"owner": "bob", "read": []}),
            dataset("visible-2", {"owner": "alice", "read": []}),
            dataset("visible-3", {"owner": "alice", "read": []}),
        ]
    )

    page, total = list_objects_readable_by_user(
        storage,
        SimpleNamespace(id="alice", role="analyst"),
        limit=1,
        offset=1,
        scan_page_size=2,
    )

    assert [item.id for item in page] == ["visible-2"]
    assert total == 3
