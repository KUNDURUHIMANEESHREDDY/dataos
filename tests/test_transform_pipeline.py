"""
Tests for Transformation Pipeline Engine (Rule #22).
Validates chaining, built-in transforms, error handling, and pipeline management.
"""

import unittest
from engines.compute.transform_pipeline import (
    TransformationEngine, TransformationPipeline, TransformStep,
    StepStatus, PipelineStatus,
)


class TestTransformStep(unittest.TestCase):

    def test_to_dict(self):
        step = TransformStep("s1", "filter", {"column": "age", "operator": "gt", "value": 18}, name="age_filter")
        d = step.to_dict()
        self.assertEqual(d["step_id"], "s1")
        self.assertEqual(d["transform_type"], "filter")
        self.assertEqual(d["status"], "pending")


class TestTransformationPipeline(unittest.TestCase):

    def test_to_dict(self):
        p = TransformationPipeline("p1", "test_pipeline", description="A test")
        p.add_step(TransformStep("s1", "filter"))
        d = p.to_dict()
        self.assertEqual(d["pipeline_id"], "p1")
        self.assertEqual(len(d["steps"]), 1)


class TestTransformationEngine(unittest.TestCase):

    def setUp(self):
        self.engine = TransformationEngine()
        self.data = [
            {"id": 1, "name": "Alice", "age": 30, "score": 85},
            {"id": 2, "name": "Bob", "age": 25, "score": 92},
            {"id": 3, "name": "Charlie", "age": 35, "score": 78},
        ]

    def test_create_pipeline(self):
        p = self.engine.create_pipeline("test", "desc")
        self.assertIsNotNone(p.pipeline_id)

    def test_add_step(self):
        p = self.engine.create_pipeline("test")
        step = self.engine.add_step(p.pipeline_id, "filter", {"column": "age", "operator": "gt", "value": 18})
        self.assertIsNotNone(step)
        self.assertEqual(len(p.steps), 1)

    def test_add_step_nonexistent(self):
        step = self.engine.add_step("no_such", "filter")
        self.assertIsNone(step)

    def test_execute_linear_pipeline(self):
        p = self.engine.create_pipeline("test")
        self.engine.add_step(p.pipeline_id, "filter", {"column": "age", "operator": "gt", "value": 26})
        self.engine.add_step(p.pipeline_id, "sort", {"column": "name", "descending": False})
        result = self.engine.execute(p.pipeline_id, self.data)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["completed"], 2)
        self.assertEqual(len(result["result"]), 2)

    def test_execute_filter_eq(self):
        p = self.engine.create_pipeline("test")
        self.engine.add_step(p.pipeline_id, "filter", {"column": "name", "operator": "eq", "value": "Bob"})
        result = self.engine.execute(p.pipeline_id, self.data)
        self.assertEqual(len(result["result"]), 1)
        self.assertEqual(result["result"][0]["name"], "Bob")

    def test_execute_filter_contains(self):
        p = self.engine.create_pipeline("test")
        self.engine.add_step(p.pipeline_id, "filter", {"column": "name", "operator": "contains", "value": "li"})
        result = self.engine.execute(p.pipeline_id, self.data)
        self.assertEqual(len(result["result"]), 2)

    def test_execute_filter_in(self):
        p = self.engine.create_pipeline("test")
        self.engine.add_step(p.pipeline_id, "filter", {"column": "name", "operator": "in", "value": ["Alice", "Charlie"]})
        result = self.engine.execute(p.pipeline_id, self.data)
        self.assertEqual(len(result["result"]), 2)

    def test_execute_sort(self):
        p = self.engine.create_pipeline("test")
        self.engine.add_step(p.pipeline_id, "sort", {"column": "score", "descending": True})
        result = self.engine.execute(p.pipeline_id, self.data)
        self.assertEqual(result["result"][0]["score"], 92)

    def test_execute_deduplicate(self):
        data = [{"id": 1, "name": "Alice"}, {"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
        p = self.engine.create_pipeline("test")
        self.engine.add_step(p.pipeline_id, "deduplicate", {"columns": ["id"]})
        result = self.engine.execute(p.pipeline_id, data)
        self.assertEqual(len(result["result"]), 2)

    def test_execute_aggregate_count(self):
        p = self.engine.create_pipeline("test")
        self.engine.add_step(p.pipeline_id, "aggregate", {"function": "count"})
        result = self.engine.execute(p.pipeline_id, self.data)
        self.assertEqual(result["result"]["count"], 3)

    def test_execute_aggregate_sum(self):
        p = self.engine.create_pipeline("test")
        self.engine.add_step(p.pipeline_id, "aggregate", {"function": "sum", "column": "score"})
        result = self.engine.execute(p.pipeline_id, self.data)
        self.assertEqual(result["result"]["sum"], 255)

    def test_execute_aggregate_groupby(self):
        data = [
            {"dept": "eng", "salary": 100}, {"dept": "eng", "salary": 120},
            {"dept": "sales", "salary": 90},
        ]
        p = self.engine.create_pipeline("test")
        self.engine.add_step(p.pipeline_id, "aggregate", {"group_by": ["dept"], "function": "sum", "column": "salary"})
        result = self.engine.execute(p.pipeline_id, data)
        self.assertEqual(len(result["result"]), 2)

    def test_execute_rename_column(self):
        p = self.engine.create_pipeline("test")
        self.engine.add_step(p.pipeline_id, "rename_column", {"old_name": "name", "new_name": "full_name"})
        result = self.engine.execute(p.pipeline_id, self.data)
        self.assertIn("full_name", result["result"][0])

    def test_execute_add_column(self):
        p = self.engine.create_pipeline("test")
        self.engine.add_step(p.pipeline_id, "add_column", {"name": "status", "default": "active"})
        result = self.engine.execute(p.pipeline_id, self.data)
        self.assertEqual(result["result"][0]["status"], "active")

    def test_execute_drop_column(self):
        p = self.engine.create_pipeline("test")
        self.engine.add_step(p.pipeline_id, "drop_column", {"columns": ["score"]})
        result = self.engine.execute(p.pipeline_id, self.data)
        self.assertNotIn("score", result["result"][0])

    def test_execute_cast(self):
        data = [{"val": "42"}, {"val": "37"}]
        p = self.engine.create_pipeline("test")
        self.engine.add_step(p.pipeline_id, "cast", {"column": "val", "type": "int"})
        result = self.engine.execute(p.pipeline_id, data)
        self.assertEqual(result["result"][0]["val"], 42)

    def test_execute_limit(self):
        p = self.engine.create_pipeline("test")
        self.engine.add_step(p.pipeline_id, "limit", {"n": 2})
        result = self.engine.execute(p.pipeline_id, self.data)
        self.assertEqual(len(result["result"]), 2)

    def test_execute_flatten(self):
        data = [{"id": 1, "tags": ["a", "b"]}, {"id": 2, "tags": ["c"]}]
        p = self.engine.create_pipeline("test")
        self.engine.add_step(p.pipeline_id, "flatten", {"column": "tags"})
        result = self.engine.execute(p.pipeline_id, data)
        self.assertEqual(len(result["result"]), 3)

    def test_execute_merge(self):
        p = self.engine.create_pipeline("test")
        self.engine.add_step(p.pipeline_id, "merge", {"columns": ["name", "age"], "separator": "-", "new_name": "info"})
        result = self.engine.execute(p.pipeline_id, self.data)
        self.assertIn("-", result["result"][0]["info"])

    def test_execute_split(self):
        data = [{"full": "Alice Smith"}]
        p = self.engine.create_pipeline("test")
        self.engine.add_step(p.pipeline_id, "split", {"column": "full", "separator": " ", "new_names": ["first", "last"]})
        result = self.engine.execute(p.pipeline_id, data)
        self.assertEqual(result["result"][0]["first"], "Alice")
        self.assertEqual(result["result"][0]["last"], "Smith")

    def test_execute_pivot(self):
        data = [
            {"region": "US", "year": 2020, "revenue": 100},
            {"region": "EU", "year": 2020, "revenue": 80},
        ]
        p = self.engine.create_pipeline("test")
        self.engine.add_step(p.pipeline_id, "pivot", {"index": "region", "pivot_column": "year", "value_column": "revenue"})
        result = self.engine.execute(p.pipeline_id, data)
        self.assertEqual(result["result"][0]["2020"], 100)

    def test_execute_unpivot(self):
        data = [{"id": 1, "x": 10, "y": 20}]
        p = self.engine.create_pipeline("test")
        self.engine.add_step(p.pipeline_id, "unpivot", {"id_columns": ["id"], "var_name": "axis", "value_name": "val"})
        result = self.engine.execute(p.pipeline_id, data)
        self.assertEqual(len(result["result"]), 2)

    def test_custom_transform(self):
        def double_score(data, params):
            return [{"id": r["id"], "score": r["score"] * 2} for r in data]
        self.engine.register_handler("double_score", double_score)
        p = self.engine.create_pipeline("test")
        self.engine.add_step(p.pipeline_id, "double_score")
        result = self.engine.execute(p.pipeline_id, self.data)
        self.assertEqual(result["result"][0]["score"], 170)

    def test_error_handler(self):
        def boom(data, params):
            raise ValueError("oops")
        self.engine.register_handler("boom", boom)
        p = self.engine.create_pipeline("test")
        self.engine.add_step(p.pipeline_id, "boom")
        result = self.engine.execute(p.pipeline_id, self.data)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failed"], 1)

    def test_unknown_transform(self):
        p = self.engine.create_pipeline("test")
        self.engine.add_step(p.pipeline_id, "nonexistent")
        result = self.engine.execute(p.pipeline_id, self.data)
        self.assertEqual(result["status"], "failed")

    def test_execute_nonexistent_pipeline(self):
        result = self.engine.execute("no_such", [])
        self.assertIn("error", result)

    def test_pipeline_history(self):
        p = self.engine.create_pipeline("test")
        self.engine.add_step(p.pipeline_id, "limit", {"n": 1})
        self.engine.execute(p.pipeline_id, self.data)
        self.engine.execute(p.pipeline_id, self.data)
        history = self.engine.get_history()
        self.assertEqual(len(history), 2)

    def test_stats(self):
        p = self.engine.create_pipeline("test")
        self.engine.add_step(p.pipeline_id, "limit", {"n": 1})
        self.engine.execute(p.pipeline_id, self.data)
        stats = self.engine.get_stats()
        self.assertEqual(stats["total_pipelines"], 1)
        self.assertEqual(stats["total_executions"], 1)

    def test_map_transform(self):
        p = self.engine.create_pipeline("test")
        self.engine.add_step(p.pipeline_id, "map", {"mapping": {"name": "full_name"}})
        result = self.engine.execute(p.pipeline_id, self.data)
        self.assertIn("full_name", result["result"][0])


class TestStepStatus(unittest.TestCase):

    def test_values(self):
        self.assertEqual(StepStatus.PENDING.value, "pending")
        self.assertEqual(StepStatus.RUNNING.value, "running")
        self.assertEqual(StepStatus.COMPLETED.value, "completed")
        self.assertEqual(StepStatus.FAILED.value, "failed")


class TestPipelineStatus(unittest.TestCase):

    def test_values(self):
        self.assertEqual(PipelineStatus.COMPLETED.value, "completed")
        self.assertEqual(PipelineStatus.FAILED.value, "failed")
        self.assertEqual(PipelineStatus.PARTIAL.value, "partial")


if __name__ == "__main__":
    unittest.main()
