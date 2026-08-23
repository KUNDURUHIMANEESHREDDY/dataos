"""
Tests for DAG Workflow Engine (Rule #21).
Validates DAG validation, parallel execution, retry, conditions, and state tracking.
"""

import unittest
from runtime.workflows.workflow_engine import (
    WorkflowEngine, WorkflowNode, NodeStatus, WorkflowStatus, DAGValidator
)


class TestDAGValidator(unittest.TestCase):

    def test_valid_dag(self):
        nodes = {
            "a": WorkflowNode("a", "noop"),
            "b": WorkflowNode("b", "noop", depends_on=["a"]),
            "c": WorkflowNode("c", "noop", depends_on=["a", "b"]),
        }
        errors = DAGValidator.validate(nodes)
        self.assertEqual(errors, [])

    def test_missing_dependency(self):
        nodes = {
            "a": WorkflowNode("a", "noop", depends_on=["nonexistent"]),
        }
        errors = DAGValidator.validate(nodes)
        self.assertEqual(len(errors), 1)
        self.assertIn("non-existent", errors[0])

    def test_cycle_detection(self):
        nodes = {
            "a": WorkflowNode("a", "noop", depends_on=["c"]),
            "b": WorkflowNode("b", "noop", depends_on=["a"]),
            "c": WorkflowNode("c", "noop", depends_on=["b"]),
        }
        errors = DAGValidator.validate(nodes)
        self.assertEqual(len(errors), 1)
        self.assertIn("Cycle", errors[0])

    def test_topological_sort(self):
        nodes = {
            "a": WorkflowNode("a", "noop"),
            "b": WorkflowNode("b", "noop", depends_on=["a"]),
            "c": WorkflowNode("c", "noop", depends_on=["a"]),
        }
        order = DAGValidator._topological_sort(nodes)
        self.assertIn("a", order)
        self.assertLess(order.index("a"), order.index("b"))
        self.assertLess(order.index("a"), order.index("c"))

    def test_execution_layers(self):
        nodes = {
            "a": WorkflowNode("a", "noop"),
            "b": WorkflowNode("b", "noop", depends_on=["a"]),
            "c": WorkflowNode("c", "noop", depends_on=["a"]),
            "d": WorkflowNode("d", "noop", depends_on=["b", "c"]),
        }
        layers = DAGValidator.get_execution_layers(nodes)
        self.assertEqual(len(layers), 3)
        self.assertEqual(layers[0], ["a"])
        self.assertEqual(sorted(layers[1]), ["b", "c"])
        self.assertEqual(layers[2], ["d"])


