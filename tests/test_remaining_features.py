"""
Tests for remaining features: Auto-Discovery, Privacy, Metrics, Rate Limiting, Dashboard.
"""

import unittest
import time
from infrastructure.services.remaining_features import (
    AutoDiscoveryEngine, DatasetCandidate, DiscoveryMethod,
    PrivacyEngine, PrivacyMethod,
    MetricsSystem, MetricType, MetricDefinition,
    RateLimiter,
    DashboardCapture,
)


class TestAutoDiscoveryEngine(unittest.TestCase):

    def setUp(self):
        self.engine = AutoDiscoveryEngine()

    def test_register_source(self):
        self.engine.register_source("test", lambda: [DatasetCandidate("ds1", "src", DiscoveryMethod.FILE_SYSTEM)])
        stats = self.engine.get_stats()
        self.assertEqual(stats["sources"], 1)

    def test_discover(self):
        self.engine.register_source("test", lambda: [DatasetCandidate("ds1", "src", DiscoveryMethod.FILE_SYSTEM)])
        new = self.engine.discover()
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0].name, "ds1")

    def test_discover_dedup(self):
        self.engine.register_source("s1", lambda: [DatasetCandidate("ds1", "src", DiscoveryMethod.FILE_SYSTEM)])
        self.engine.register_source("s2", lambda: [DatasetCandidate("ds1", "src2", DiscoveryMethod.API)])
        self.engine.discover()
        new = self.engine.discover()
        self.assertEqual(len(new), 0)

    def test_list_discovered(self):
        self.engine.register_source("s", lambda: [DatasetCandidate("ds1", "src", DiscoveryMethod.FILE_SYSTEM)])
        self.engine.discover()
        discovered = self.engine.list_discovered()
        self.assertEqual(len(discovered), 1)

    def test_discover_error(self):
        self.engine.register_source("bad", lambda: (_ for _ in ()).throw(ValueError("fail")))
        new = self.engine.discover()
        self.assertEqual(len(new), 0)


class TestPrivacyEngine(unittest.TestCase):

    def setUp(self):
        self.privacy = PrivacyEngine(epsilon=1.0)

    def test_masking(self):
        result = self.privacy.apply_masking("1234567890")
        self.assertEqual(result, "12******90")

    def test_masking_short(self):
        result = self.privacy.apply_masking("ab")
        self.assertEqual(result, "ab")

    def test_email_masking(self):
        result = self.privacy.apply_email_masking("alice@example.com")
        self.assertIn("@example.com", result)
        self.assertNotIn("alice", result)

    def test_k_anonymity(self):
        records = [
            {"qi": "A", "val": 1}, {"qi": "A", "val": 2},
            {"qi": "B", "val": 3}, {"qi": "B", "val": 4},
            {"qi": "C", "val": 5},
        ]
        result = self.privacy.apply_k_anonymity(records, ["qi"], k=2)
        self.assertEqual(result["kept_count"], 4)
        self.assertEqual(result["suppressed_count"], 1)

    def test_differential_privacy(self):
        result = self.privacy.apply_differential_privacy([100.0, 200.0], sensitivity=1.0)
        self.assertEqual(len(result["noisy_values"]), 2)
        self.assertNotEqual(result["noisy_values"][0], 100.0)

    def test_tokenization(self):
        result = self.privacy.apply_tokenization(["alice", "bob", "alice"])
        self.assertEqual(len(result["token_map"]), 2)
        self.assertEqual(len(result["tokenized_values"]), 3)

    def test_column_masking(self):
        records = [{"name": "Alice Smith"}, {"name": "Bob Jones"}]
        result = self.privacy.apply_column_masking(records, "name")
        self.assertNotIn("Alice", result[0]["name"])

    def test_column_hash(self):
        records = [{"ssn": "123-45-6789"}]
        result = self.privacy.apply_column_masking(records, "ssn", method="hash")
        self.assertNotEqual(result[0]["ssn"], "123-45-6789")


