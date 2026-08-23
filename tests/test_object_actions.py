"""
Tests for Universal Object Actions (Rule #55).
Validates action registration, execution, permissions, history, and built-in actions.
"""

import unittest
from engines.actions.registry import (
    ActionsRegistry, ObjectAction, ActionCategory, ActionResult, register_builtin_actions
)


class TestActionsRegistry(unittest.TestCase):

    def setUp(self):
        self.registry = ActionsRegistry()

    def test_register_action(self):
        action = self.registry.register(
            action_id="test_action",
            name="Test Action",
            category=ActionCategory.ANALYZE,
            handler=lambda obj=None, **kw: {"result": "ok"},
            description="A test action",
        )
        self.assertEqual(action.action_id, "test_action")
        self.assertEqual(action.category, ActionCategory.ANALYZE)

    def test_duplicate_registration_raises(self):
        self.registry.register(
            action_id="dup",
            name="Dup",
            category=ActionCategory.READ,
            handler=lambda **kw: None,
        )
        with self.assertRaises(ValueError):
            self.registry.register(
                action_id="dup",
                name="Dup2",
                category=ActionCategory.READ,
                handler=lambda **kw: None,
            )

    def test_unregister(self):
        self.registry.register(
            action_id="to_remove",
            name="Remove",
            category=ActionCategory.READ,
            handler=lambda **kw: None,
        )
        self.assertTrue(self.registry.unregister("to_remove"))
        self.assertIsNone(self.registry.get("to_remove"))

    def test_unregister_nonexistent(self):
        self.assertFalse(self.registry.unregister("no_such"))

    def test_get_action(self):
        self.registry.register(
            action_id="find_me",
            name="Find",
            category=ActionCategory.QUERY,
            handler=lambda **kw: "found",
        )
        action = self.registry.get("find_me")
        self.assertIsNotNone(action)
        self.assertEqual(action.name, "Find")

    def test_list_all(self):
        self.registry.register("a1", "A1", ActionCategory.READ, lambda **kw: None)
        self.registry.register("a2", "A2", ActionCategory.ANALYZE, lambda **kw: None)
        all_actions = self.registry.list_all()
        self.assertEqual(len(all_actions), 2)

    def test_list_by_category(self):
        self.registry.register("r1", "R1", ActionCategory.READ, lambda **kw: None)
        self.registry.register("r2", "R2", ActionCategory.READ, lambda **kw: None)
        self.registry.register("a1", "A1", ActionCategory.ANALYZE, lambda **kw: None)
        read_actions = self.registry.list_by_category(ActionCategory.READ)
        self.assertEqual(len(read_actions), 2)

    def test_list_for_object_type(self):
        self.registry.register(
            "csv_action", "CSV Action", ActionCategory.ANALYZE,
            lambda **kw: None, applicable_types=["dataset"],
        )
        self.registry.register(
            "all_action", "All Action", ActionCategory.READ,
            lambda **kw: None, applicable_types=[],
        )
        dataset_actions = self.registry.list_for_object_type("dataset")
        self.assertEqual(len(dataset_actions), 2)
        doc_actions = self.registry.list_for_object_type("document")
        self.assertEqual(len(doc_actions), 1)

    def test_get_capabilities(self):
        self.registry.register(
            "cap1", "Cap1", ActionCategory.READ,
            lambda **kw: None, applicable_types=["dataset", "document"],
        )
        caps = self.registry.get_capabilities_for_object("dataset")
        self.assertIn("cap1", caps)

    def test_execute_action(self):
        def my_handler(object_id, obj=None, **kw):
            return {"id": object_id, "data": "processed"}
        self.registry.register("process", "Process", ActionCategory.TRANSFORM, my_handler)
        result = self.registry.execute("process", "obj_1")
        self.assertTrue(result.success)
        self.assertEqual(result.output["id"], "obj_1")
        self.assertGreater(result.execution_time_ms, 0)

    def test_execute_nonexistent_action(self):
        result = self.registry.execute("no_such", "obj_1")
        self.assertFalse(result.success)
        self.assertIn("not found", result.error)

    def test_execute_with_permissions(self):
        def perm_handler(object_id, **kw):
            return {"allowed": True}
        self.registry.register(
            "admin_action", "Admin", ActionCategory.READ,
            perm_handler, requires_permissions=["admin"],
        )
        # Without permission
        result = self.registry.execute("admin_action", "obj_1", user_permissions=["read"])
        self.assertFalse(result.success)
        self.assertIn("Missing permissions", result.error)
        # With permission
        result = self.registry.execute("admin_action", "obj_1", user_permissions=["admin"])
        self.assertTrue(result.success)

    def test_execute_handler_error(self):
        def failing_handler(object_id, **kw):
            raise RuntimeError("Handler failed")
        self.registry.register("fail", "Fail", ActionCategory.READ, failing_handler)
        result = self.registry.execute("fail", "obj_1")
        self.assertFalse(result.success)
        self.assertIn("Handler failed", result.error)

    def test_execution_history(self):
        self.registry.register("h1", "H1", ActionCategory.READ, lambda object_id, **kw: {"ok": True})
        self.registry.execute("h1", "obj_1")
        self.registry.execute("h1", "obj_2")
        history = self.registry.get_execution_history()
        self.assertEqual(len(history), 2)

    def test_execution_history_filter(self):
        self.registry.register("a1", "A1", ActionCategory.READ, lambda object_id, **kw: None)
        self.registry.register("a2", "A2", ActionCategory.READ, lambda object_id, **kw: None)
        self.registry.execute("a1", "obj_1")
        self.registry.execute("a2", "obj_1")
        self.registry.execute("a1", "obj_2")
        # Filter by action
        history = self.registry.get_execution_history(action_id="a1")
        self.assertEqual(len(history), 2)
        # Filter by object
        history = self.registry.get_execution_history(object_id="obj_1")
        self.assertEqual(len(history), 2)

    def test_stats(self):
        self.registry.register("s1", "S1", ActionCategory.READ, lambda **kw: None)
        self.registry.register("s2", "S2", ActionCategory.ANALYZE, lambda **kw: None)
        self.registry.execute("s1", "obj_1")
        stats = self.registry.get_stats()
        self.assertEqual(stats["total_actions"], 2)
        self.assertEqual(stats["total_executions"], 1)
        self.assertEqual(stats["by_category"]["read"], 1)
        self.assertEqual(stats["by_category"]["analyze"], 1)


