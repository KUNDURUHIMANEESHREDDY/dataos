"""
Tests for Embeddings API and AI Classification (Rules #47, #49).
Validates embedding providers, registry, classification, and batching.
"""

import unittest
from intelligence.semantic.embeddings_api import (
    EmbeddingRegistry, EmbeddingEngine, HashEmbeddingProvider,
    ContentClassifier, ContentType, ClassificationRule,
)


class TestHashEmbeddingProvider(unittest.TestCase):

    def setUp(self):
        self.provider = HashEmbeddingProvider(dimension=64)

    def test_embed(self):
        vecs = self.provider.embed(["hello", "world"])
        self.assertEqual(len(vecs), 2)
        self.assertEqual(len(vecs[0]), 64)

    def test_dimension(self):
        self.assertEqual(self.provider.dimension(), 64)

    def test_name(self):
        self.assertEqual(self.provider.name, "hash_v1")

    def test_is_available(self):
        self.assertTrue(self.provider.is_available)

    def test_l2_normalized(self):
        vecs = self.provider.embed(["test"])
        norm = sum(v * v for v in vecs[0]) ** 0.5
        self.assertAlmostEqual(norm, 1.0, places=5)


class TestEmbeddingRegistry(unittest.TestCase):

    def setUp(self):
        self.registry = EmbeddingRegistry()

    def test_register(self):
        self.registry.register(HashEmbeddingProvider(32))
        self.assertIsNotNone(self.registry.get())

    def test_get_by_name(self):
        self.registry.register(HashEmbeddingProvider(32))
        p = self.registry.get("hash_v1")
        self.assertIsNotNone(p)

    def test_list_providers(self):
        self.registry.register(HashEmbeddingProvider(32))
        providers = self.registry.list_providers()
        self.assertEqual(len(providers), 1)

    def test_set_default(self):
        self.registry.register(HashEmbeddingProvider(32))
        self.assertTrue(self.registry.set_default("hash_v1"))
        self.assertFalse(self.registry.set_default("nonexistent"))

    def test_default_is_first(self):
        self.registry.register(HashEmbeddingProvider(32))
        self.assertEqual(self.registry.get().name, "hash_v1")


class TestEmbeddingEngine(unittest.TestCase):

    def setUp(self):
        self.engine = EmbeddingEngine(HashEmbeddingProvider(64))

    def test_embed(self):
        vec = self.engine.embed("hello")
        self.assertEqual(len(vec), 64)

    def test_embed_caching(self):
        vec1 = self.engine.embed("test")
        vec2 = self.engine.embed("test")
        self.assertEqual(vec1, vec2)

    def test_embed_batch(self):
        vecs = self.engine.embed_batch(["a", "b", "c"])
        self.assertEqual(len(vecs), 3)

    def test_similarity(self):
        sim = self.engine.similarity("hello", "hello")
        self.assertAlmostEqual(sim, 1.0, places=3)

    def test_find_nearest(self):
        results = self.engine.find_nearest("test", ["test one", "test two", "unrelated"], top_k=2)
        self.assertEqual(len(results), 2)
        self.assertIn(results[0]["text"], ["test one", "test two"])

    def test_set_provider(self):
        self.engine.set_provider(HashEmbeddingProvider(32))
        vec = self.engine.embed("test")
        self.assertEqual(len(vec), 32)

    def test_stats(self):
        stats = self.engine.get_stats()
        self.assertIn("provider", stats)


class TestContentClassifier(unittest.TestCase):

    def setUp(self):
        self.classifier = ContentClassifier()

    def test_classify_python(self):
        result = self.classifier.classify_by_filename("script.py")
        self.assertEqual(result["classification"], "python")

    def test_classify_csv(self):
        result = self.classifier.classify_by_filename("data.csv")
        self.assertEqual(result["classification"], "csv")

    def classif_by_content_code(self):
        result = self.classifier.classify_by_content("def hello():\n    return 'world'")
        self.assertEqual(result["classification"], "code")

    def test_classify_by_content_data(self):
        result = self.classifier.classify_by_content("name,age,address\nAlice,30,NYC\nBob,25,LA\nCharlie,35,SF")
        self.assertIn(result["classification"], ["data", "unknown"])

    def test_classify_by_content_document(self):
        content = "# Title\n\nThis is a long document with many words. " * 20
        result = self.classifier.classify_by_content(content)
        self.assertEqual(result["classification"], "document")

    def test_classify_combined(self):
        result = self.classifier.classify(filename="data.py", content="def main(): pass")
        self.assertEqual(result["classification"], "python")

    def test_classify_unknown(self):
        result = self.classifier.classify_by_content("x")
        self.assertEqual(result["classification"], "unknown")

    def test_classify_no_extension(self):
        result = self.classifier.classify_by_filename("Makefile")
        self.assertEqual(result["classification"], "unknown")

    def test_get_stats(self):
        stats = self.classifier.get_stats()
        self.assertGreater(stats["total_rules"], 0)


class TestClassificationRule(unittest.TestCase):

    def test_rule(self):
        rule = ClassificationRule("test", pattern="*.py", keywords=["def"], confidence=0.9)
        self.assertEqual(rule.name, "test")
        self.assertEqual(rule.confidence, 0.9)


class TestContentType(unittest.TestCase):

    def test_values(self):
        self.assertEqual(ContentType.DOCUMENT.value, "document")
        self.assertEqual(ContentType.CODE.value, "code")


if __name__ == "__main__":
    unittest.main()
