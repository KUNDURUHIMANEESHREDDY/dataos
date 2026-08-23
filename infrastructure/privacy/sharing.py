"""
Selective Sharing and Access Control for DataOS (Rule #43, Rule #65).
Manages encrypted sharing tokens, access policies, and private execution contexts.
"""

from __future__ import annotations
import uuid
import datetime
import hashlib
import secrets
from typing import Dict, Any, List, Optional, Set
from enum import Enum


class SharingLevel(str, Enum):
    PRIVATE = "private"
    SHARED_READ = "shared_read"
    SHARED_WRITE = "shared_write"
    PUBLIC = "public"


class SharingToken:
    """An encrypted token granting access to specific objects/subgraphs."""

    def __init__(
        self,
        grantor_id: str,
        grantee_id: str,
        object_ids: List[str],
        level: SharingLevel = SharingLevel.SHARED_READ,
        expires_in_hours: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.token_id = str(uuid.uuid4())
        self.grantor_id = grantor_id
        self.grantee_id = grantee_id
        self.object_ids = object_ids
        self.level = level
        self.metadata = metadata or {}
        self.created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.expires_at = None
        self.revoked = False
        self._secret = secrets.token_urlsafe(32)

        if expires_in_hours:
            exp = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=expires_in_hours)
            self.expires_at = exp.isoformat()

    @property
    def token_value(self) -> str:
        """The shareable token string."""
        raw = f"{self.token_id}:{self._secret}"
        return hashlib.sha256(raw.encode()).hexdigest()[:48]

    def is_valid(self) -> bool:
        """Check if token is active and not expired."""
        if self.revoked:
            return False
        if self.expires_at:
            try:
                exp = datetime.datetime.fromisoformat(self.expires_at)
                if datetime.datetime.now(datetime.timezone.utc) > exp:
                    return False
            except (ValueError, TypeError):
                pass
        return True

    def can_access(self, object_id: str, write: bool = False) -> bool:
        """Check if this token grants access to an object."""
        if not self.is_valid():
            return False
        if object_id not in self.object_ids:
            return False
        if write and self.level not in (SharingLevel.SHARED_WRITE, SharingLevel.PUBLIC):
            return False
        return True

    def revoke(self) -> None:
        """Revoke this token."""
        self.revoked = True

    def to_dict(self) -> Dict[str, Any]:
        """Return token as dictionary."""
        return {
            "token_id": self.token_id,
            "grantor_id": self.grantor_id,
            "grantee_id": self.grantee_id,
            "object_ids": self.object_ids,
            "level": self.level.value,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "revoked": self.revoked,
            "metadata": self.metadata,
        }


class PrivateExecutionContext:
    """Isolated execution context for sensitive operations."""

    def __init__(self, context_id: Optional[str] = None, owner_id: str = "system"):
        self.context_id = context_id or str(uuid.uuid4())
        self.owner_id = owner_id
        self.created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self._accessible_objects: Set[str] = set()
        self._audit_log: List[Dict[str, Any]] = []
        self._encryption_enabled = True
        self._closed = False

    def grant_access(self, object_id: str) -> None:
        """Grant access to an object within this context."""
        if self._closed:
            raise RuntimeError("Context is closed")
        self._accessible_objects.add(object_id)
        self._log("grant_access", {"object_id": object_id})

    def revoke_access(self, object_id: str) -> None:
        """Revoke access to an object within this context."""
        self._accessible_objects.discard(object_id)
        self._log("revoke_access", {"object_id": object_id})

    def can_access(self, object_id: str) -> bool:
        """Check if an object is accessible in this context."""
        if self._closed:
            return False
        return object_id in self._accessible_objects

    def record_operation(self, operation: str, details: Dict[str, Any]) -> None:
        """Record an operation in the audit log."""
        self._log(operation, details)

    def get_audit_log(self) -> List[Dict[str, Any]]:
        """Return the full audit log for this context."""
        return list(self._audit_log)

    def close(self) -> None:
        """Close the execution context."""
        self._closed = True
        self._log("context_closed", {})

    def _log(self, operation: str, details: Dict[str, Any]) -> None:
        self._audit_log.append({
            "operation": operation,
            "details": details,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        })

    def to_dict(self) -> Dict[str, Any]:
        """Return context as dictionary."""
        return {
            "context_id": self.context_id,
            "owner_id": self.owner_id,
            "created_at": self.created_at,
            "accessible_objects": list(self._accessible_objects),
            "closed": self._closed,
            "audit_log_size": len(self._audit_log),
        }


