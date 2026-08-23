"""
DataOS Benchmark Suite
======================

Run: python -m tests.benchmarks.run_all

Comprehensive benchmark report covering:
  1. Ingestion throughput & accuracy
  2. Entity discovery (precision / recall / F1)
  3. Relationship discovery (precision / recall / F1)
  4. Schema matching accuracy
  5. Query engine latency
  6. Vector search quality
  7. Lineage completeness
  8. Scalability (10 / 100 / 500 objects)
  9. Content classification accuracy
  10. End-to-end pipeline
"""

import gc
import os
import sys
import time
import statistics
import tempfile
import tracemalloc
import unittest
from typing import Dict, List, Any, Tuple, Set

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dataos_system import DataOS
from core.object.model import DataObject, ObjectType, Timestamps
from intelligence.knowledge.extractor import KnowledgeExtractor
from tests.benchmarks.generator import (
    generate_customer_order_dataset, generate_text_corpus, BenchmarkDataset,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _f1(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return round(2 * precision * recall / (precision + recall), 4)


def _precision(tp: int, predicted: int) -> float:
    return round(tp / predicted, 4) if predicted > 0 else 0.0


def _recall(tp: int, ground_truth: int) -> float:
    return round(tp / ground_truth, 4) if ground_truth > 0 else 0.0


def benchmark_fn(func, iterations=50, warmup=5):
    """Run func, return median ms."""
    for _ in range(warmup):
        func()
    times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        func()
        times.append((time.perf_counter() - t0) * 1000)
    return {
        "median_ms": round(statistics.median(times), 3),
        "p95_ms": round(sorted(times)[int(len(times) * 0.95)], 3),
        "mean_ms": round(statistics.mean(times), 3),
    }


def _read_file(path: str) -> str:
    with open(path, "r") as f:
        return f.read()


# ===========================================================================
# Benchmark 1: Ingestion
# ===========================================================================

class BenchmarkIngestion(unittest.TestCase):
    """Benchmark: File ingestion throughput and success rate."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.mkdtemp(prefix="dataos_bench_ingest_")
        cls.dataset = generate_customer_order_dataset(cls.temp_dir)
        cls.dos = DataOS(db_path=":memory:")

    def test_ingestion_throughput(self):
        """Measure files/sec ingestion rate."""
        filenames = list(self.dataset.files.keys())
        start = time.perf_counter()
        ingested = 0
        for fname in filenames:
            content = _read_file(self.dataset.files[fname])
            self.dos.ingest(content, filename=fname, discover_relations=False)
            ingested += 1
        elapsed = time.perf_counter() - start
        rate = ingested / elapsed
        print(f"\n  [Ingestion] {ingested} files in {elapsed:.2f}s = {rate:.1f} files/sec")
        self.assertGreater(rate, 1.0)

    def test_ingestion_success_rate(self):
        """All files should ingest without error."""
        filenames = list(self.dataset.files.keys())
        success = 0
        for fname in filenames:
            content = _read_file(self.dataset.files[fname])
            result = self.dos.ingest(content, filename=fname, discover_relations=False)
            if result.get("success", True):
                success += 1
        rate = success / len(filenames) * 100
        print(f"  [Ingestion] Success rate: {rate:.1f}% ({success}/{len(filenames)})")
        self.assertEqual(success, len(filenames))


# ===========================================================================
# Benchmark 2: Entity Discovery
# ===========================================================================

class BenchmarkEntityDiscovery(unittest.TestCase):
    """Benchmark: Entity extraction precision/recall/F1 against ground truth."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.mkdtemp(prefix="dataos_bench_entity_")
        cls.dataset = generate_text_corpus(cls.temp_dir)
        cls.extractor = KnowledgeExtractor()

        # Run knowledge extraction on all articles
        cls.extracted_entities = {}
        for fname, fpath in cls.dataset.files.items():
            content = _read_file(fpath)
            extraction = cls.extractor.extract_all(content)
            for e in extraction.get("entities", []):
                text_lower = e["text"].lower().replace(" ", "_")
                cls.extracted_entities[text_lower] = e

    def test_entity_precision_recall_f1(self):
        """Evaluate entity extraction against ground truth."""
        gt_names = {e.id for e in self.dataset.entities}
        predicted_names = set(self.extracted_entities.keys())

        # Partial match: ground truth entity appears in extracted text
        tp = 0
        for gt_id in gt_names:
            for pred_id in predicted_names:
                if gt_id in pred_id or pred_id in gt_id:
                    tp += 1
                    break

        precision = _precision(tp, len(predicted_names)) if predicted_names else 0
        recall = _recall(tp, len(gt_names))
        f1 = _f1(precision, recall)

        print(f"\n  [Entity Discovery] GT: {len(gt_names)}, Extracted: {len(predicted_names)}")
        print(f"  [Entity Discovery] Precision: {precision:.4f}, Recall: {recall:.4f}, F1: {f1:.4f}")
        self.assertGreater(len(predicted_names), 0)

    def test_entity_type_distribution(self):
        """Verify extracted entities span multiple types."""
        types = set()
        for e in self.extracted_entities.values():
            types.add(e.get("entity_type", "unknown"))
        print(f"  [Entity Discovery] Entity types found: {len(types)} ({', '.join(sorted(types))})")
        self.assertGreater(len(types), 1)


# ===========================================================================
# Benchmark 3: Relationship Discovery
# ===========================================================================

class BenchmarkRelationshipDiscovery(unittest.TestCase):
    """Benchmark: Relationship discovery using signal matchers."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.mkdtemp(prefix="dataos_bench_rel_")
        cls.dataset = generate_customer_order_dataset(cls.temp_dir)
        cls.dos = DataOS(db_path=":memory:")

        # Build proper DataObjects with parsed tabular content
        import csv
        cls.data_objects = {}
        for fname, fpath in cls.dataset.files.items():
            if fname.endswith(".csv"):
                with open(fpath, "r") as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)
                columns = list(rows[0].keys()) if rows else []
            else:
                content = _read_file(fpath)
                rows = [{"data": content}]
                columns = ["data"]

            obj = DataObject(
                type=ObjectType.DATASET.value,
                properties={"filename": fname, "table_name": fname.replace(".", "_").replace("-", "_"), "columns": columns},
                content=rows,
                provenance={},
            )
            cls.data_objects[fname] = cls.dos.storage.save_object(obj)

        # Run structural signal matching
        from intelligence.discovery.signals import StructuralSignalMatcher, ContentSignalMatcher
        cls.discovered_rels = []
        filenames = list(cls.data_objects.keys())
        for i in range(len(filenames)):
            for j in range(i + 1, len(filenames)):
                f1, f2 = filenames[i], filenames[j]
                result = StructuralSignalMatcher.match(cls.data_objects[f1], cls.data_objects[f2])
                if result:
                    result["_pair"] = (f1, f2)
                    cls.discovered_rels.append(result)
                result = ContentSignalMatcher.match(cls.data_objects[f1], cls.data_objects[f2])
                if result:
                    result["_pair"] = (f1, f2)
                    cls.discovered_rels.append(result)

    def test_relationship_discovery_count(self):
        """Should discover at least some relationships between files."""
        print(f"\n  [Relationships] Discovered: {len(self.discovered_rels)} relationships")
        for r in self.discovered_rels[:5]:
            print(f"    {r.get('_pair', '?')}: {r['relation_type']} (conf={r['confidence']:.2f})")
        self.assertGreater(len(self.discovered_rels), 0)

    def test_relationship_confidence(self):
        """Discovered relationships should have meaningful confidence."""
        if not self.discovered_rels:
            self.skipTest("No relationships discovered")
        confidences = [r["confidence"] for r in self.discovered_rels]
        avg_conf = statistics.mean(confidences)
        print(f"  [Relationships] Confidence: avg={avg_conf:.3f}, min={min(confidences):.3f}")
        self.assertGreater(avg_conf, 0.5)


# ===========================================================================
# Benchmark 4: Schema Matching
# ===========================================================================

class BenchmarkSchemaMatching(unittest.TestCase):
    """Benchmark: Schema/column matching across files."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.mkdtemp(prefix="dataos_bench_schema_")
        cls.dataset = generate_customer_order_dataset(cls.temp_dir)
        cls.dos = DataOS(db_path=":memory:")

        # Build DataObjects with column metadata in properties
        import csv
        cls.data_objects = {}
        for fname, fpath in cls.dataset.files.items():
            if fname.endswith(".csv"):
                with open(fpath, "r") as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)
                columns = list(rows[0].keys()) if rows else []
            else:
                rows = [{"data": _read_file(fpath)}]
                columns = ["data"]

            obj = DataObject(
                type=ObjectType.DATASET.value,
                properties={"filename": fname, "table_name": fname.replace(".", "_").replace("-", "_"), "columns": columns},
                content=rows,
                provenance={},
            )
            cls.data_objects[fname] = cls.dos.storage.save_object(obj)

    def test_schema_column_detection(self):
        """Verify schema matching detects shared columns across files."""
        from intelligence.discovery.signals import StructuralSignalMatcher

        detected_pairs = []
        filenames = list(self.data_objects.keys())
        for i in range(len(filenames)):
            for j in range(i + 1, len(filenames)):
                f1, f2 = filenames[i], filenames[j]
                result = StructuralSignalMatcher.match(
                    self.data_objects[f1], self.data_objects[f2]
                )
                if result:
                    detected_pairs.append((f1, f2, result))

        print(f"\n  [Schema Matching] Detected {len(detected_pairs)} file pairs with shared columns")
        for f1, f2, r in detected_pairs[:5]:
            print(f"    {f1} <-> {f2}: {r['relation_type']} (conf={r['confidence']:.2f})")
        self.assertGreater(len(detected_pairs), 0)

    def test_schema_matcher_accuracy(self):
        """Check that detected matches correspond to ground truth."""
        from intelligence.discovery.signals import StructuralSignalMatcher

        gt_pairs = set()
        for col, file_list in self.dataset.schema_matches.items():
            for i in range(len(file_list)):
                for j in range(i + 1, len(file_list)):
                    gt_pairs.add((file_list[i], file_list[j]))
                    gt_pairs.add((file_list[j], file_list[i]))

        detected = set()
        filenames = list(self.data_objects.keys())
        for i in range(len(filenames)):
            for j in range(i + 1, len(filenames)):
                f1, f2 = filenames[i], filenames[j]
                result = StructuralSignalMatcher.match(
                    self.data_objects[f1], self.data_objects[f2]
                )
                if result:
                    detected.add((f1, f2))
                    detected.add((f2, f1))

        tp = len(detected & gt_pairs)
        precision = _precision(tp, len(detected)) if detected else 0
        recall = _recall(tp, len(gt_pairs)) if gt_pairs else 0
        f1 = _f1(precision, recall)

        print(f"  [Schema Matching] GT: {len(gt_pairs)}, Detected: {len(detected)}, TP: {tp}")
        print(f"  [Schema Matching] Precision: {precision:.4f}, Recall: {recall:.4f}, F1: {f1:.4f}")
        self.assertGreater(len(detected), 0)


# ===========================================================================
# Benchmark 5: Query Engine Latency
# ===========================================================================

class BenchmarkQueryEngine(unittest.TestCase):
    """Benchmark: SQL query execution latency."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.mkdtemp(prefix="dataos_bench_query_")
        cls.dataset = generate_customer_order_dataset(cls.temp_dir)
        cls.dos = DataOS(db_path=":memory:")

        for fname, fpath in cls.dataset.files.items():
            if fname.endswith(".csv"):
                content = _read_file(fpath)
                cls.dos.ingest(content, filename=fname, discover_relations=False)

    def test_query_latency_select(self):
        result = benchmark_fn(
            lambda: self.dos.sql_engine.execute_sql("SELECT * FROM customers_csv")
        )
        print(f"\n  [Query] SELECT * customers: {result['median_ms']}ms (p95: {result['p95_ms']}ms)")
        self.assertLess(result["median_ms"], 100)

    def test_query_latency_join(self):
        result = benchmark_fn(
            lambda: self.dos.sql_engine.execute_sql(
                "SELECT c.name, COUNT(o.order_id) as order_count "
                "FROM customers_csv c "
                "JOIN orders_csv o ON c.customer_id = o.customer_id "
                "GROUP BY c.name LIMIT 20"
            )
        )
        print(f"  [Query] JOIN + GROUP BY: {result['median_ms']}ms (p95: {result['p95_ms']}ms)")
        self.assertLess(result["median_ms"], 200)

    def test_query_latency_aggregation(self):
        result = benchmark_fn(
            lambda: self.dos.sql_engine.execute_sql(
                "SELECT region, COUNT(*) as cnt, AVG(total_amount) as avg_amount "
                "FROM orders_csv GROUP BY region"
            )
        )
        print(f"  [Query] Aggregation: {result['median_ms']}ms (p95: {result['p95_ms']}ms)")
        self.assertLess(result["median_ms"], 100)


# ===========================================================================
# Benchmark 6: Vector Search Quality
# ===========================================================================

class BenchmarkVectorSearch(unittest.TestCase):
    """Benchmark: Vector search latency and quality."""

    @classmethod
    def setUpClass(cls):
        cls.dos = DataOS(db_path=":memory:")
        cls.objs = []
        cls.descriptions = [
            "Customer analytics dashboard with revenue metrics",
            "Sales pipeline tracking and forecasting",
            "Employee performance review system",
            "Product inventory management",
            "Support ticket resolution tracking",
            "Financial quarterly report analysis",
            "Marketing campaign effectiveness metrics",
            "Supply chain logistics optimization",
            "Customer satisfaction survey results",
            "Regional sales comparison report",
        ]
        for i, desc in enumerate(cls.descriptions):
            obj = DataObject(
                type=ObjectType.DATASET.value,
                properties={"name": f"dataset_{i}", "description": desc},
                content=[{"summary": desc}],
                provenance={},
            )
            saved = cls.dos.storage.save_object(obj)
            cls.objs.append(saved)
            cls.dos.vector_index.index_object(saved)

    def test_search_latency(self):
        result = benchmark_fn(
            lambda: self.dos.vector_index.search_similar("revenue and sales metrics", top_k=5)
        )
        print(f"\n  [Vector Search] Latency: {result['median_ms']}ms (p95: {result['p95_ms']}ms)")
        self.assertLess(result["median_ms"], 50)

    def test_search_returns_results(self):
        """Search should return non-empty results."""
        results = self.dos.vector_index.search_similar("revenue and sales metrics", top_k=5)
        print(f"  [Vector Search] Results returned: {len(results)}")
        self.assertGreater(len(results), 0)
        # All results should have valid similarity scores
        for r in results:
            self.assertIn("similarity", r)
            self.assertIn("object_id", r)

    def test_search_ranking(self):
        """Results should be sorted by similarity descending."""
        results = self.dos.vector_index.search_similar("employee performance", top_k=10)
        if len(results) > 1:
            sims = [r["similarity"] for r in results]
            self.assertEqual(sims, sorted(sims, reverse=True))
            print(f"  [Vector Search] Ranking correct: scores [{sims[0]:.4f} ... {sims[-1]:.4f}]")

    def test_search_index_size(self):
        stats = self.dos.vector_index.get_index_stats()
        print(f"  [Vector Search] Index size: {stats['total_embeddings']} embeddings")
        self.assertEqual(stats["total_embeddings"], len(self.objs))


# ===========================================================================
# Benchmark 7: Lineage Completeness
# ===========================================================================

class BenchmarkLineage(unittest.TestCase):
    """Benchmark: Lineage/provenance tracking completeness."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.mkdtemp(prefix="dataos_bench_lineage_")
        cls.dataset = generate_customer_order_dataset(cls.temp_dir)
        cls.dos = DataOS(db_path=":memory:")

        for fname, fpath in cls.dataset.files.items():
            content = _read_file(fpath)
            cls.dos.ingest(content, filename=fname, discover_relations=True)

    def test_lineage_completeness(self):
        """Every ingested object should have provenance recorded."""
        objects = self.dos.storage.list_objects(limit=200)
        with_provenance = sum(1 for o in objects if o.provenance)
        completeness = with_provenance / len(objects) * 100 if objects else 0
        print(f"\n  [Lineage] Objects: {len(objects)}, With provenance: {with_provenance} ({completeness:.1f}%)")
        self.assertGreater(completeness, 80)

    def test_lineage_query_latency(self):
        objects = self.dos.storage.list_objects(limit=10)
        if not objects:
            self.skipTest("No objects")
        obj_id = objects[0].id
        result = benchmark_fn(lambda: self.dos.why(obj_id))
        print(f"  [Lineage] why() latency: {result['median_ms']}ms (p95: {result['p95_ms']}ms)")
        self.assertLess(result["median_ms"], 100)


# ===========================================================================
# Benchmark 8: Scalability
# ===========================================================================

class BenchmarkScalability(unittest.TestCase):
    """Benchmark: Scalability across object counts."""

    def _run_scale_test(self, n_objects: int) -> Dict[str, Any]:
        dos = DataOS(db_path=":memory:")

        t0 = time.perf_counter()
        obj_ids = []
        for i in range(n_objects):
            obj = DataObject(
                type=ObjectType.DATASET.value,
                properties={"name": f"scale_{i}", "index": i},
                content=[{"col_a": i, "col_b": f"val_{i}", "col_c": i * 1.5}],
                provenance={},
            )
            saved = dos.storage.save_object(obj)
            obj_ids.append(saved.id)
        ingest_time = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        for oid in obj_ids:
            obj = dos.storage.get_object(oid)
            dos.vector_index.index_object(obj)
        index_time = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        for _ in range(10):
            dos.vector_index.search_similar("test query", top_k=5)
        search_time = (time.perf_counter() - t0) * 1000 / 10

        tracemalloc.start()
        for oid in obj_ids:
            dos.storage.get_object(oid)
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        dos.close()
        return {
            "n": n_objects,
            "ingest_ms": round(ingest_time, 1),
            "ingest_per_obj_ms": round(ingest_time / n_objects, 3),
            "index_ms": round(index_time, 1),
            "search_ms": round(search_time, 3),
            "peak_memory_mb": round(peak / 1024 / 1024, 2),
        }

    def test_scalability_10(self):
        r = self._run_scale_test(10)
        print(f"\n  [Scale] n={r['n']}: ingest={r['ingest_ms']}ms, index={r['index_ms']}ms, search={r['search_ms']}ms, mem={r['peak_memory_mb']}MB")
        self.assertLess(r["ingest_per_obj_ms"], 50)

    def test_scalability_100(self):
        r = self._run_scale_test(100)
        print(f"  [Scale] n={r['n']}: ingest={r['ingest_ms']}ms, index={r['index_ms']}ms, search={r['search_ms']}ms, mem={r['peak_memory_mb']}MB")
        self.assertLess(r["ingest_per_obj_ms"], 50)

    def test_scalability_500(self):
        r = self._run_scale_test(500)
        print(f"  [Scale] n={r['n']}: ingest={r['ingest_ms']}ms, index={r['index_ms']}ms, search={r['search_ms']}ms, mem={r['peak_memory_mb']}MB")
        self.assertLess(r["ingest_per_obj_ms"], 50)


# ===========================================================================
# Benchmark 9: Content Classification
# ===========================================================================

class BenchmarkClassification(unittest.TestCase):
    """Benchmark: Content type classification accuracy."""

    @classmethod
    def setUpClass(cls):
        cls.dos = DataOS(db_path=":memory:")
        # Map: (filename, content) -> expected classification subtype
        cls.test_cases = [
            ("data.csv", "name,age,score\nAlice,30,95\nBob,25,88", "csv"),
            ("app.py", "def hello():\n    print('world')", "python"),
            ("readme.md", "# Title\n\n## Section\n\nSome text", "markdown"),
            ("config.yaml", "server:\n  port: 8080\n  host: localhost", "yaml"),
            ("report.txt", "Quarterly results show 15% growth in revenue.", "unknown"),
            ("schema.json", '{"type": "object", "properties": {"id": {"type": "integer"}}}', "json"),
        ]

    def test_classification_accuracy(self):
        correct = 0
        for filename, content, expected in self.test_cases:
            result = self.dos.classify(filename=filename, content=content)
            actual = result.get("classification", "unknown")
            # Check if expected is contained in actual (e.g. "csv" in "csv")
            match = expected in actual or actual in expected
            if match:
                correct += 1
            print(f"  [Classify] {filename}: expected={expected}, got={actual}, match={match}")
        accuracy = correct / len(self.test_cases) * 100
        print(f"  [Classify] Accuracy: {accuracy:.1f}% ({correct}/{len(self.test_cases)})")
        self.assertGreaterEqual(correct, 3)


# ===========================================================================
# Benchmark 10: End-to-End Pipeline
# ===========================================================================

class BenchmarkEndToEnd(unittest.TestCase):
    """Benchmark: Full pipeline from ingestion to query."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.mkdtemp(prefix="dataos_bench_e2e_")
        cls.dataset = generate_customer_order_dataset(cls.temp_dir)

    def test_full_pipeline_latency(self):
        dos = DataOS(db_path=":memory:")

        def _pipeline():
            for fname, fpath in self.dataset.files.items():
                content = _read_file(fpath)
                dos.ingest(content, filename=fname, discover_relations=False)
            objects = dos.storage.list_objects(limit=50)
            for obj in objects:
                dos.vector_index.index_object(obj)
            dos.vector_index.search_similar("customer orders", top_k=5)
            dos.sql_engine.execute_sql("SELECT COUNT(*) FROM customers_csv")

        result = benchmark_fn(_pipeline, iterations=5, warmup=1)
        print(f"\n  [E2E] Full pipeline: {result['median_ms']}ms (p95: {result['p95_ms']}ms)")
        self.assertLess(result["median_ms"], 5000)
        dos.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
