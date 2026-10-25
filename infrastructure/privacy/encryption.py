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
import tempfile
import stat
from typing import Dict, Any, Optional, Tuple
import warnings


class EncryptionEngine:
    """
    Authenticated encryption for data at rest.

    Passwords are expanded with PBKDF2. New writes use Fernet when available
    and AES-GCM as a compatible alternative. The engine fails closed when no
    authenticated-encryption backend is available; it never writes XOR
    ciphertext. Legacy XOR reads require explicit migration-only opt-in.
    """

    def __init__(
        self,
        master_key: Optional[str] = None,
        key_file: Optional[str] = None,
        *,
        allow_legacy_xor_decryption: bool = False,
    ):
        self._backend = None
        self._fernet = None
        self._aes_key = None
        self._allow_legacy_xor_decryption = allow_legacy_xor_decryption

        if master_key is not None:
            self._init_from_password(master_key)
        elif key_file is not None:
            # An explicitly selected key file is authoritative. Missing paths,
            # broken symlinks, and unreadable files must not silently fall back
            # to an unrelated environment or ephemeral key.
            self._init_from_file(key_file)
        else:
            self._init_from_env()

    def _init_from_password(self, password: str) -> None:
        """Derive encryption key from password using PBKDF2."""
        if not isinstance(password, str) or not password.strip():
            raise EncryptionError("Encryption master key must be a non-empty string")
        salt = self._get_or_create_salt()
        key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 480000, dklen=32)
        self._aes_key = key
        self._try_init_fernet(key)

    def _init_from_file(self, key_file: str) -> None:
        """Load a bounded regular key file without following symbolic links."""
        key = self._read_key_file(key_file)
        if len(key) == 32:
            self._aes_key = key
            self._try_init_fernet(key)
        else:
            try:
                password = key.decode("utf-8").strip()
            except UnicodeDecodeError as exc:
                raise EncryptionError(
                    "Encryption key file must contain 32 raw key bytes or a UTF-8 passphrase"
                ) from exc
            if not password:
                raise EncryptionError("Encryption key file passphrase must not be empty")
            self._init_from_password(password)

    @staticmethod
    def _read_key_file(key_path: str) -> bytes:
        """Read at most 4 KiB from a regular key file, rejecting symlinks."""
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        flags = os.O_RDONLY | nofollow | getattr(os, "O_BINARY", 0)
        before = None
        if not nofollow:
            try:
                before = os.lstat(key_path)
            except OSError as exc:
                raise EncryptionError("Encryption key file must be a regular non-symlink file") from exc
            if stat.S_ISLNK(before.st_mode):
                raise EncryptionError("Encryption key file must be a regular non-symlink file")

        try:
            fd = os.open(key_path, flags)
        except OSError as exc:
            raise EncryptionError("Encryption key file must be a regular non-symlink file") from exc

        try:
            metadata = os.fstat(fd)
            if not stat.S_ISREG(metadata.st_mode):
                raise EncryptionError("Encryption key file must be a regular non-symlink file")
            if before is not None:
                try:
                    current = os.lstat(key_path)
                except OSError as exc:
                    raise EncryptionError("Encryption key file changed while being opened") from exc
                if (
                    stat.S_ISLNK(current.st_mode)
                    or (current.st_dev, current.st_ino) != (metadata.st_dev, metadata.st_ino)
                ):
                    raise EncryptionError("Encryption key file changed while being opened")

            with os.fdopen(fd, "rb") as key_file:
                fd = -1
                key = key_file.read(4097)
        finally:
            if fd != -1:
                os.close(fd)

        if len(key) > 4096:
            raise EncryptionError("Encryption key file exceeds the 4 KiB limit")
        if not key:
            raise EncryptionError("Encryption key file must not be empty")
        return key

    def _init_from_env(self) -> None:
        """Initialize from DATAOS_MASTER_KEY environment variable."""
        env_key = os.environ.get("DATAOS_MASTER_KEY")
        if env_key is not None:
            # An explicitly configured but empty key is a deployment error, not
            # permission to silently switch to a different encryption key.
            self._init_from_password(env_key)
        else:
            # Treat every supported deployment environment marker as authoritative.
            # If any marker says production, never silently create an ephemeral key.
            environments = {
                os.environ.get(name, "").strip().lower()
                for name in ("DATAOS_ENV", "APP_ENV", "ENVIRONMENT")
            }
            if environments.intersection({"production", "prod"}):
                raise EncryptionError(
                    "DATAOS_MASTER_KEY must be configured in production; refusing an ephemeral key"
                )
            # Generate an ephemeral key only for local development/test data.
            # Ciphertext created with this key cannot be decrypted after restart.
            self._aes_key = os.urandom(32)
            self._try_init_fernet(self._aes_key)

    def _get_or_create_salt(self) -> bytes:
        """Load or atomically initialize the stable 16-byte key-derivation salt.

        Deployments may point DATAOS_ENCRYPTION_SALT_FILE at a persistent,
        shared file. The salt is not secret, but changing or losing it makes
        existing ciphertext derived from the same master password unreadable.
        """
        configured_path = os.environ.get("DATAOS_ENCRYPTION_SALT_FILE")
        salt_path = os.path.abspath(os.path.expanduser(
            configured_path or "~/.dataos/encryption_salt"
        ))
        salt_dir = os.path.dirname(salt_path)
        os.makedirs(salt_dir, exist_ok=True)

        # Write the complete candidate to a private temporary file first, then
        # publish it with a no-overwrite hard link. Concurrent processes that
        # initialize the same path therefore converge on the first complete
        # salt instead of racing to overwrite each other's key material.
        fd, temp_path = tempfile.mkstemp(prefix=".encryption-salt-", dir=salt_dir)
        candidate = os.urandom(16)
        try:
            with os.fdopen(fd, "wb") as salt_file:
                salt_file.write(candidate)
                salt_file.flush()
                os.fsync(salt_file.fileno())
            try:
                os.link(temp_path, salt_path)
                salt = candidate
            except FileExistsError:
                salt = self._read_existing_salt(salt_path)
        finally:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass

        if len(salt) != 16:
            raise EncryptionError(
                "Encryption salt file must contain exactly 16 bytes; restore the persistent salt before starting"
            )
        return salt

    @staticmethod
    def _read_existing_salt(salt_path: str) -> bytes:
        """Read a bounded, regular salt file without following symlinks."""
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        flags = os.O_RDONLY | nofollow | getattr(os, "O_BINARY", 0)
        before = None
        if not nofollow:
            # Platforms without O_NOFOLLOW get a lstat/open/fstat identity
            # check so a path swapped to a symlink is rejected.
            try:
                before = os.lstat(salt_path)
            except OSError as exc:
                raise EncryptionError("Encryption salt file must be a regular non-symlink file") from exc
            if stat.S_ISLNK(before.st_mode):
                raise EncryptionError("Encryption salt file must be a regular non-symlink file")

        try:
            fd = os.open(salt_path, flags)
        except OSError as exc:
            raise EncryptionError("Encryption salt file must be a regular non-symlink file") from exc

        try:
            metadata = os.fstat(fd)
            if not stat.S_ISREG(metadata.st_mode):
                raise EncryptionError("Encryption salt file must be a regular non-symlink file")
            if before is not None:
                try:
                    current = os.lstat(salt_path)
                except OSError as exc:
                    raise EncryptionError("Encryption salt file changed while being opened") from exc
                if (
                    stat.S_ISLNK(current.st_mode)
                    or (current.st_dev, current.st_ino) != (metadata.st_dev, metadata.st_ino)
                ):
                    raise EncryptionError("Encryption salt file changed while being opened")

            with os.fdopen(fd, "rb") as salt_file:
                fd = -1
                salt = salt_file.read(17)
        finally:
            if fd != -1:
                os.close(fd)

        if len(salt) != 16:
            raise EncryptionError(
                "Encryption salt file must contain exactly 16 bytes; restore the persistent salt before starting"
            )
        return salt

    def _try_init_fernet(self, key: bytes) -> None:
        """Initialize a supported authenticated-encryption backend or fail closed."""
        try:
            from cryptography.fernet import Fernet
            # Fernet needs a URL-safe base64 encoding of a 32-byte key.
            fernet_key = base64.urlsafe_b64encode(key[:32])
            self._fernet = Fernet(fernet_key)
            self._backend = "fernet"
        except ImportError:
            try:
                from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
                self._backend = "aesgcm"
            except ImportError as exc:
                self._backend = None
                raise EncryptionError(
                    "The cryptography package is required; refusing insecure fallback encryption"
                ) from exc

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a string using an authenticated-encryption backend."""
        if self._backend == "fernet" and self._fernet:
            encrypted = self._fernet.encrypt(plaintext.encode())
            return f"fernet:{encrypted.decode()}"
        if self._backend == "aesgcm":
            return self._encrypt_aes_gcm(plaintext)
        raise EncryptionError(
            "No secure encryption backend is available; refusing to encrypt with XOR"
        )

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt supported ciphertext formats; legacy XOR requires explicit opt-in."""
        if ciphertext.startswith("fernet:"):
            if not self._fernet:
                raise EncryptionError("Fernet support is unavailable for this ciphertext")
            encrypted = ciphertext[7:].encode()
            return self._fernet.decrypt(encrypted).decode()
        if ciphertext.startswith("aesgcm:"):
            try:
                # Read older AES-GCM ciphertext even when new writes use Fernet.
                return self._decrypt_aes_gcm(ciphertext)
            except ImportError as exc:
                raise EncryptionError("AES-GCM support is unavailable for this ciphertext") from exc
        if ciphertext.startswith("xor:") and self._allow_legacy_xor_decryption:
            warnings.warn(
                "Legacy XOR ciphertext is unauthenticated and insecure; decrypt only to migrate it",
                RuntimeWarning,
                stacklevel=2,
            )
            return self._decrypt_xor_fallback(ciphertext)
        if ciphertext.startswith("xor:"):
            raise EncryptionError(
                "Legacy XOR ciphertext is disabled; set allow_legacy_xor_decryption=True only for migration"
            )
        raise EncryptionError("Unsupported ciphertext format")

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
        """Decrypt recognized encrypted fields without hiding decryption failures."""
        result = dict(data)
        target_fields = fields or list(data.keys())
        encrypted_prefixes = ("fernet:", "aesgcm:", "xor:")
        for field in target_fields:
            value = result.get(field)
            if isinstance(value, str) and value.startswith(encrypted_prefixes):
                # A recognized ciphertext that cannot be decrypted is an error,
                # not an unencrypted value. Never silently pass it through.
                result[field] = self.decrypt(value)
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