class TestMetricsSystem(unittest.TestCase):

    def setUp(self):
        self.metrics = MetricsSystem()

    def test_define(self):
        m = self.metrics.define("requests", MetricType.COUNTER, description="Total requests")
        self.assertEqual(m.name, "requests")

    def test_increment(self):
        self.metrics.define("req", MetricType.COUNTER)
        self.metrics.increment("req")
        self.metrics.increment("req", 5)
        self.assertEqual(self.metrics.get_counter("req"), 6)

    def test_gauge(self):
        self.metrics.define("temp", MetricType.GAUGE)
        self.metrics.set_gauge("temp", 72.5)
        self.assertEqual(self.metrics.get_gauge("temp"), 72.5)

    def test_histogram(self):
        self.metrics.define("latency", MetricType.HISTOGRAM)
        for v in [10, 20, 30, 40, 50]:
            self.metrics.observe("latency", v)
        stats = self.metrics.get_histogram("latency")
        self.assertEqual(stats["count"], 5)
        self.assertEqual(stats["min"], 10)
        self.assertEqual(stats["max"], 50)

    def test_snapshot(self):
        self.metrics.increment("a")
        self.metrics.set_gauge("b", 42)
        snap = self.metrics.snapshot()
        self.assertIn("a", snap["counters"])

    def test_list_definitions(self):
        self.metrics.define("x", MetricType.COUNTER)
        defs = self.metrics.list_definitions()
        self.assertEqual(len(defs), 1)

    def test_reset(self):
        self.metrics.increment("a")
        self.metrics.reset()
        self.assertEqual(self.metrics.get_counter("a"), 0)


class TestRateLimiter(unittest.TestCase):

    def setUp(self):
        self.limiter = RateLimiter(max_requests=3, window_seconds=60)

    def test_allow(self):
        result = self.limiter.allow("key1")
        self.assertTrue(result["allowed"])
        self.assertEqual(result["remaining"], 2)

    def test_block(self):
        for _ in range(3):
            self.limiter.allow("key1")
        result = self.limiter.allow("key1")
        self.assertFalse(result["allowed"])
        self.assertIn("retry_after_seconds", result)

    def test_separate_keys(self):
        for _ in range(3):
            self.limiter.allow("key1")
        result = self.limiter.allow("key2")
        self.assertTrue(result["allowed"])

    def test_get_usage(self):
        self.limiter.allow("key1")
        usage = self.limiter.get_usage("key1")
        self.assertEqual(usage["current_requests"], 1)

    def test_reset_key(self):
        self.limiter.allow("key1")
        self.limiter.reset("key1")
        usage = self.limiter.get_usage("key1")
        self.assertEqual(usage["current_requests"], 0)

    def test_reset_all(self):
        self.limiter.allow("k1")
        self.limiter.allow("k2")
        self.limiter.reset()
        stats = self.limiter.get_stats()
        self.assertEqual(stats["total_keys"], 0)


class TestDashboardCapture(unittest.TestCase):

    def setUp(self):
        self.capture = DashboardCapture()

    def test_capture(self):
        widgets = [{"type": "chart", "title": "Revenue"}]
        snap = self.capture.capture("d1", "Sales Dashboard", widgets)
        self.assertEqual(snap["widget_count"], 1)

    def test_get_snapshot(self):
        self.capture.capture("d1", "D", [{"type": "kpi"}])
        snap = self.capture.get_snapshot()
        self.assertIsNotNone(snap)

    def test_list_snapshots(self):
        self.capture.capture("d1", "D1", [])
        self.capture.capture("d2", "D2", [])
        self.assertEqual(len(self.capture.list_snapshots()), 2)

    def test_get_stats(self):
        self.capture.capture("d1", "D", [])
        stats = self.capture.get_stats()
        self.assertEqual(stats["total_snapshots"], 1)


class TestDiscoveryMethod(unittest.TestCase):

    def test_values(self):
        self.assertEqual(DiscoveryMethod.FILE_SYSTEM.value, "file_system")
        self.assertEqual(DiscoveryMethod.DATABASE.value, "database")


class TestPrivacyMethod(unittest.TestCase):

    def test_values(self):
        self.assertEqual(PrivacyMethod.K_ANONYMITY.value, "k_anonymity")
        self.assertEqual(PrivacyMethod.MASKING.value, "masking")


class TestMetricType(unittest.TestCase):

    def test_values(self):
        self.assertEqual(MetricType.COUNTER.value, "counter")
        self.assertEqual(MetricType.HISTOGRAM.value, "histogram")


if __name__ == "__main__":
    unittest.main()
