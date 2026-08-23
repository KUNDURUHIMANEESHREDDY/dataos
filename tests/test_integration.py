"""
Integration tests for DataOS system kernel with all new modules.
Verifies that new subsystems are properly wired into the DataOS kernel.
"""

import unittest
import io
import zipfile
from dataos_system import DataOS
from core.object.model import DataObject, ObjectType


class TestDataOSIntegration(unittest.TestCase):
    """Integration tests verifying all new modules work through the DataOS kernel."""

    def setUp(self):
        self.dos = DataOS(db_path=":memory:")

    def test_kernel_instantiation(self):
        """Verify DataOS kernel initializes with all new subsystems."""
        self.assertIsNotNone(self.dos.storage)
        self.assertIsNotNone(self.dos.embedding_engine)
        self.assertIsNotNone(self.dos.classifier)
        self.assertIsNotNone(self.dos.ingestion_adapters)
        self.assertIsNotNone(self.dos.privacy)
        self.assertIsNotNone(self.dos.metrics)
        self.assertIsNotNone(self.dos.rate_limiter)
        self.assertIsNotNone(self.dos.dashboard)

    def test_embed(self):
        vec = self.dos.embed("hello world")
        self.assertEqual(len(vec), 128)

    def test_embed_batch(self):
        vecs = self.dos.embed_batch(["hello", "world"])
        self.assertEqual(len(vecs), 2)
        self.assertEqual(len(vecs[0]), 128)

    def test_classify_python(self):
        result = self.dos.classify(filename="script.py")
        self.assertEqual(result["classification"], "python")

    def test_classify_csv(self):
        result = self.dos.classify(filename="data.csv")
        self.assertEqual(result["classification"], "csv")

    def test_classify_content(self):
        result = self.dos.classify(content="# Hello\n\nThis is a document.")
        self.assertIn(result["classification"], ["document", "unknown"])

    def test_ingest_archive(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("file.txt", "hello")
        result = self.dos.ingest_source("archive", {"archive_bytes": buf.getvalue()})
        self.assertEqual(result["total_files"], 1)

    def test_ingest_database(self):
        result = self.dos.ingest_source("database", {
            "db_type": "sqlite",
            "connection_string": ":memory:",
            "query": "SELECT 1 as id, 'test' as name",
        })
        self.assertEqual(result["row_count"], 1)

    def test_export_csv(self):
        data = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
        result = self.dos.export_data(data, "csv")
        self.assertEqual(result["row_count"], 2)
        self.assertIn("Alice", result["content"])

    def test_export_parquet(self):
        data = [{"id": 1}]
        result = self.dos.export_data(data, "parquet")
        self.assertIn("format", result)

    def test_mask(self):
        result = self.dos.mask("1234567890")
        self.assertEqual(result, "12******90")

    def test_rate_limit(self):
        result = self.dos.check_rate_limit("test_key")
        self.assertTrue(result["allowed"])
        self.assertIn("remaining", result)

    def test_rate_limit_exceeded(self):
        for _ in range(100):
            self.dos.check_rate_limit("key1")
        result = self.dos.check_rate_limit("key1")
        self.assertFalse(result["allowed"])

    def test_metrics(self):
        self.dos.metrics.increment("test_counter", 5)
        self.assertEqual(self.dos.metrics.get_counter("test_counter"), 5)

    def test_dashboard_capture(self):
        snap = self.dos.dashboard.capture("d1", "Test", [{"type": "kpi"}])
        self.assertEqual(snap["widget_count"], 1)

    def test_privacy_k_anonymity(self):
        records = [{"qi": "A"} for _ in range(10)]
        result = self.dos.privacy.apply_k_anonymity(records, ["qi"], k=5)
        self.assertEqual(result["kept_count"], 10)

    def test_existing_ingest(self):
        """Verify existing ingest still works."""
        obj = DataObject(id="test1", type="document", content="hello world")
        self.dos.objects.save(obj)
        found = self.dos.objects.get("test1")
        self.assertIsNotNone(found)
        self.assertEqual(found.content, "hello world")

    def test_existing_search(self):
        """Verify existing search still works."""
        obj = DataObject(id="s1", type="document", content="machine learning algorithms")
        self.dos.objects.save(obj)
        results = self.dos.search("machine learning")
        self.assertIsInstance(results, list)

    def test_existing_vector_search(self):
        """Verify existing vector search still works."""
        obj = DataObject(id="v1", type="document", content="data science and analytics")
        self.dos.objects.save(obj)
        self.dos.vector_index.index_object(obj)
        results = self.dos.search_vector("data analytics")
        self.assertIsInstance(results, list)

    def test_full_workflow(self):
        """End-to-end workflow: ingest, embed, classify, export."""
        # 1. Ingest
        obj = DataObject(id="wf1", type="dataset", content="name,age\nAlice,30\nBob,25")
        self.dos.objects.save(obj)

        # 2. Embed
        vec = self.dos.embed(obj.content)
        self.assertEqual(len(vec), 128)

        # 3. Classify
        cls_result = self.dos.classify(filename="data.csv", content=obj.content)
        self.assertIn(cls_result["classification"], ["csv", "data", "document"])

        # 4. Export
        data = [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]
        export_result = self.dos.export_data(data, "csv")
        self.assertEqual(export_result["row_count"], 2)

        # 5. Privacy
        masked = self.dos.mask("Alice Smith")
        self.assertNotIn("Alice", masked)

        # 6. Rate limit
        rl = self.dos.check_rate_limit("user1")
        self.assertTrue(rl["allowed"])


class TestDataOSNewAPIs(unittest.TestCase):
    """Test new API methods on the DataOS kernel."""

    def setUp(self):
        self.dos = DataOS(db_path=":memory:")

    def test_classify_by_content_code(self):
        result = self.dos.classify(content="def hello():\n    return 'world'")
        self.assertEqual(result["classification"], "code")

    def test_classify_by_content_data(self):
        result = self.dos.classify(content="col1,col2,col3\n1,2,3\n4,5,6\n7,8,9")
        self.assertIn(result["classification"], ["data", "unknown"])

    def test_embed_similarity(self):
        sim = self.dos.embedding_engine.similarity("hello", "hello")
        self.assertAlmostEqual(sim, 1.0, places=3)

    def test_export_unsupported(self):
        result = self.dos.export_data([{"a": 1}], "yaml")
        self.assertIn("error", result)

    def test_metrics_histogram(self):
        for v in [10, 20, 30]:
            self.dos.metrics.observe("latency", v)
        stats = self.dos.metrics.get_histogram("latency")
        self.assertEqual(stats["count"], 3)


if __name__ == "__main__":
    unittest.main()
