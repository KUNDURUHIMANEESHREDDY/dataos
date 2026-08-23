"""
Tests for Governance, Sharing, Quotas & Federation (Rules #58, #61, #64, #65).
"""

import unittest
import tempfile
import os
import time
from core.object.model import DataObject, ObjectType
from core.relation.model import Relationship, RelationType
from infrastructure.storage.sqlite_store import SQLiteStorage
from engines.governance.deduplication import DuplicateDetectionEngine, compute_levenshtein_similarity, compute_minhash_jaccard
from core.governance.resource_governor import ResourceGovernor, ResourceQuota, RateLimitExceededError, QuotaExceededError
from core.permissions.sharing_tokens import SubgraphTokenManager
from infrastructure.federation.federation_engine import DataOSFederationEngine


class TestGovernanceAndFederation(unittest.TestCase):

    def setUp(self):
        self.temp_db = tempfile.mktemp(suffix=".db")
        self.storage = SQLiteStorage(db_path=self.temp_db)
        self.deduplication = DuplicateDetectionEngine(self.storage)
        self.governor = ResourceGovernor()
        self.token_manager = SubgraphTokenManager(secret_key="unit_test_secret_key")
        self.federation = DataOSFederationEngine(self.storage, local_instance_id="node_test_local")

    def tearDown(self):
        if os.path.exists(self.temp_db):
            os.remove(self.temp_db)

    def test_fuzzy_duplicate_detection(self):
        """Rule #58: Exact hash, MinHash Jaccard, and Levenshtein similarity detection."""
        # 1. Exact duplicate content
        obj_original = self.storage.save_object(DataObject(
            type="document",
            properties={"filename": "q1_summary.md", "title": "Q1 Performance Summary"},
            content="Revenue grew by 25% across all regional divisions in Q1 2026."
        ))
        obj_exact_dup = self.storage.save_object(DataObject(
            type="document",
            properties={"filename": "q1_summary_copy.md", "title": "Q1 Performance Summary Copy"},
            content="Revenue grew by 25% across all regional divisions in Q1 2026."
        ))

        # 2. Near-duplicate text (MinHash)
        obj_near_dup = self.storage.save_object(DataObject(
            type="document",
            properties={"filename": "q1_summary_v2.md", "title": "Q1 Summary Draft"},
            content="Revenue grew by 25% across regional divisions in Q1 2026, according to records."
        ))

        duplicates = self.deduplication.find_duplicates(min_similarity=0.70, auto_link_graph=True)
        self.assertTrue(len(duplicates) >= 1)

        # Check exact duplicate match
        exact_match = next((d for d in duplicates if d["is_exact_duplicate"]), None)
        self.assertIsNotNone(exact_match)
        self.assertEqual(exact_match["method"], "exact_hash")
        self.assertEqual(exact_match["similarity_score"], 1.0)

        # Check graph relationship was established
        rels = self.storage.list_relationships(source_id=obj_original.id, relation_type=RelationType.SIMILAR_TO.value) + \
               self.storage.list_relationships(target_id=obj_original.id, relation_type=RelationType.SIMILAR_TO.value)
        self.assertTrue(len(rels) >= 1)

    def test_resource_governance_and_rate_limiting(self):
        """Rule #61: Execution timeouts, query rate limits, and compute budgets."""
        quota = ResourceQuota(
            principal_id="test_rate_limited_agent",
            max_queries_per_minute=3,
            max_compute_seconds_per_hour=10.0,
            max_tokens_per_hour=500
        )
        self.governor.set_quota(quota)

        # 1. Consume 3 allowed queries
        for _ in range(3):
            status = self.governor.check_and_consume_rate_limit("test_rate_limited_agent")
            self.assertEqual(status["principal_id"], "test_rate_limited_agent")

        # 2. 4th query must raise RateLimitExceededError
        with self.assertRaises(RateLimitExceededError):
            self.governor.check_and_consume_rate_limit("test_rate_limited_agent")

        # 3. Compute budget exceed test
        with self.assertRaises(QuotaExceededError):
            self.governor.record_compute_usage("test_rate_limited_agent", duration_seconds=15.0)

        # 4. Token budget exceed test
        with self.assertRaises(QuotaExceededError):
            self.governor.record_compute_usage("test_rate_limited_agent", duration_seconds=1.0, tokens_used=1000)

    def test_cryptographically_signed_sharing_tokens(self):
        """Rule #65: Subgraph sharing tokens with HMAC-SHA256 signatures."""
        root_obj = self.storage.save_object(DataObject(type="dataset", properties={"name": "clinical_trial"}))
        child_obj = self.storage.save_object(DataObject(type="table", properties={"name": "patient_records"}))

        # 1. Issue valid sharing token
        token_str = self.token_manager.issue_token(
            issuer="admin_alice",
            subject_principal="partner_pharma",
            subgraph_root_id=root_obj.id,
            allowed_object_ids=[root_obj.id, child_obj.id],
            allowed_capabilities=["read_object", "query_sql"],
            duration_seconds=3600
        )

        # 2. Verify and decode token
        payload = self.token_manager.verify_and_decode_token(token_str)
        self.assertEqual(payload.issuer, "admin_alice")
        self.assertEqual(payload.subject_principal, "partner_pharma")
        self.assertTrue(payload.allows_object(root_obj.id))
        self.assertTrue(payload.allows_object(child_obj.id))
        self.assertFalse(payload.allows_object("unauthorized_obj_id"))
        self.assertTrue(payload.allows_capability("read_object"))
        self.assertFalse(payload.allows_capability("delete_object"))

        # 3. Tampered token verification must fail
        tampered_token = token_str[:-4] + "dead"
        with self.assertRaises(PermissionError):
            self.token_manager.verify_and_decode_token(tampered_token)

        # 4. Expired token verification must fail
        expired_token = self.token_manager.issue_token(
            issuer="admin_alice",
            subject_principal="partner_pharma",
            subgraph_root_id=root_obj.id,
            duration_seconds=-10  # Expired in past
        )
        with self.assertRaises(PermissionError):
            self.token_manager.verify_and_decode_token(expired_token)

    def test_federation_engine_peer_registry_and_search(self):
        """Rule #64: Federation peer registry and search."""
        self.storage.save_object(DataObject(
            type="dataset",
            properties={"filename": "local_astronomy_data.csv"},
            content="James Webb Space Telescope observations of exoplanets."
        ))

        # Register remote peer
        peer = self.federation.register_peer(
            peer_id="eu_central_hub",
            name="EU Central DataOS Instance",
            base_url="https://eu-dataos.example.org"
        )
        self.assertEqual(len(self.federation.list_peers()), 1)

        # Federated search (searches local + checks peer endpoints)
        fed_res = self.federation.federated_search("telescope exoplanets", top_k=5)
        self.assertTrue(fed_res["total_matches"] >= 1)
        self.assertEqual(fed_res["results"][0]["source_instance"], "node_test_local")
        self.assertTrue(fed_res["results"][0]["is_local"])


if __name__ == "__main__":
    unittest.main()
