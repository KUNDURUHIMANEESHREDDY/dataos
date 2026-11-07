"""Tests for per-user dataset visibility in the legacy SQL execution path."""

from types import SimpleNamespace

from backend.sql_authorization import datasets_readable_by_user
from core.object.model import ObjectType


class FakeStorage:
    def __init__(self, objects):
        self.objects = objects
        self.calls = []

    def list_objects(self, **kwargs):
        self.calls.append(kwargs)
        return self.objects


def dataset(object_id, permissions):
    return SimpleNamespace(
        id=object_id,
        type=ObjectType.DATASET.value,
        permissions=permissions,
    )


def test_dataset_visibility_includes_owner_explicit_reader_and_public_data():
    storage = FakeStorage(
        [
            dataset("owned", {"owner": "alice", "read": []}),
            dataset("shared", {"owner": "bob", "read": ["alice"]}),
            dataset("public", {"owner": "bob", "read": ["*"]}),
            dataset("private", {"owner": "bob", "read": ["carol"]}),
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
