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


def test_sql_requires_identity_when_production_or_jwt_auth_is_enabled():
    from backend.sql_authorization import requires_per_user_identity

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
    from backend.sql_authorization import user_owned_object_permissions

    permissions = user_owned_object_permissions(
        SimpleNamespace(id="alice", role="analyst")
    )

    assert permissions == {
        "owner": "alice",
        "read": ["alice"],
        "write": ["alice"],
    }
