"""
Tests for Semantic Search enhancements (Rule #48).
Validates neural embeddings, filtering, batch indexing, and deletion.
"""

import unittest
import numpy as np
from engines.search.vector_index import (
    PersistentVectorIndex, TFIDFVectorEmbeddingModel,
    SentenceTransformerEmbeddingModel, BaseEmbeddingModel,
)
from core.object.model import DataObject


class TestTFIDFEmbeddingModel(unittest.TestCase):

    def setUp(self):
        self.model = TFIDFVectorEmbeddingModel(dimension=128)

    def test_encode(self):
        vecs = self.model.encode(["hello world", "test query"])
        self.assertEqual(vecs.shape, (2, 128))

    def test_encode_empty(self):
        vecs = self.model.encode([])
        self.assertEqual(vecs.shape, (0, 128))

    def test_l2_normalized(self):
        vecs = self.model.encode(["test"])
        norms = np.linalg.norm(vecs, axis=1)
        self.assertAlmostEqual(norms[0], 1.0, places=5)

    def test_properties(self):
        self.assertEqual(self.model.model_name, "tfidf_statistical")
        self.assertEqual(self.model.dimension, 128)


class TestSentenceTransformerModel(unittest.TestCase):

    def test_init(self):
        try:
            model = SentenceTransformerEmbeddingModel("all-MiniLM-L6-v2")
            self.assertIn("sentence_transformer", model.model_name)
        except ImportError:
            self.skipTest("sentence-transformers not installed")


class TestPersistentVectorIndex(unittest.TestCase):

    def setUp(self):
        self.index = PersistentVectorIndex(db_path=":memory:")

    def test_index_object(self):
        obj = DataObject(id="v1", type="document", properties={"title": "Test"}, content="Hello world")
        result = self.index.index_object(obj)
        self.assertEqual(result["object_id"], "v1")

    def test_search_similar(self):
        self.index.index_object(DataObject(id="v1", type="document", content="machine learning algorithms"))
        self.index.index_object(DataObject(id="v2", type="document", content="deep neural networks"))
        self.index.index_object(DataObject(id="v3", type="document", content="cooking recipes"))
        results = self.index.search_similar("artificial intelligence", top_k=2)
        self.assertLessEqual(len(results), 2)
        self.assertGreater(results[0]["similarity"], 0)

    def test_search_empty(self):
        results = self.index.search_similar("test")
        self.assertEqual(len(results), 0)

    def test_search_with_filter_ids(self):
        self.index.index_object(DataObject(id="v1", type="document", content="data science"))
        self.index.index_object(DataObject(id="v2", type="document", content="data engineering"))
        results = self.index.search_similar("data", object_ids=["v1"])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["object_id"], "v1")

    def test_search_min_similarity(self):
        self.index.index_object(DataObject(id="v1", type="document", content="test"))
        results = self.index.search_similar("xyz", min_similarity=0.99)
        self.assertEqual(len(results), 0)

    def test_index_batch(self):
        objects = [
            DataObject(id=f"b{i}", type="document", content=f"content {i}")
            for i in range(5)
        ]
        result = self.index.index_batch(objects)
        self.assertEqual(result["indexed"], 5)

    def test_delete_embedding(self):
        self.index.index_object(DataObject(id="d1", type="document", content="test"))
        self.assertTrue(self.index.delete_embedding("d1"))
        results = self.index.search_similar("test")
        self.assertEqual(len(results), 0)

    def test_delete_nonexistent(self):
        self.assertFalse(self.index.delete_embedding("no_such"))

    def test_get_index_stats(self):
        self.index.index_object(DataObject(id="s1", type="document", content="a"))
        stats = self.index.get_index_stats()
        self.assertEqual(stats["total_embeddings"], 1)

    def test_upsert(self):
        self.index.index_object(DataObject(id="u1", type="document", content="original"))
        self.index.index_object(DataObject(id="u1", type="document", content="updated content"))
        stats = self.index.get_index_stats()
        self.assertEqual(stats["total_embeddings"], 1)

    def test_recompute_all(self):
        from infrastructure.storage.sqlite_store import SQLiteStorage
        storage = SQLiteStorage(db_path=":memory:")
        storage.save_object(DataObject(id="r1", type="document", content="hello"))
        storage.save_object(DataObject(id="r2", type="document", content="world"))
        result = self.index.recompute_all(storage)
        self.assertEqual(result["total_recomputed"], 2)

    def test_extract_object_text(self):
        obj = DataObject(
            id="t1", type="dataset",
            properties={"filename": "data.csv", "title": "Sales Data"},
            content="revenue amounts"
        )
        text = self.index._extract_object_text(obj)
        self.assertIn("dataset", text)
        self.assertIn("data.csv", text)


class TestBaseEmbeddingModel(unittest.TestCase):

    def test_is_abstract(self):
        with self.assertRaises(TypeError):
            BaseEmbeddingModel()


if __name__ == "__main__":
    unittest.main()
