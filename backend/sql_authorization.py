"""Per-user object visibility for the legacy Python/FastAPI backend."""

from __future__ import annotations

from typing import Any

from core.object.model import ObjectType
from core.permissions.auth import User
from infrastructure.storage.base import StorageBackend


def requires_per_user_identity(
    user: User | None,
    *,
    production_mode: bool,
    jwt_auth_configured: bool,
) -> bool:
    """Return whether a request without a resolved user must fail closed."""
    return user is None and (production_mode or jwt_auth_configured)


def user_owned_object_permissions(user: User) -> dict[str, Any]:
    """Build private-by-default object permissions for an authenticated user."""
    principal_id = str(user.id)
    return {
        "owner": principal_id,
        "read": [principal_id],
        "write": [principal_id],
    }


def can_read_object(user: User, obj: Any) -> bool:
    """Check object-level read permission after route capability checks."""
    if user.role == "admin":
        return True

    permissions = getattr(obj, "permissions", None)
    if not isinstance(permissions, dict):
        return False

    principal_id = str(user.id)
    if permissions.get("owner") == principal_id:
        return True

    readers = permissions.get("read", ())
    return isinstance(readers, (list, tuple, set)) and (
        "*" in readers or principal_id in readers
    )


def can_write_object(user: User, obj: Any) -> bool:
    """Check object-level write permission after route capability checks."""
    if user.role == "admin":
        return True

    permissions = getattr(obj, "permissions", None)
    if not isinstance(permissions, dict):
        return False

    principal_id = str(user.id)
    if permissions.get("owner") == principal_id:
        return True

    writers = permissions.get("write", ())
    return isinstance(writers, (list, tuple, set)) and (
        "*" in writers or principal_id in writers
    )


def datasets_readable_by_user(
    storage: StorageBackend,
    user: User,
    *,
    limit: int = 100,
) -> list[Any]:
    """Return only datasets the authenticated user may read."""
    datasets = storage.list_objects(
        object_type=ObjectType.DATASET.value,
        limit=limit,
    )
    return [dataset for dataset in datasets if can_read_object(user, dataset)]


def list_objects_readable_by_user(
    storage: StorageBackend,
    user: User,
    *,
    object_type: str | None = None,
    source: str | None = None,
    limit: int = 100,
    offset: int = 0,
    scan_page_size: int = 1000,
) -> tuple[list[Any], int]:
    """Filter object listing by ACL while preserving visible-item pagination.

    Storage adapters expose portable type/source pagination but not a common
    JSON-permission query. Scan in bounded pages, retain only the requested
    visible page, and count all visible matches for the existing API contract.
    """
    if limit < 1 or offset < 0 or scan_page_size < 1:
        raise ValueError("Object listing limits must be positive and offset non-negative")

    visible_page: list[Any] = []
    visible_total = 0
    scan_offset = 0

    while True:
        batch = storage.list_objects(
            object_type=object_type,
            source=source,
            limit=scan_page_size,
            offset=scan_offset,
        )
        if not batch:
            break

        for obj in batch:
            if not can_read_object(user, obj):
                continue
            if offset <= visible_total < offset + limit:
                visible_page.append(obj)
            visible_total += 1

        scan_offset += len(batch)
        if len(batch) < scan_page_size:
            break

    return visible_page, visible_total
