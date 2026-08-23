"""
Performance Benchmarks for DataOS.
Measures throughput and latency of core operations.
"""

import time
import statistics
import tempfile
import os
import unittest
import pandas as pd

from dataos_system import DataOS
from core.object.model import DataObject, ObjectType, Timestamps


def benchmark(func, iterations=100, warmup=10):
    """Run func multiple times, return median and stats in ms."""
    for _ in range(warmup):
        func()
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        func()
        elapsed = (time.perf_counter() - start) * 1000
        times.append(elapsed)
    return {
        "median_ms": round(statistics.median(times), 3),
        "mean_ms": round(statistics.mean(times), 3),
        "p95_ms": round(sorted(times)[int(len(times) * 0.95)], 3),
        "min_ms": round(min(times), 3),
        "max_ms": round(max(times), 3),
        "iterations": iterations,
    }


class BenchmarkObjectCRUD(unittest.TestCase):
    """Benchmark: Object create, read, list, delete."""

    @classmethod
    def setUpClass(cls):
        cls.dos = DataOS(db_path=":memory:")
        cls.batches = [10, 50, 100]

    def _make_obj(self, i):
        return DataObject(
            type=ObjectType.DATASET.value,
            properties={"name": f"bench_{i}", "rows": i * 10},
            content=[{"col": j} for j in range(10)],
            provenance={"created_by": "benchmark"},
        )

    def test_benchmark_single_save(self):
        obj = self._make_obj(0)
        result = benchmark(lambda: self.dos.storage.save_object(self._make_obj(time.perf_counter_ns())))
        print(f"\n  [Object CRUD] Single save: {result['median_ms']}ms (p95: {result['p95_ms']}ms)")
        self.assertLess(result["median_ms"], 50)

    def test_benchmark_single_get(self):
        obj = self.dos.storage.save_object(self._make_obj(9999))
        result = benchmark(lambda: self.dos.storage.get_object(obj.id))
        print(f"\n  [Object CRUD] Single get: {result['median_ms']}ms (p95: {result['p95_ms']}ms)")
        self.assertLess(result["median_ms"], 10)

    def test_benchmark_batch_save(self):
        for n in self.batches:
            def _batch():
                for i in range(n):
                    self.dos.storage.save_object(self._make_obj(time.perf_counter_ns() + i))
            result = benchmark(_batch, iterations=20, warmup=2)
            per_obj = result["median_ms"] / n
            print(f"\n  [Object CRUD] Batch save {n}: {result['median_ms']}ms total, {per_obj}ms/obj")
            self.assertLess(per_obj, 5)

    def test_benchmark_list_objects(self):
        result = benchmark(lambda: self.dos.storage.list_objects(limit=100))
        print(f"\n  [Object CRUD] List 100: {result['median_ms']}ms (p95: {result['p95_ms']}ms)")
        self.assertLess(result["median_ms"], 20)


class BenchmarkVectorSearch(unittest.TestCase):
    """Benchmark: Vector indexing and similarity search."""

    @classmethod
    def setUpClass(cls):
        cls.dos = DataOS(db_path=":memory:")
        cls.objs = []
        for i in range(50):
            obj = DataObject(
                type=ObjectType.DATASET.value,
                properties={"name": f"dataset_{i}", "description": f"Sales data for region {i % 5}"},
                content=[{"metric": f"val_{j}"} for j in range(5)],
                provenance={"created_by": "benchmark"},
            )
            cls.objs.append(cls.dos.storage.save_object(obj))

    def test_benchmark_single_index(self):
        obj = self._make_index_obj(0)
        result = benchmark(lambda: self.dos.vector_index.index_object(self._make_index_obj(time.perf_counter_ns())))
        print(f"\n  [Vector] Single index: {result['median_ms']}ms (p95: {result['p95_ms']}ms)")
        self.assertLess(result["median_ms"], 100)

    def test_benchmark_batch_index(self):
        def _batch():
            for i in range(10):
                self.dos.vector_index.index_object(self._make_index_obj(time.perf_counter_ns() + i))
        result = benchmark(_batch, iterations=10, warmup=2)
        print(f"\n  [Vector] Batch index 10: {result['median_ms']}ms")
        self.assertLess(result["median_ms"], 500)

    def test_benchmark_search(self):
        for obj in self.objs:
            self.dos.vector_index.index_object(obj)
        result = benchmark(lambda: self.dos.vector_index.search_similar("sales data region", top_k=10))
        print(f"\n  [Vector] Search top-10: {result['median_ms']}ms (p95: {result['p95_ms']}ms)")
        self.assertLess(result["median_ms"], 50)

    def _make_index_obj(self, i):
        return DataObject(
            type=ObjectType.DATASET.value,
            properties={"name": f"idx_{i}"},
            content=[{"col": "data"}],
            provenance={},
        )


