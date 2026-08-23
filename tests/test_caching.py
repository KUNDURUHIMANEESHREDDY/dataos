"""
Tests for Dependency-Aware Caching (Rule #62).
Validates LRU eviction, TTL expiration, dependency invalidation, and statistics.
"""

import unittest
import time
import threading
from infrastructure.caching.cache import DependencyAwareCache, CacheEntry


class TestDependencyAwareCache(unittest.TestCase):

    def setUp(self):
        self.cache = DependencyAwareCache(max_size=5, default_ttl=60)

    def test_put_and_get(self):
        self.cache.put("key1", "value1")
        self.assertEqual(self.cache.get("key1"), "value1")

    def test_get_miss(self):
        self.assertIsNone(self.cache.get("nonexistent"))

    def test_overwrite(self):
        self.cache.put("key1", "v1")
        self.cache.put("key1", "v2")
        self.assertEqual(self.cache.get("key1"), "v2")

    def test_lru_eviction(self):
        cache = DependencyAwareCache(max_size=3, default_ttl=60)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("c", 3)
        # Access 'a' to make it recently used
        cache.get("a")
        # Adding 'd' should evict 'b' (least recently used)
        cache.put("d", 4)
        self.assertIsNone(cache.get("b"))
        self.assertEqual(cache.get("a"), 1)
        self.assertEqual(cache.get("d"), 4)

    def test_ttl_expiration(self):
        cache = DependencyAwareCache(default_ttl=1)
        cache.put("key1", "value1", ttl=0)  # Expire immediately
        time.sleep(0.01)
        self.assertIsNone(cache.get("key1"))

    def test_ttl_none_never_expires(self):
        cache = DependencyAwareCache(default_ttl=None)
        cache.put("key1", "value1", ttl=None)
        self.assertEqual(cache.get("key1"), "value1")

    def test_dependency_invalidation(self):
        cache = DependencyAwareCache(default_ttl=60)
        cache.put("parent", "data", dependencies=set())
        cache.put("child1", "derived1", dependencies={"parent"})
        cache.put("child2", "derived2", dependencies={"parent"})
        cache.put("unrelated", "other", dependencies=set())

        cache.invalidate("parent")
        self.assertIsNone(cache.get("parent"))
        self.assertIsNone(cache.get("child1"))
        self.assertIsNone(cache.get("child2"))
        self.assertEqual(cache.get("unrelated"), "other")

    def test_transitive_dependency_invalidation(self):
        cache = DependencyAwareCache(default_ttl=60)
        cache.put("root", "r", dependencies=set())
        cache.put("level1", "l1", dependencies={"root"})
        cache.put("level2", "l2", dependencies={"level1"})

        cache.invalidate("root")
        self.assertIsNone(cache.get("root"))
        self.assertIsNone(cache.get("level1"))
        self.assertIsNone(cache.get("level2"))

    def test_tag_invalidation(self):
        cache = DependencyAwareCache(default_ttl=60)
        cache.put("a", 1, tags={"dataset"})
        cache.put("b", 2, tags={"dataset"})
        cache.put("c", 3, tags={"document"})

        count = cache.invalidate_by_tag("dataset")
        self.assertEqual(count, 2)
        self.assertIsNone(cache.get("a"))
        self.assertIsNone(cache.get("b"))
        self.assertEqual(cache.get("c"), 3)

    def test_invalidate_all(self):
        cache = DependencyAwareCache(default_ttl=60)
        cache.put("a", 1)
        cache.put("b", 2)
        count = cache.invalidate_all()
        self.assertEqual(count, 2)
        self.assertIsNone(cache.get("a"))
        self.assertIsNone(cache.get("b"))

    def test_get_or_put(self):
        call_count = [0]
        def factory():
            call_count[0] += 1
            return "computed_value"

        result = self.cache.get_or_put("key1", factory)
        self.assertEqual(result, "computed_value")
        self.assertEqual(call_count[0], 1)

        # Second call should use cache
        result = self.cache.get_or_put("key1", factory)
        self.assertEqual(result, "computed_value")
        self.assertEqual(call_count[0], 1)

    def test_exists(self):
        self.cache.put("key1", "value1")
        self.assertTrue(self.cache.exists("key1"))
        self.assertFalse(self.cache.exists("nonexistent"))

    def test_keys(self):
        self.cache.put("a", 1)
        self.cache.put("b", 2)
        self.cache.put("c", 3)
        keys = self.cache.keys()
        self.assertEqual(len(keys), 3)
        self.assertIn("a", keys)

    def test_get_entry(self):
        self.cache.put("key1", "value1", tags={"tag1"}, dependencies={"dep1"})
        entry = self.cache.get_entry("key1")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["key"], "key1")
        self.assertEqual(entry["access_count"], 0)
        self.assertIn("tag1", entry["tags"])

    def test_get_dependents(self):
        self.cache.put("parent", "p", dependencies=set())
        self.cache.put("child1", "c1", dependencies={"parent"})
        self.cache.put("child2", "c2", dependencies={"parent"})
        deps = self.cache.get_dependents("parent")
        self.assertEqual(deps, {"child1", "child2"})

    def test_stats(self):
        cache = DependencyAwareCache(default_ttl=60)
        cache.put("a", 1)
        cache.get("a")  # hit
        cache.get("miss")  # miss
        stats = cache.get_stats()
        self.assertEqual(stats["hits"], 1)
        self.assertEqual(stats["misses"], 1)
        self.assertEqual(stats["size"], 1)
        self.assertEqual(stats["hit_rate_percent"], 50.0)

    def test_cleanup_expired(self):
        cache = DependencyAwareCache(default_ttl=0)
        cache.put("a", 1)
        cache.put("b", 2)
        time.sleep(0.01)
        count = cache.cleanup_expired()
        self.assertEqual(count, 2)

    def test_thread_safety(self):
        cache = DependencyAwareCache(max_size=100, default_ttl=60)

        def writer():
            for i in range(50):
                cache.put(f"key_{i}", i)

        def reader():
            for i in range(50):
                cache.get(f"key_{i}")

        threads = [threading.Thread(target=writer) for _ in range(3)]
        threads += [threading.Thread(target=reader) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        stats = cache.get_stats()
        self.assertGreater(stats["total_requests"], 0)

    def test_custom_ttl(self):
        cache = DependencyAwareCache(default_ttl=60)
        cache.put("short", "v", ttl=0)
        cache.put("long", "v", ttl=3600)
        time.sleep(0.01)
        self.assertIsNone(cache.get("short"))
        self.assertEqual(cache.get("long"), "v")


class TestCacheEntry(unittest.TestCase):

    def test_basic_entry(self):
        entry = CacheEntry(key="k", value="v", ttl_seconds=60)
        self.assertEqual(entry.key, "k")
        self.assertFalse(entry.is_expired)
        self.assertEqual(entry.version, 1)

    def test_entry_touch(self):
        entry = CacheEntry(key="k", value="v")
        entry.touch()
        self.assertEqual(entry.access_count, 1)
        entry.touch()
        self.assertEqual(entry.access_count, 2)

    def test_entry_expired(self):
        entry = CacheEntry(key="k", value="v", ttl_seconds=0)
        time.sleep(0.01)
        self.assertTrue(entry.is_expired)

    def test_entry_to_dict(self):
        entry = CacheEntry(key="k", value="v", tags={"t1"}, dependencies={"d1"})
        d = entry.to_dict()
        self.assertEqual(d["key"], "k")
        self.assertIn("t1", d["tags"])
        self.assertIn("d1", d["dependencies"])


if __name__ == "__main__":
    unittest.main()
