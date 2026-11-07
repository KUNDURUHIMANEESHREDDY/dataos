"""Per-user dataset visibility for legacy Python SQL execution.

The Rust/Axum backend applies owner scoping in its database layer. The legacy
FastAPI backend must apply the same object-permission boundary before registering
datasets in the in-memory SQL engine.
"""

from __future__ import annotations

from typing import Any

from core.object.model import ObjectType
from core.permissions.auth import User
from infrastructure.storage.base import StorageBackend


def datasets_readable_by_user(
    storage: StorageBackend,
    user: User,
    *,
    limit: int = 100,
) -> list[Any]:
    """Return only datasets the authenticated user may read.

    Ownership grants read access. Otherwise, the object's explicit read
    permission list must contain the user's ID or the public wildcard. Malformed
    or missing permission metadata fails closed for non-admin users. Admin
    access remains capability-gated by the route before this helper is called.
    """
    datasets = storage.list_objects(
        object_type=ObjectType.DATASET.value,
        limit=limit,
    )

    if user.role == "admin":
        return datasets

    principal_id = str(user.id)
    readable = []
    for dataset in datasets:
        permissions = getattr(dataset, "permissions", None)
        if not isinstance(permissions, dict):
            continue

        if permissions.get("owner") == principal_id:
            readable.append(dataset)
            continue

        readers = permissions.get("read", ())
        if isinstance(readers, (list, tuple, set)) and (
            "*" in readers or principal_id in readers
        ):
            readable.append(dataset)

    return readable


def requires_per_user_identity(
    user: User | None,
    *,
    production_mode: bool,
    jwt_auth_configured: bool,
) -> bool:
    """Return whether SQL must reject a request that has no resolved user."""
    return user is None and (production_mode or jwt_auth_configured)