class BenchmarkEmbeddings(unittest.TestCase):
    """Benchmark: Embedding generation and similarity."""

    @classmethod
    def setUpClass(cls):
        cls.dos = DataOS(db_path=":memory:")

    def test_benchmark_hash_embed(self):
        result = benchmark(lambda: self.dos.embed("The quick brown fox jumps over the lazy dog"))
        print(f"\n  [Embeddings] Hash embed: {result['median_ms']}ms")
        self.assertLess(result["median_ms"], 5)

    def test_benchmark_hash_similarity(self):
        a = self.dos.embed("machine learning model training")
        b = self.dos.embed("deep learning model training")
        import numpy as np
        sim = float(np.dot(a, b))
        result = benchmark(lambda: float(np.dot(a, b)))
        print(f"\n  [Embeddings] Similarity: {result['median_ms']}ms")
        self.assertLess(result["median_ms"], 1)


class BenchmarkSQL(unittest.TestCase):
    """Benchmark: SQL query execution."""

    @classmethod
    def setUpClass(cls):
        from engines.compute.sql_engine import SQLExecutionEngine
        cls.dos = DataOS(db_path=":memory:")
        cls.sql_engine = SQLExecutionEngine(cls.dos.storage)
        for i in range(5):
            df = pd.DataFrame({
                "id": range(1000),
                "value": [j * (i + 1) for j in range(1000)],
                "category": [f"cat_{j % 10}" for j in range(1000)],
            })
            obj = DataObject(
                type=ObjectType.DATASET.value,
                properties={"filename": f"table_{i}.csv", "table_name": f"table_{i}"},
                content=df.to_dict(orient="records"),
                provenance={},
            )
            cls.dos.storage.save_object(obj)

    def test_benchmark_select_all(self):
        result = benchmark(lambda: self.sql_engine.execute_sql("SELECT * FROM table_0"))
        print(f"\n  [SQL] SELECT * 1000 rows: {result['median_ms']}ms (p95: {result['p95_ms']}ms)")
        self.assertLess(result["median_ms"], 50)

    def test_benchmark_select_agg(self):
        result = benchmark(lambda: self.sql_engine.execute_sql("SELECT category, SUM(value) as total FROM table_0 GROUP BY category"))
        print(f"\n  [SQL] GROUP BY SUM: {result['median_ms']}ms (p95: {result['p95_ms']}ms)")
        self.assertLess(result["median_ms"], 50)

    def test_benchmark_select_where(self):
        result = benchmark(lambda: self.sql_engine.execute_sql("SELECT * FROM table_0 WHERE value > 5000"))
        print(f"\n  [SQL] WHERE filter: {result['median_ms']}ms (p95: {result['p95_ms']}ms)")
        self.assertLess(result["median_ms"], 50)


class BenchmarkPrivacy(unittest.TestCase):
    """Benchmark: Privacy masking and encryption."""

    @classmethod
    def setUpClass(cls):
        cls.dos = DataOS(db_path=":memory:")

    def test_benchmark_mask(self):
        result = benchmark(lambda: self.dos.mask("1234567890"))
        print(f"\n  [Privacy] Mask: {result['median_ms']}ms")
        self.assertLess(result["median_ms"], 1)

    def test_benchmark_batch_mask(self):
        values = [f"user_{i}@example.com" for i in range(100)]
        result = benchmark(lambda: [self.dos.mask(v) for v in values])
        print(f"\n  [Privacy] Batch mask 100: {result['median_ms']}ms")
        self.assertLess(result["median_ms"], 50)


class BenchmarkClassify(unittest.TestCase):
    """Benchmark: Content classification."""

    @classmethod
    def setUpClass(cls):
        cls.dos = DataOS(db_path=":memory:")

    def test_benchmark_classify_code(self):
        code = "def hello():\n    print('world')\nimport os\nx = [1,2,3]"
        result = benchmark(lambda: self.dos.classify(content=code))
        print(f"\n  [Classify] Code content: {result['median_ms']}ms")
        self.assertLess(result["median_ms"], 10)

    def test_benchmark_classify_data(self):
        data = "name,age,salary\nAlice,30,50000\nBob,25,45000"
        result = benchmark(lambda: self.dos.classify(content=data))
        print(f"\n  [Classify] CSV content: {result['median_ms']}ms")
        self.assertLess(result["median_ms"], 10)


class BenchmarkEndToEnd(unittest.TestCase):
    """Benchmark: Full ingest-to-query pipeline."""

    @classmethod
    def setUpClass(cls):
        cls.dos = DataOS(db_path=":memory:")

    def test_benchmark_full_pipeline(self):
        def _pipeline():
            obj = DataObject(
                type=ObjectType.DATASET.value,
                properties={"name": "pipeline_test", "filename": "data.csv"},
                content=[{"x": i, "y": i * 2} for i in range(100)],
                provenance={"created_by": "bench"},
            )
            self.dos.storage.save_object(obj)
            self.dos.vector_index.index_object(obj)
            self.dos.vector_index.search_similar("pipeline test data", top_k=5)

        result = benchmark(_pipeline, iterations=20, warmup=2)
        print(f"\n  [E2E] Ingest+Index+Search: {result['median_ms']}ms")
        self.assertLess(result["median_ms"], 500)


if __name__ == "__main__":
    unittest.main(verbosity=2)
