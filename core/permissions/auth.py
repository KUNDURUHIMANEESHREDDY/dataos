"""
Per-user identity for DataOS — user store, password hashing, and JWT auth.

No external IdP is required: users are stored in the same SQLite/Postgres
backend as DataOS objects (a `dataos_users` table the backend ensures exists),
passwords are hashed with stdlib PBKDF2-HMAC-SHA256 (no extra dependency),
and tokens are HS256 JWTs signed with DATAOS_JWT_SECRET (>=32 UTF-8 bytes).

Designed to be safe to run even when DATAOS_JWT_SECRET is unset in dev:
tokens are simply never issued. In production the routes fail closed.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from core.permissions.policy import ROLE_CAPABILITIES, Role

JWT_SECRET_ENV = "DATAOS_JWT_SECRET"
DEFAULT_TTL_SECONDS = 3600
MAX_TTL_SECONDS = 86400
MIN_SECRET_BYTES = 32

VALID_ROLES = {r.value for r in Role}


def _jwt_secret() -> str:
    secret = os.getenv(JWT_SECRET_ENV, "")
    if not secret or secret.strip() != secret or len(secret.encode("utf-8")) < MIN_SECRET_BYTES:
        return ""
    return secret


def jwt_configured() -> bool:
    return bool(_jwt_secret())


def hash_password(password: str) -> str:
    """PBKDF2-HMAC-SHA256 with a random salt. Format: salt$iterations$dk_b64."""
    salt = os.urandom(16)
    iterations = 200_000
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=32)
    return f"{salt.hex()}${iterations}${base64.b64encode(dk).decode('ascii')}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, iterations_s, dk_b64 = stored.split("$", 2)
        salt = bytes.fromhex(salt_hex)
        iterations = int(iterations_s)
        expected = base64.b64decode(dk_b64)
    except (ValueError, TypeError):
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=len(expected))
    return hmac.compare_digest(dk, expected)


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(segment: str) -> bytes:
    segment += "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment.encode("ascii"))


def issue_jwt(user_id: str, role: str, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> str:
    secret = _jwt_secret()
    if not secret:
        raise RuntimeError("JWT auth is disabled until DATAOS_JWT_SECRET is configured.")
    ttl = max(1, min(ttl_seconds, MAX_TTL_SECONDS))
    import json
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {"sub": user_id, "role": role, "iat": now, "exp": now + ttl}
    header_seg = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_seg = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_seg}.{payload_seg}".encode("ascii")
    sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header_seg}.{payload_seg}.{_b64url_encode(sig)}"


def decode_jwt(token: str) -> dict:
    secret = _jwt_secret()
    if not secret:
        raise ValueError("JWT auth is not configured.")
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Malformed token.")
    header_seg, payload_seg, sig_seg = parts
    signing_input = f"{header_seg}.{payload_seg}".encode("ascii")
    expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    if not hmac.compare_digest(_b64url_decode(sig_seg), expected):
        raise ValueError("Invalid token signature.")
    import json
    payload = json.loads(_b64url_decode(payload_seg))
    if int(payload.get("exp", 0)) <= int(time.time()):
        raise ValueError("Token expired.")
    return payload


@dataclass
class User:
    id: str
    username: str
    email: str
    role: str
    password_hash: str = field(repr=False)
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()))

    @property
    def capabilities(self) -> set:
        return set(ROLE_CAPABILITIES.get(self.role, ROLE_CAPABILITIES[Role.VIEWER.value]))

    def has_capability(self, capability: str) -> bool:
        return capability in self.capabilities

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "role": self.role,
            "capabilities": sorted(self.capabilities),
            "created_at": self.created_at,
        }


class UserStore:
    """SQLite-backed user store. The table is created on first use."""

    def __init__(self, db_path: str = "dataos.db"):
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dataos_users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE,
                role TEXT NOT NULL DEFAULT 'viewer',
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def register(self, username: str, email: str, password: str, role: str = "viewer") -> User:
        username = username.strip()
        email = email.strip().lower()
        if not username or not email or not password:
            raise ValueError("username, email, and password are all required.")
        if role not in VALID_ROLES:
            raise ValueError(f"Unknown role '{role}'. Valid roles: {sorted(VALID_ROLES)}")
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters.")
        user = User(
            id=str(uuid.uuid4()),
            username=username,
            email=email,
            role=role,
            password_hash=hash_password(password),
        )
        try:
            self._conn.execute(
                "INSERT INTO dataos_users (id, username, email, role, password_hash, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (user.id, user.username, user.email, user.role, user.password_hash, user.created_at),
            )
            self._conn.commit()
        except sqlite3.IntegrityError:
            raise ValueError("A user with this username or email already exists.")
        return user

    def _from_row(self, row) -> User:
        return User(
            id=row["id"], username=row["username"], email=row["email"],
            role=row["role"], password_hash=row["password_hash"], created_at=row["created_at"],
        )

    def get_by_id(self, user_id: str) -> Optional[User]:
        row = self._conn.execute("SELECT * FROM dataos_users WHERE id = ?", (user_id,)).fetchone()
        return self._from_row(row) if row else None

    def get_by_login(self, login: str) -> Optional[User]:
        row = self._conn.execute(
            "SELECT * FROM dataos_users WHERE username = ? OR email = ?", (login, login.lower())
        ).fetchone()
        return self._from_row(row) if row else None

    def authenticate(self, login: str, password: str) -> Optional[User]:
        user = self.get_by_login(login)
        if user is None or not verify_password(password, user.password_hash):
            return None
        return user

    def list_users(self) -> list:
        rows = self._conn.execute("SELECT * FROM dataos_users ORDER BY created_at").fetchall()
        return [self._from_row(r).to_dict() for r in rows]