class SelectiveSharingManager:
    """
    Manages sharing tokens, access policies, and private contexts.
    Central hub for privacy and sharing operations.
    """

    def __init__(self):
        self._tokens: Dict[str, SharingToken] = {}
        self._contexts: Dict[str, PrivateExecutionContext] = {}
        self._access_policies: Dict[str, Dict[str, Any]] = {}

    def create_token(
        self,
        grantor_id: str,
        grantee_id: str,
        object_ids: List[str],
        level: SharingLevel = SharingLevel.SHARED_READ,
        expires_in_hours: Optional[int] = None,
    ) -> SharingToken:
        """Create and register a sharing token."""
        token = SharingToken(
            grantor_id=grantor_id,
            grantee_id=grantee_id,
            object_ids=object_ids,
            level=level,
            expires_in_hours=expires_in_hours,
        )
        self._tokens[token.token_id] = token
        return token

    def revoke_token(self, token_id: str) -> bool:
        """Revoke a sharing token."""
        token = self._tokens.get(token_id)
        if token:
            token.revoke()
            return True
        return False

    def get_token(self, token_id: str) -> Optional[SharingToken]:
        """Get a token by ID."""
        return self._tokens.get(token_id)

    def get_tokens_for_grantee(self, grantee_id: str) -> List[Dict[str, Any]]:
        """Get all valid tokens for a specific grantee."""
        return [
            t.to_dict() for t in self._tokens.values()
            if t.grantee_id == grantee_id and t.is_valid()
        ]

    def get_tokens_for_object(self, object_id: str) -> List[Dict[str, Any]]:
        """Get all valid tokens that grant access to an object."""
        return [
            t.to_dict() for t in self._tokens.values()
            if object_id in t.object_ids and t.is_valid()
        ]

    def check_access(
        self,
        token_id: str,
        object_id: str,
        write: bool = False,
    ) -> bool:
        """Check if a token grants access to an object."""
        token = self._tokens.get(token_id)
        if not token:
            return False
        return token.can_access(object_id, write=write)

    def create_context(
        self,
        owner_id: str,
        initial_objects: Optional[List[str]] = None,
    ) -> PrivateExecutionContext:
        """Create a new private execution context."""
        ctx = PrivateExecutionContext(owner_id=owner_id)
        for oid in (initial_objects or []):
            ctx.grant_access(oid)
        self._contexts[ctx.context_id] = ctx
        return ctx

    def get_context(self, context_id: str) -> Optional[PrivateExecutionContext]:
        """Get a context by ID."""
        return self._contexts.get(context_id)

    def close_context(self, context_id: str) -> bool:
        """Close a private execution context."""
        ctx = self._contexts.get(context_id)
        if ctx:
            ctx.close()
            return True
        return False

    def set_access_policy(self, policy_id: str, policy: Dict[str, Any]) -> None:
        """Set an access control policy."""
        self._access_policies[policy_id] = policy

    def get_access_policy(self, policy_id: str) -> Optional[Dict[str, Any]]:
        """Get an access control policy."""
        return self._access_policies.get(policy_id)

    def list_policies(self) -> List[Dict[str, Any]]:
        """List all access policies."""
        return [{"id": pid, **p} for pid, p in self._access_policies.items()]

    def get_stats(self) -> Dict[str, Any]:
        """Return sharing statistics."""
        active_tokens = sum(1 for t in self._tokens.values() if t.is_valid())
        return {
            "total_tokens": len(self._tokens),
            "active_tokens": active_tokens,
            "revoked_tokens": len(self._tokens) - active_tokens,
            "total_contexts": len(self._contexts),
            "active_contexts": sum(1 for c in self._contexts.values() if not c._closed),
            "total_policies": len(self._access_policies),
        }
