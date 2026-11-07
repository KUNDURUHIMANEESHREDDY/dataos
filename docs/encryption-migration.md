# DataOS encryption migration and operations

## Security contract

**Integration boundary:** `EncryptionEngine` is currently a library component and is not automatically applied to every write in the default SQLite/PostgreSQL storage adapters. This PR hardens that component; it does **not** claim that existing database files or all newly persisted records are encrypted at rest. A separate storage-adapter integration, field classification, key-rotation plan and round-trip/restore tests are required before making that production claim.

The encryption engine writes authenticated ciphertext using Fernet when available and AES-GCM otherwise. It requires the `cryptography` dependency and fails closed if neither authenticated backend is available. It never writes XOR ciphertext.

In production, any of `DATAOS_ENV`, `APP_ENV`, or `ENVIRONMENT` set to `production` or `prod` requires `DATAOS_MASTER_KEY`. A missing or empty key is a startup/configuration error. An ephemeral key is permitted only for local development/test data and must not protect data that needs to survive a process restart.

## Persistent key material

- Configure `DATAOS_MASTER_KEY` through the deployment secret manager. Never commit it, print it, or log it.
- For passphrase-derived keys, DataOS uses PBKDF2-HMAC-SHA256 with 480,000 iterations and a 16-byte salt.
- The default salt location is `~/.dataos/encryption_salt`. Set `DATAOS_ENCRYPTION_SALT_FILE` to a durable path for containerized deployments and replicas.
- The salt is not secret, but it is required to derive the same key. Back it up with deployment metadata and restore it before starting a replacement instance.
- An explicit `key_file` is authoritative. It must be a regular non-symlink file no larger than 4 KiB, containing either exactly 32 raw key bytes or a UTF-8 passphrase. Missing, unreadable, symlinked, oversized, or malformed files fail closed.

## Legacy XOR migration

Older versions could write `xor:` ciphertext when the `cryptography` package was unavailable. XOR is unauthenticated and must not be used for new writes.

The default engine rejects legacy XOR ciphertext. A controlled migration may opt in explicitly:

```python
from infrastructure.privacy.encryption import EncryptionEngine

legacy = EncryptionEngine(
    master_key=original_master_key,
    allow_legacy_xor_decryption=True,
)
current = EncryptionEngine(master_key=new_master_key)

plaintext = legacy.decrypt(legacy_ciphertext)
replacement = current.encrypt(plaintext)
```

Use this only if the original key and salt are available. If the old ciphertext was created with an ephemeral key that has been lost, it cannot be reliably recovered. Treat legacy plaintext as untrusted: verify it against an independent integrity source before replacing stored values.

Migration procedure:

1. Take and verify a restorable backup before processing any records.
2. Identify only values explicitly prefixed with `xor:`; do not guess ciphertext formats.
3. Run migration in an isolated, access-controlled job with the original key/salt and explicit legacy opt-in.
4. Decrypt each value, validate its provenance/integrity independently, and encrypt it with the current authenticated engine.
5. Verify the replacement ciphertext by decrypting it with the new engine and comparing a cryptographic digest of the plaintext.
6. Record counts and failures without logging keys, plaintext, or ciphertext.
7. Keep the original backup until the migrated dataset has passed restore and application-level acceptance.
8. Remove legacy opt-in from the migration runtime after completion.

Do not run this migration automatically at application startup. No schema rewrite or stored-data migration is included in this change.

## Key rotation

`EncryptionEngine.rotate_key()` updates the engine's active key; it does not re-encrypt records already stored by callers. A real rotation must be an explicit, backup-backed migration that decrypts each record with the old key, encrypts it with the new key, verifies it, and preserves a recoverable rollback copy until acceptance.

## Verification

The privacy test suite covers authenticated round trips, missing/empty keys, production environment markers, explicit key-file handling, symlink and size rejection, persistent salt stability, concurrent salt initialization, corrupt salt rejection, fail-closed backend behavior, and explicit legacy XOR migration opt-in.

Run:

```bash
python -m pytest tests/test_privacy.py
python -m pytest tests/ --ignore=tests/test_benchmarks.py
```
