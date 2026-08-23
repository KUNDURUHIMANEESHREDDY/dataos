"""
Tests for Privacy (Rule #43).
Validates encryption, selective sharing, tokens, and private execution contexts.
"""

import unittest
import os
from infrastructure.privacy.encryption import EncryptionEngine
from infrastructure.privacy.sharing import (
    SelectiveSharingManager, SharingToken, SharingLevel, PrivateExecutionContext
)


class TestEncryptionEngine(unittest.TestCase):

    def setUp(self):
        self.engine = EncryptionEngine(master_key="test_password_123")

    def test_encrypt_decrypt_string(self):
        plaintext = "Hello DataOS"
        ciphertext = self.engine.encrypt(plaintext)
        self.assertNotEqual(plaintext, ciphertext)
        decrypted = self.engine.decrypt(ciphertext)
        self.assertEqual(decrypted, plaintext)

    def test_encrypt_decrypt_unicode(self):
        plaintext = "Hello 世界 🌍"
        ciphertext = self.engine.encrypt(plaintext)
        decrypted = self.engine.decrypt(ciphertext)
        self.assertEqual(decrypted, plaintext)

    def test_encrypt_decrypt_empty(self):
        plaintext = ""
        ciphertext = self.engine.encrypt(plaintext)
        decrypted = self.engine.decrypt(ciphertext)
        self.assertEqual(decrypted, plaintext)

    def test_encrypt_dict(self):
        data = {"name": "Alice", "email": "alice@example.com", "age": 30}
        encrypted = self.engine.encrypt_dict(data, fields=["name", "email"])
        self.assertNotEqual(encrypted["name"], "Alice")
        self.assertNotEqual(encrypted["email"], "alice@example.com")
        self.assertEqual(encrypted["age"], 30)
        decrypted = self.engine.decrypt_dict(encrypted, fields=["name", "email"])
        self.assertEqual(decrypted["name"], "Alice")
        self.assertEqual(decrypted["email"], "alice@example.com")

    def test_hash_content(self):
        h = self.engine.hash_content("test content")
        self.assertEqual(len(h), 64)  # SHA-256 hex
        self.assertEqual(h, self.engine.hash_content("test content"))

    def test_verify_integrity(self):
        content = "important data"
        h = self.engine.hash_content(content)
        self.assertTrue(self.engine.verify_integrity(content, h))
        self.assertFalse(self.engine.verify_integrity("tampered data", h))

    def test_ephemeral_key(self):
        engine = EncryptionEngine()
        ct = engine.encrypt("data")
        pt = engine.decrypt(ct)
        self.assertEqual(pt, "data")

    def test_key_rotation(self):
        ct1 = self.engine.encrypt("before rotation")
        self.engine.rotate_key("new_password_456")
        ct2 = self.engine.encrypt("after rotation")
        pt2 = self.engine.decrypt(ct2)
        self.assertEqual(pt2, "after rotation")


class TestSharingToken(unittest.TestCase):

    def test_token_creation(self):
        token = SharingToken(
            grantor_id="user_1",
            grantee_id="user_2",
            object_ids=["obj_a", "obj_b"],
            level=SharingLevel.SHARED_READ,
        )
        self.assertIsNotNone(token.token_id)
        self.assertTrue(token.is_valid())

    def test_token_value(self):
        token = SharingToken(grantor_id="u1", grantee_id="u2", object_ids=["o1"])
        val = token.token_value
        self.assertEqual(len(val), 48)

    def test_can_access(self):
        token = SharingToken(grantor_id="u1", grantee_id="u2", object_ids=["o1", "o2"])
        self.assertTrue(token.can_access("o1"))
        self.assertTrue(token.can_access("o2"))
        self.assertFalse(token.can_access("o3"))

    def test_write_access(self):
        token = SharingToken(
            grantor_id="u1", grantee_id="u2", object_ids=["o1"],
            level=SharingLevel.SHARED_READ,
        )
        self.assertTrue(token.can_access("o1", write=False))
        self.assertFalse(token.can_access("o1", write=True))

    def test_write_access_granted(self):
        token = SharingToken(
            grantor_id="u1", grantee_id="u2", object_ids=["o1"],
            level=SharingLevel.SHARED_WRITE,
        )
        self.assertTrue(token.can_access("o1", write=True))

    def test_revoke(self):
        token = SharingToken(grantor_id="u1", grantee_id="u2", object_ids=["o1"])
        self.assertTrue(token.is_valid())
        token.revoke()
        self.assertFalse(token.is_valid())

    def test_expiry(self):
        token = SharingToken(
            grantor_id="u1", grantee_id="u2", object_ids=["o1"],
            expires_in_hours=-1,  # Expired
        )
        self.assertFalse(token.is_valid())

    def test_to_dict(self):
        token = SharingToken(grantor_id="u1", grantee_id="u2", object_ids=["o1"])
        d = token.to_dict()
        self.assertEqual(d["grantor_id"], "u1")
        self.assertEqual(d["grantee_id"], "u2")
        self.assertFalse(d["revoked"])


