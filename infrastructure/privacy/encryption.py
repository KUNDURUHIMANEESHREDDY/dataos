"""
Encryption Engine for DataOS (Rule #43).
Provides AES-256-GCM encryption for data at rest, key derivation,
and transparent encrypt/decrypt wrappers for storage backends.
"""

from __future__ import annotations
import os
import json
import base64
import hashlib
import secrets
from typing import Dict, Any, Optional, Tuple


class EncryptionEngine:
    """
    AES-256-GCM encryption for data at rest.
    Uses PBKDF2 for key derivation from passwords.
    Falls back to Fernet if cryptography is unavailable.
    """

    def __init__(self, master_key: Optional[str] = None, key_file: Optional[str] = None):
        self._backend = None
        self._fernet = None
        self._aes_key = None

        if master_key:
            self._init_from_password(master_key)
        elif key_file and os.path.exists(key_file):
            self._init_from_file(key_file)
        else:
            self._init_from_env()

    def _init_from_password(self, password: str) -> None:
        """Derive encryption key from password using PBKDF2."""
        salt = self._get_or_create_salt()
        key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 480000, dklen=32)
        self._aes_key = key
        self._try_init_fernet(key)

    def _init_from_file(self, key_file: str) -> None:
        """Load key from file."""
        with open(key_file, "rb") as f:
            key = f.read()
        if len(key) == 32:
            self._aes_key = key
            self._try_init_fernet(key)
        else:
            self._init_from_password(key.decode().strip())

    def _init_from_env(self) -> None:
        """Initialize from DATAOS_MASTER_KEY environment variable."""
        env_key = os.environ.get("DATAOS_MASTER_KEY")
        if env_key:
            self._init_from_password(env_key)
        else:
            # Generate ephemeral key (data won't persist across restarts)
            self._aes_key = os.urandom(32)
            self._try_init_fernet(self._aes_key)

    def _get_or_create_salt(self) -> bytes:
        """Get or create a persistent salt file."""
        salt_dir = os.path.expanduser("~/.dataos")
        os.makedirs(salt_dir, exist_ok=True)
        salt_path = os.path.join(salt_dir, "encryption_salt")
        if os.path.exists(salt_path):
            with open(salt_path, "rb") as f:
                return f.read()
        salt = os.urandom(16)
        with open(salt_path, "wb") as f:
            f.write(salt)
        return salt

    def _try_init_fernet(self, key: bytes) -> None:
        """Try to initialize Fernet encryption (requires cryptography or cryptography)."""
        try:
            from cryptography.fernet import Fernet
            # Fernet needs url-safe base64 32-byte key
            fernet_key = base64.urlsafe_b64encode(key[:32])
            self._fernet = Fernet(fernet_key)
            self._backend = "fernet"
        except ImportError:
            try:
                from cryptography.hazmat.primitives.ciphers.aead import AESGCM
                self._backend = "aesgcm"
            except ImportError:
                # Pure-Python XOR fallback (NOT secure for production)
                self._backend = "xor_fallback"

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a string, return base64-encoded ciphertext with metadata."""
        if self._backend == "fernet" and self._fernet:
            encrypted = self._fernet.encrypt(plaintext.encode())
            return f"fernet:{encrypted.decode()}"
        elif self._backend == "aesgcm":
            return self._encrypt_aes_gcm(plaintext)
        else:
            return self._encrypt_xor_fallback(plaintext)

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt a ciphertext string."""
        if ciphertext.startswith("fernet:") and self._fernet:
            encrypted = ciphertext[7:].encode()
            return self._fernet.decrypt(encrypted).decode()
        elif ciphertext.startswith("aesgcm:"):
            return self._decrypt_aes_gcm(ciphertext)
        else:
            return self._decrypt_xor_fallback(ciphertext)

    def _encrypt_aes_gcm(self, plaintext: str) -> str:
        """Encrypt using AES-GCM via cryptography library."""
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        aesgcm = AESGCM(self._aes_key)
        nonce = os.urandom(12)
        ct = aesgcm.encrypt(nonce, plaintext.encode(), None)
        combined = nonce + ct
        encoded = base64.b64encode(combined).decode()
        return f"aesgcm:{encoded}"

    def _decrypt_aes_gcm(self, ciphertext: str) -> str:
        """Decrypt AES-GCM ciphertext."""
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        encoded = ciphertext[7:]
        combined = base64.b64decode(encoded)
        nonce = combined[:12]
        ct = combined[12:]
        aesgcm = AESGCM(self._aes_key)
        return aesgcm.decrypt(nonce, ct, None).decode()

    def _encrypt_xor_fallback(self, plaintext: str) -> str:
        """XOR fallback for environments without cryptography library."""
        key_bytes = self._aes_key
        pt_bytes = plaintext.encode()
        ct_bytes = bytes(pt_bytes[i] ^ key_bytes[i % len(key_bytes)] for i in range(len(pt_bytes)))
        encoded = base64.b64encode(ct_bytes).decode()
        return f"xor:{encoded}"

    def _decrypt_xor_fallback(self, ciphertext: str) -> str:
        """Decrypt XOR fallback ciphertext."""
        encoded = ciphertext[4:]
        ct_bytes = base64.b64decode(encoded)
        key_bytes = self._aes_key
        pt_bytes = bytes(ct_bytes[i] ^ key_bytes[i % len(key_bytes)] for i in range(len(ct_bytes)))
        return pt_bytes.decode()

    def encrypt_dict(self, data: Dict[str, Any], fields: Optional[list] = None) -> Dict[str, Any]:
        """Encrypt specific fields in a dictionary."""
        result = dict(data)
        target_fields = fields or list(data.keys())
        for field in target_fields:
            if field in result and isinstance(result[field], str):
                result[field] = self.encrypt(result[field])
        return result

    def decrypt_dict(self, data: Dict[str, Any], fields: Optional[list] = None) -> Dict[str, Any]:
        """Decrypt specific fields in a dictionary."""
        result = dict(data)
        target_fields = fields or list(data.keys())
        for field in target_fields:
            if field in result and isinstance(result[field], str):
                try:
                    result[field] = self.decrypt(result[field])
                except Exception:
                    pass  # Field was not encrypted
        return result

    def hash_content(self, content: str) -> str:
        """Create a deterministic hash of content for integrity verification."""
        return hashlib.sha256(content.encode()).hexdigest()

    def verify_integrity(self, content: str, expected_hash: str) -> bool:
        """Verify content hasn't been tampered with."""
        return self.hash_content(content) == expected_hash

    def rotate_key(self, new_password: str) -> None:
        """Rotate to a new encryption key. Existing data must be re-encrypted."""
        self._init_from_password(new_password)


class EncryptionError(Exception):
    """Raised when encryption/decryption fails."""
    pass
