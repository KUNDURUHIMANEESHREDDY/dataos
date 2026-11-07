"""Tests for per-user object visibility in the legacy SQL and object APIs."""

from types import SimpleNamespace

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