class TestBuiltinActions(unittest.TestCase):

    def setUp(self):
        self.registry = ActionsRegistry()
        register_builtin_actions(self.registry)

    def test_read_action(self):
        class MockObj:
            def to_dict(self):
                return {"type": "test", "data": [1, 2, 3]}
        result = self.registry.execute("read", "obj_1", obj=MockObj())
        self.assertTrue(result.success)
        self.assertEqual(result.output["type"], "test")

    def test_read_no_object(self):
        result = self.registry.execute("read", "obj_1")
        self.assertTrue(result.success)
        self.assertIn("error", result.output)

    def test_summarize_action(self):
        class MockObj:
            def to_dict(self):
                return {"type": "dataset", "content": "x" * 500}
        result = self.registry.execute("summarize", "obj_1", obj=MockObj())
        self.assertTrue(result.success)
        self.assertIn("summary", result.output)

    def test_validate_action(self):
        class MockObj:
            pass
        result = self.registry.execute("validate", "obj_1", obj=MockObj())
        self.assertTrue(result.success)
        self.assertTrue(result.output["valid"])

    def test_metadata_action(self):
        class MockObj:
            def to_dict(self):
                return {"type": "doc", "version": 3, "timestamps": {"created": "2024-01-01"}}
        result = self.registry.execute("metadata", "obj_1", obj=MockObj())
        self.assertTrue(result.success)
        self.assertEqual(result.output["version"], 3)

    def test_duplicate_action(self):
        class MockObj:
            def create_new_version(self):
                return MockObj()
        result = self.registry.execute("duplicate", "obj_1", obj=MockObj())
        self.assertTrue(result.success)
        self.assertTrue(result.output["duplicated"])

    def test_builtin_count(self):
        stats = self.registry.get_stats()
        self.assertEqual(stats["total_actions"], 5)


class TestObjectAction(unittest.TestCase):

    def test_is_applicable_to(self):
        action = ObjectAction(
            action_id="test",
            name="Test",
            category=ActionCategory.READ,
            handler=lambda **kw: None,
            applicable_types=["dataset", "document"],
        )
        self.assertTrue(action.is_applicable_to("dataset"))
        self.assertTrue(action.is_applicable_to("document"))
        self.assertFalse(action.is_applicable_to("code"))

    def test_is_applicable_to_any(self):
        action = ObjectAction(
            action_id="test",
            name="Test",
            category=ActionCategory.READ,
            handler=lambda **kw: None,
            applicable_types=[],
        )
        self.assertTrue(action.is_applicable_to("anything"))

    def test_to_dict(self):
        action = ObjectAction(
            action_id="test",
            name="Test",
            category=ActionCategory.ANALYZE,
            handler=lambda **kw: None,
            description="Test action",
            applicable_types=["dataset"],
        )
        d = action.to_dict()
        self.assertEqual(d["action_id"], "test")
        self.assertEqual(d["category"], "analyze")
        self.assertIn("dataset", d["applicable_types"])


class TestActionResult(unittest.TestCase):

    def test_to_dict_success(self):
        result = ActionResult(
            action_id="a1",
            object_id="o1",
            success=True,
            output={"data": 42},
            execution_time_ms=1.5,
        )
        d = result.to_dict()
        self.assertTrue(d["success"])
        self.assertEqual(d["output"]["data"], 42)
        self.assertEqual(d["execution_time_ms"], 1.5)

    def test_to_dict_failure(self):
        result = ActionResult(
            action_id="a1",
            object_id="o1",
            success=False,
            error="Something went wrong",
        )
        d = result.to_dict()
        self.assertFalse(d["success"])
        self.assertIsNone(d["output"])
        self.assertEqual(d["error"], "Something went wrong")


class TestActionCategory(unittest.TestCase):

    def test_all_categories(self):
        for cat in ActionCategory:
            self.assertIsInstance(cat.value, str)


if __name__ == "__main__":
    unittest.main()
