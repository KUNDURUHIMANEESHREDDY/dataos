"""API-boundary tests for bounded, built-in workflow execution."""
import unittest

from backend.workflow_api import WorkflowRequestError, execute_safe_workflow
from runtime.workflows.workflow_engine import WorkflowEngine


class TestSafeWorkflowAPI(unittest.TestCase):
    def setUp(self):
        self.engine = WorkflowEngine()

    def test_executes_a_bounded_manual_workflow(self):
        result = execute_safe_workflow(
            self.engine,
            {
                "name": "safe-example",
                "trigger": {"type": "manual"},
                "nodes": {
                    "set-value": {
                        "action_type": "set_variable",
                        "parameters": {"name": "answer", "value": 42},
                    },
                    "finish": {
                        "action_type": "noop",
                        "depends_on": ["set-value"],
                    },
                },
            },
            {"requester": "test"},
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["completed"], 2)
        self.assertEqual(result["context"]["answer"], 42)
        self.assertEqual(result["context"]["requester"], "test")

    def test_rejects_unknown_or_code_execution_actions(self):
        with self.assertRaisesRegex(WorkflowRequestError, "action_type"):
            execute_safe_workflow(
                self.engine,
                {"nodes": {"run": {"action_type": "python", "parameters": {"code": "print(1)"}}}},
                {},
            )

    def test_rejects_non_string_action_and_condition_operators(self):
        with self.assertRaisesRegex(WorkflowRequestError, "action_type"):
            execute_safe_workflow(
                self.engine,
                {"nodes": {"n": {"action_type": ["noop"]}}},
                {},
            )
        with self.assertRaisesRegex(WorkflowRequestError, "condition operator"):
            execute_safe_workflow(
                self.engine,
                {"nodes": {"n": {
                    "action_type": "noop",
                    "condition": {"field": "flag", "operator": [], "value": True},
                }}},
                {},
            )

    def test_rejects_dags_over_node_budget(self):
        nodes = {f"n{i}": {"action_type": "noop"} for i in range(26)}
        with self.assertRaisesRegex(WorkflowRequestError, "1 to 25 nodes"):
            execute_safe_workflow(self.engine, {"nodes": nodes}, {})

    def test_rejects_unbounded_retries_and_unenforced_timeouts(self):
        with self.assertRaisesRegex(WorkflowRequestError, "max_attempts"):
            execute_safe_workflow(
                self.engine,
                {"nodes": {"n": {"action_type": "noop", "retry": {"max_attempts": 1000000}}}},
                {},
            )
        with self.assertRaisesRegex(WorkflowRequestError, "timeouts are not supported"):
            execute_safe_workflow(
                self.engine,
                {"nodes": {"n": {"action_type": "noop", "timeout_seconds": 1}}},
                {},
            )

    def test_rejects_invalid_graph_before_execution(self):
        with self.assertRaisesRegex(WorkflowRequestError, "non-existent node"):
            execute_safe_workflow(
                self.engine,
                {"nodes": {"n": {"action_type": "noop", "depends_on": ["missing"]}}},
                {},
            )

    def test_rejects_oversized_context(self):
        with self.assertRaisesRegex(WorkflowRequestError, "128-byte limit"):
            execute_safe_workflow(
                self.engine,
                {"nodes": {"n": {"action_type": "noop"}}},
                {"payload": "x" * (128 * 1024)},
            )

