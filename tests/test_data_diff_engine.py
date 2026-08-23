"""
Tests for Data Diff Engine (Rule #24).
Validates schema, row, summary, column, and full diffs.
"""

import unittest
from engines.diff.data_diff_engine import (
    DataDiffEngine, DiffEngineManager, DiffResult, DiffReport,
    DiffType, DiffSeverity,
)


class TestDataDiffEngine(unittest.TestCase):

    def setUp(self):
        self.engine = DataDiffEngine(key_column="id")

    def test_diff_schemas_identical(self):
        source = [{"id": 1, "name": "Alice"}]
        target = [{"id": 1, "name": "Alice"}]
        report = self.engine.diff_schemas(source, target)
        self.assertEqual(report.summary()["total_diffs"], 0)

    def test_diff_schemas_added_column(self):
        source = [{"id": 1}]
        target = [{"id": 1, "email": "a@b.com"}]
        report = self.engine.diff_schemas(source, target)
        self.assertEqual(report.summary()["by_type"]["column_added"], 1)

    def test_diff_schemas_removed_column(self):
        source = [{"id": 1, "name": "Alice"}]
        target = [{"id": 1}]
        report = self.engine.diff_schemas(source, target)
        self.assertEqual(report.summary()["by_type"]["column_removed"], 1)

    def test_diff_rows_identical(self):
        data = [{"id": 1, "val": "a"}, {"id": 2, "val": "b"}]
        report = self.engine.diff_rows(data, data)
        self.assertEqual(report.summary()["total_diffs"], 0)

    def test_diff_rows_added(self):
        source = [{"id": 1}]
        target = [{"id": 1}, {"id": 2}]
        report = self.engine.diff_rows(source, target)
        self.assertEqual(report.summary()["by_type"]["row_added"], 1)

    def test_diff_rows_removed(self):
        source = [{"id": 1}, {"id": 2}]
        target = [{"id": 1}]
        report = self.engine.diff_rows(source, target)
        self.assertEqual(report.summary()["by_type"]["row_removed"], 1)

    def test_diff_rows_modified(self):
        source = [{"id": 1, "val": "old"}]
        target = [{"id": 1, "val": "new"}]
        report = self.engine.diff_rows(source, target)
        self.assertEqual(report.summary()["by_type"]["value_changed"], 1)

    def test_diff_rows_custom_key(self):
        engine = DataDiffEngine(key_column="pk")
        source = [{"pk": 1, "v": 10}]
        target = [{"pk": 1, "v": 20}]
        report = engine.diff_rows(source, target)
        self.assertEqual(report.summary()["by_type"]["value_changed"], 1)

    def test_diff_summaries(self):
        source = [{"id": 1}, {"id": 2}]
        target = [{"id": 1}, {"id": 2}, {"id": 3}]
        report = self.engine.diff_summaries(source, target)
        row_result = [r for r in report.results if r.target == "row_count"][0]
        self.assertEqual(row_result.old_value, 2)
        self.assertEqual(row_result.new_value, 3)

    def test_full_diff(self):
        source = [{"id": 1, "v": 10}, {"id": 2, "v": 20}]
        target = [{"id": 1, "v": 10}, {"id": 3, "v": 30}]
        result = self.engine.full_diff(source, target)
        self.assertIn("results", result)
        self.assertIn("by_type", result)

    def test_diff_columns(self):
        source = [{"id": 1, "tag": "a"}, {"id": 2, "tag": "b"}]
        target = [{"id": 1, "tag": "a"}, {"id": 3, "tag": "c"}]
        result = self.engine.diff_columns(source, target, "tag")
        self.assertIn("b", result["values_removed"])
        self.assertIn("c", result["values_added"])

    def test_diff_columns_empty(self):
        result = self.engine.diff_columns([], [], "x")
        self.assertEqual(result["source_count"], 0)
        self.assertEqual(result["target_count"], 0)


class TestDiffResult(unittest.TestCase):

    def test_to_dict(self):
        r = DiffResult(DiffType.VALUE_CHANGED, "col", old_value=1, new_value=2, row_id="r1")
        d = r.to_dict()
        self.assertEqual(d["diff_type"], "value_changed")
        self.assertEqual(d["old_value"], 1)


class TestDiffReport(unittest.TestCase):

    def test_summary(self):
        report = DiffReport("s1", "t1")
        report.add(DiffResult(DiffType.ROW_ADDED, "id"))
        report.add(DiffResult(DiffType.ROW_REMOVED, "id", severity=DiffSeverity.WARNING))
        s = report.summary()
        self.assertEqual(s["total_diffs"], 2)
        self.assertEqual(s["by_severity"]["warning"], 1)

    def test_to_dict(self):
        report = DiffReport("s1", "t1")
        report.add(DiffResult(DiffType.COLUMN_ADDED, "email"))
        d = report.to_dict()
        self.assertEqual(len(d["results"]), 1)


class TestDiffEngineManager(unittest.TestCase):

    def setUp(self):
        self.manager = DiffEngineManager()

    def test_register_dataset(self):
        engine = self.manager.register_dataset("ds1")
        self.assertIsNotNone(engine)

    def test_diff(self):
        self.manager.register_dataset("ds1")
        source = [{"id": 1}]
        target = [{"id": 1}, {"id": 2}]
        result = self.manager.diff("ds1", "ds2", source, target)
        self.assertIn("source_id", result)
        self.assertIn("results", result)

    def test_history(self):
        self.manager.diff("ds1", "ds2", [{"id": 1}], [{"id": 1}])
        self.assertEqual(len(self.manager.get_history()), 1)

    def test_stats(self):
        self.manager.register_dataset("ds1")
        self.manager.diff("ds1", "ds2", [{"id": 1}], [{"id": 1}])
        stats = self.manager.get_stats()
        self.assertEqual(stats["registered_engines"], 1)
        self.assertEqual(stats["total_diffs"], 1)


class TestDiffType(unittest.TestCase):

    def test_all_types(self):
        self.assertEqual(len(DiffType), 7)


if __name__ == "__main__":
    unittest.main()