class TestWorkflowEngine(unittest.TestCase):

    def setUp(self):
        self.engine = WorkflowEngine()

    def test_simple_linear_workflow(self):
        workflow = {
            "name": "linear_test",
            "nodes": {
                "step1": {"action_type": "set_variable", "parameters": {"name": "x", "value": 42}},
                "step2": {"action_type": "noop", "parameters": {}, "depends_on": ["step1"]},
            },
        }
        result = self.engine.execute(workflow)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["total_nodes"], 2)
        self.assertEqual(result["completed"], 2)

    def test_parallel_workflow(self):
        workflow = {
            "name": "parallel_test",
            "nodes": {
                "a": {"action_type": "set_variable", "parameters": {"name": "a_val", "value": 1}},
                "b": {"action_type": "set_variable", "parameters": {"name": "b_val", "value": 2}},
                "c": {"action_type": "noop", "parameters": {}, "depends_on": ["a", "b"]},
            },
        }
        result = self.engine.execute(workflow)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["completed"], 3)

    def test_diamond_dag(self):
        workflow = {
            "name": "diamond_test",
            "nodes": {
                "start": {"action_type": "set_variable", "parameters": {"name": "s", "value": 1}},
                "left": {"action_type": "noop", "parameters": {}, "depends_on": ["start"]},
                "right": {"action_type": "noop", "parameters": {}, "depends_on": ["start"]},
                "end": {"action_type": "noop", "parameters": {}, "depends_on": ["left", "right"]},
            },
        }
        result = self.engine.execute(workflow)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["completed"], 4)

    def test_condition_met(self):
        workflow = {
            "name": "cond_test",
            "nodes": {
                "check": {
                    "action_type": "noop",
                    "parameters": {},
                    "condition": {"field": "flag", "operator": "==", "value": True},
                },
            },
        }
        result = self.engine.execute(workflow, context={"flag": True})
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["completed"], 1)

    def test_condition_not_met(self):
        workflow = {
            "name": "cond_skip",
            "nodes": {
                "check": {
                    "action_type": "noop",
                    "parameters": {},
                    "condition": {"field": "flag", "operator": "==", "value": True},
                },
            },
        }
        result = self.engine.execute(workflow, context={"flag": False})
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["completed"], 0)

    def test_retry_on_failure(self):
        call_count = [0]
        def flaky_handler(params, ctx):
            call_count[0] += 1
            if call_count[0] < 3:
                raise RuntimeError("transient error")
            return {"ok": True}
        self.engine.register_handler("flaky", flaky_handler)

        workflow = {
            "name": "retry_test",
            "nodes": {
                "step1": {
                    "action_type": "flaky",
                    "parameters": {},
                    "retry": {"max_attempts": 3, "delay_seconds": 0},
                },
            },
        }
        result = self.engine.execute(workflow)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(call_count[0], 3)

    def test_retry_exhausted(self):
        def always_fail(params, ctx):
            raise RuntimeError("permanent error")
        self.engine.register_handler("fail_always", always_fail)

        workflow = {
            "name": "retry_fail",
            "nodes": {
                "step1": {
                    "action_type": "fail_always",
                    "parameters": {},
                    "retry": {"max_attempts": 2, "delay_seconds": 0},
                },
            },
        }
        result = self.engine.execute(workflow)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failed"], 1)

    def test_dependency_failure_skips_downstream(self):
        def failing(params, ctx):
            raise RuntimeError("boom")
        self.engine.register_handler("fail", failing)

        workflow = {
            "name": "dep_fail",
            "nodes": {
                "step1": {"action_type": "fail", "parameters": {}},
                "step2": {"action_type": "noop", "parameters": {}, "depends_on": ["step1"]},
            },
        }
        result = self.engine.execute(workflow)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["node_results"]["step2"]["status"], "skipped")

    def test_invalid_dag(self):
        workflow = {
            "name": "invalid",
            "nodes": {
                "a": {"action_type": "noop", "depends_on": ["missing"]},
            },
        }
        result = self.engine.execute(workflow)
        self.assertEqual(result["status"], "failed")
        self.assertGreater(len(result["errors"]), 0)

    def test_context_propagation(self):
        workflow = {
            "name": "ctx_test",
            "nodes": {
                "set": {"action_type": "set_variable", "parameters": {"name": "greeting", "value": "hello"}},
                "use": {"action_type": "noop", "parameters": {}, "depends_on": ["set"]},
            },
        }
        result = self.engine.execute(workflow)
        self.assertIn("greeting", result["context"])

    def test_custom_handler(self):
        def custom(params, ctx):
            return {"computed": params.get("a", 0) + params.get("b", 0)}
        self.engine.register_handler("add", custom)

        workflow = {
            "name": "custom_test",
            "nodes": {
                "calc": {"action_type": "add", "parameters": {"a": 3, "b": 4}},
            },
        }
        result = self.engine.execute(workflow)
        self.assertEqual(result["status"], "completed")
        calc_result = result["node_results"]["calc"]
        self.assertEqual(calc_result["computed"], 7)

    def test_execution_history(self):
        workflow = {"name": "h", "nodes": {"a": {"action_type": "noop"}}}
        r1 = self.engine.execute(workflow)
        r2 = self.engine.execute(workflow)
        execs = self.engine.list_executions()
        self.assertEqual(len(execs), 2)
        found = self.engine.get_execution(r1["execution_id"])
        self.assertIsNotNone(found)

    def test_stats(self):
        workflow = {"name": "s", "nodes": {"a": {"action_type": "noop"}}}
        self.engine.execute(workflow)
        stats = self.engine.get_stats()
        self.assertEqual(stats["total_executions"], 1)
        self.assertEqual(stats["by_status"]["completed"], 1)

    def test_node_status_values(self):
        self.assertEqual(NodeStatus.PENDING.value, "pending")
        self.assertEqual(NodeStatus.RUNNING.value, "running")
        self.assertEqual(NodeStatus.COMPLETED.value, "completed")

    def test_workflow_status_values(self):
        self.assertEqual(WorkflowStatus.COMPLETED.value, "completed")
        self.assertEqual(WorkflowStatus.FAILED.value, "failed")
        self.assertEqual(WorkflowStatus.PARTIAL.value, "partial")


class TestWorkflowNode(unittest.TestCase):

    def test_to_dict(self):
        node = WorkflowNode("n1", "sql", parameters={"query": "SELECT 1"}, depends_on=["n0"])
        d = node.to_dict()
        self.assertEqual(d["node_id"], "n1")
        self.assertEqual(d["action_type"], "sql")
        self.assertIn("n0", d["depends_on"])


if __name__ == "__main__":
    unittest.main()
