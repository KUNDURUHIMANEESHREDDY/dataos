"""Principal-aware read ACL helpers for the legacy Python API.

The Rust production backend has indexed ACL enforcement. This module provides
bounded parity for the legacy Python reference backend: it never paginates
before authorization, and it fails closed when a non-admin request would
require scanning beyond the configured safety bound.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException

PAGE_SIZE = 500
MAX_AUTHORIZATION_SCAN = 20_000


def _normalized_user(current_user: Any) -> Any:
    """Treat FastAPI dependency placeholders like an absent principal in direct tests."""
    return current_user if current_user is not None and getattr(current_user, "id", None) else None


def _principal_values(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, (list, tuple, set)):
        return {str(item) for item in value if item is not None}
    return set()


def can_read_object(obj: Any, current_user: Any) -> bool:
    """Return whether the authenticated principal may read one object."""
    current_user = _normalized_user(current_user)
    if current_user is None:
        # Development/shared-token mode is handled by require_read_identity.
        return True
    if getattr(current_user, "role", None) == "admin":
        return True

    principal_id = str(getattr(current_user, "id", "") or "")
    if not principal_id:
        return False

    permissions = getattr(obj, "permissions", None)
    if not isinstance(permissions, dict):
        return False

    owner = str(permissions.get("owner", "") or "")
    readers = _principal_values(permissions.get("read"))
    return owner == principal_id or "*" in readers or principal_id in readers


def require_read_identity(
    current_user: Any,
    *,
    jwt_enabled: bool,
    production: bool,
) -> None:
    """Require a principal whenever the API is configured for authenticated reads."""
    current_user = _normalized_user(current_user)
    if current_user is not None:
        return
    if jwt_enabled:
        raise HTTPException(
            status_code=401,
            detail="A per-user session is required to read DataOS objects.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if production:
        raise HTTPException(
            status_code=503,
            detail="Per-user JWT authentication is required for production object reads. Configure DATAOS_JWT_SECRET.",
        )


def list_readable_objects(
    storage: Any,
    current_user: Any,
    *,
    object_type: Optional[str] = None,
    source: Optional[str] = None,
    jwt_enabled: bool = False,
    production: bool = False,
) -> Optional[list[Any]]:
    """Return all visible objects before pagination, or None for trusted dev/admin views.

    The Python reference backend does not expose an indexed ACL query on every
    supported storage adapter. Scan in bounded pages and refuse oversized
    collections rather than return a partially authorized page or leak rows.
    """
    require_read_identity(
        current_user,
        jwt_enabled=jwt_enabled,
        production=production,
    )
    current_user = _normalized_user(current_user)
    if current_user is None or getattr(current_user, "role", None) == "admin":
        return None

    visible: list[Any] = []
    offset = 0
    while offset < MAX_AUTHORIZATION_SCAN:
        batch = storage.list_objects(
            object_type=object_type,
            source=source,
            limit=min(PAGE_SIZE, MAX_AUTHORIZATION_SCAN - offset),
            offset=offset,
        )
        if not batch:
            return visible
        visible.extend(obj for obj in batch if can_read_object(obj, current_user))
        offset += len(batch)
        if len(batch) < PAGE_SIZE:
            return visible

    # Distinguish exactly MAX_AUTHORIZATION_SCAN rows from a truncated scan.
    probe = storage.list_objects(
        object_type=object_type,
        source=source,
        limit=1,
        offset=MAX_AUTHORIZATION_SCAN,
    )
    if probe:
        raise HTTPException(
            status_code=503,
            detail=(
                "The Python reference backend cannot safely authorize this collection "
                f"above {MAX_AUTHORIZATION_SCAN} objects; use the indexed Rust backend."
            ),
            headers={"Retry-After": "30"},
        )
    return visible


def readable_object_ids(
    storage: Any,
    current_user: Any,
    *,
    jwt_enabled: bool = False,
    production: bool = False,
) -> Optional[set[str]]:
    """Return visible object IDs for search engines that support ID filtering."""
    objects = list_readable_objects(
        storage,
        current_user,
        jwt_enabled=jwt_enabled,
        production=production,
    )
    if objects is None:
        return None
    return {str(obj.id) for obj in objects}