class TestPrivateExecutionContext(unittest.TestCase):

    def test_create_context(self):
        ctx = PrivateExecutionContext(owner_id="user_1")
        self.assertIsNotNone(ctx.context_id)
        self.assertFalse(ctx._closed)

    def test_grant_and_check_access(self):
        ctx = PrivateExecutionContext(owner_id="user_1")
        ctx.grant_access("obj_1")
        self.assertTrue(ctx.can_access("obj_1"))
        self.assertFalse(ctx.can_access("obj_2"))

    def test_revoke_access(self):
        ctx = PrivateExecutionContext(owner_id="user_1")
        ctx.grant_access("obj_1")
        ctx.revoke_access("obj_1")
        self.assertFalse(ctx.can_access("obj_1"))

    def test_close_context(self):
        ctx = PrivateExecutionContext(owner_id="user_1")
        ctx.grant_access("obj_1")
        ctx.close()
        self.assertFalse(ctx.can_access("obj_1"))

    def test_operations_after_close_raises(self):
        ctx = PrivateExecutionContext(owner_id="user_1")
        ctx.close()
        with self.assertRaises(RuntimeError):
            ctx.grant_access("obj_1")

    def test_audit_log(self):
        ctx = PrivateExecutionContext(owner_id="user_1")
        ctx.grant_access("obj_1")
        ctx.record_operation("query", {"sql": "SELECT * FROM t"})
        log = ctx.get_audit_log()
        self.assertEqual(len(log), 2)
        self.assertEqual(log[0]["operation"], "grant_access")
        self.assertEqual(log[1]["operation"], "query")

    def test_to_dict(self):
        ctx = PrivateExecutionContext(owner_id="user_1")
        ctx.grant_access("obj_1")
        d = ctx.to_dict()
        self.assertEqual(d["owner_id"], "user_1")
        self.assertIn("obj_1", d["accessible_objects"])


class TestSelectiveSharingManager(unittest.TestCase):

    def setUp(self):
        self.manager = SelectiveSharingManager()

    def test_create_token(self):
        token = self.manager.create_token("u1", "u2", ["o1", "o2"])
        self.assertIsNotNone(token.token_id)
        self.assertEqual(token.level, SharingLevel.SHARED_READ)

    def test_revoke_token(self):
        token = self.manager.create_token("u1", "u2", ["o1"])
        self.assertTrue(self.manager.revoke_token(token.token_id))
        self.assertFalse(token.is_valid())

    def test_get_tokens_for_grantee(self):
        self.manager.create_token("u1", "u2", ["o1"])
        self.manager.create_token("u1", "u3", ["o2"])
        tokens = self.manager.get_tokens_for_grantee("u2")
        self.assertEqual(len(tokens), 1)

    def test_get_tokens_for_object(self):
        self.manager.create_token("u1", "u2", ["o1", "o2"])
        self.manager.create_token("u1", "u3", ["o2", "o3"])
        tokens = self.manager.get_tokens_for_object("o2")
        self.assertEqual(len(tokens), 2)

    def test_check_access(self):
        token = self.manager.create_token("u1", "u2", ["o1"])
        self.assertTrue(self.manager.check_access(token.token_id, "o1"))
        self.assertFalse(self.manager.check_access(token.token_id, "o2"))

    def test_create_context(self):
        ctx = self.manager.create_context("u1", ["o1", "o2"])
        self.assertTrue(ctx.can_access("o1"))
        self.assertTrue(ctx.can_access("o2"))
        self.assertFalse(ctx.can_access("o3"))

    def test_close_context(self):
        ctx = self.manager.create_context("u1", ["o1"])
        self.assertTrue(self.manager.close_context(ctx.context_id))
        self.assertFalse(ctx.can_access("o1"))

    def test_access_policies(self):
        self.manager.set_access_policy("policy_1", {"level": "read_only", "objects": ["o1"]})
        policy = self.manager.get_access_policy("policy_1")
        self.assertIsNotNone(policy)
        self.assertEqual(policy["level"], "read_only")
        policies = self.manager.list_policies()
        self.assertEqual(len(policies), 1)

    def test_stats(self):
        self.manager.create_token("u1", "u2", ["o1"])
        t2 = self.manager.create_token("u1", "u3", ["o2"])
        self.manager.revoke_token(t2.token_id)
        self.manager.create_context("u1", ["o1"])
        stats = self.manager.get_stats()
        self.assertEqual(stats["total_tokens"], 2)
        self.assertEqual(stats["active_tokens"], 1)
        self.assertEqual(stats["revoked_tokens"], 1)
        self.assertEqual(stats["total_contexts"], 1)


if __name__ == "__main__":
    unittest.main()
