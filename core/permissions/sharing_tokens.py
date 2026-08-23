"""
Cryptographically Signed Subgraph & Object Sharing Tokens for DataOS (Rule #65).
Enables secure, verifiable, revocable, and capability-scoped sharing of objects and subgraphs.
"""

from __future__ import annotations
import hmac
import hashlib
import json
import base64
import time
import datetime
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass, field, asdict
from core.permissions.policy import Capability


@dataclass
class SharingTokenPayload:
    """Payload contained inside a cryptographically signed DataOS Sharing Token."""
    token_id: str
    issuer: str
    subject_principal: str
    subgraph_root_id: str
    allowed_object_ids: List[str]
    allowed_capabilities: List[str]
    max_hops: int = 1
    issued_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    expires_at: Optional[str] = None  # ISO timestamp or None for non-expiring

    def is_expired(self) -> bool:
        """Check if the token has expired."""
        if not self.expires_at:
            return False
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        return now_iso > self.expires_at

    def allows_object(self, object_id: str) -> bool:
        """Check if the token permits access to the given object."""
        if "*" in self.allowed_object_ids:
            return True
        return object_id in self.allowed_object_ids or object_id == self.subgraph_root_id

    def allows_capability(self, capability: str) -> bool:
        """Check if the token permits the given capability."""
        return capability in self.allowed_capabilities or "*" in self.allowed_capabilities


class SubgraphTokenManager:
    """Issues and verifies cryptographically signed HMAC-SHA256 sharing tokens."""

    def __init__(self, secret_key: str = "dataos_subgraph_master_secret_2026"):
        """Initialize with an HMAC secret key for signing."""
        self.secret_key = secret_key.encode("utf-8")

    def issue_token(
        self,
        issuer: str,
        subject_principal: str,
        subgraph_root_id: str,
        allowed_object_ids: Optional[List[str]] = None,
        allowed_capabilities: Optional[List[str]] = None,
        max_hops: int = 2,
        duration_seconds: Optional[int] = 3600
    ) -> str:
        """Create and sign a scoped token string."""
        import uuid
        now = datetime.datetime.now(datetime.timezone.utc)
        expires_at = (now + datetime.timedelta(seconds=duration_seconds)).isoformat() if duration_seconds else None

        payload = SharingTokenPayload(
            token_id=f"tok_{uuid.uuid4().hex[:12]}",
            issuer=issuer,
            subject_principal=subject_principal,
            subgraph_root_id=subgraph_root_id,
            allowed_object_ids=allowed_object_ids or [subgraph_root_id],
            allowed_capabilities=allowed_capabilities or [Capability.READ_OBJECT.value],
            max_hops=max_hops,
            issued_at=now.isoformat(),
            expires_at=expires_at
        )

        payload_json = json.dumps(asdict(payload), sort_keys=True)
        payload_b64 = base64.urlsafe_b64encode(payload_json.encode("utf-8")).decode("utf-8")

        # Compute HMAC signature
        signature = hmac.new(self.secret_key, payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{payload_b64}.{signature}"

    def verify_and_decode_token(self, token_str: str) -> SharingTokenPayload:
        """
        Verify cryptographic signature and expiration.
        Raises ValueError or PermissionError on tampering or expiration.
        """
        parts = token_str.split(".")
        if len(parts) != 2:
            raise ValueError("Malformed sharing token format.")

        payload_b64, signature = parts[0], parts[1]

        # Verify HMAC
        expected_sig = hmac.new(self.secret_key, payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected_sig):
            raise PermissionError("Invalid cryptographic signature on sharing token (tampering detected).")

        # Decode payload
        payload_json = base64.urlsafe_b64decode(payload_b64.encode("utf-8")).decode("utf-8")
        payload_dict = json.loads(payload_json)
        payload = SharingTokenPayload(**payload_dict)

        # Check expiration
        if payload.is_expired():
            raise PermissionError(f"Sharing token '{payload.token_id}' expired at {payload.expires_at}.")

        return payload
