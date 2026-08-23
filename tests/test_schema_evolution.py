"""
Tests for Schema Evolution Tracker (Rule #14).
Validates versioning, change detection, compatibility checks, and migration.
"""

import unittest
from core.schema.evolution import (
    SchemaEvolutionTracker, SchemaVersion, SchemaChange,
    SchemaChangeType, ChangeImpact,
)


class TestSchemaEvolutionTracker(unittest.TestCase):

    def setUp(self):
        self.tracker = SchemaEvolutionTracker()

    def test_register_schema(self):
        v = self.tracker.register("ds1", {"id": "int", "name": "string"})
        self.assertIsNotNone(v.version_id)
        self.assertEqual(v.dataset_id, "ds1")

    def test_get_current(self):
        self.tracker.register("ds1", {"id": "int"})
        current = self.tracker.get_current("ds1")
        self.assertEqual(current.columns, {"id": "int"})

    def test_get_versions(self):
        self.tracker.register("ds1", {"id": "int"})
        self.tracker.register("ds1", {"id": "int", "name": "string"})
        versions = self.tracker.get_versions("ds1")
        self.assertEqual(len(versions), 2)

    def test_detect_changes_no_change(self):
        self.tracker.register("ds1", {"id": "int"})
        changes = self.tracker.detect_changes("ds1", {"id": "int"})
        self.assertEqual(len(changes), 0)

    def test_detect_column_added(self):
        self.tracker.register("ds1", {"id": "int"})
        changes = self.tracker.detect_changes("ds1", {"id": "int", "email": "string"})
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].change_type, SchemaChangeType.COLUMN_ADDED)
        self.assertEqual(changes[0].impact, ChangeImpact.NON_BREAKING)

    def test_detect_column_removed(self):
        self.tracker.register("ds1", {"id": "int", "name": "string"})
        changes = self.tracker.detect_changes("ds1", {"id": "int"})
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].change_type, SchemaChangeType.COLUMN_REMOVED)
        self.assertEqual(changes[0].impact, ChangeImpact.BREAKING)

    def test_detect_type_changed(self):
        self.tracker.register("ds1", {"id": "int"})
        changes = self.tracker.detect_changes("ds1", {"id": "string"})
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].change_type, SchemaChangeType.TYPE_CHANGED)
        self.assertEqual(changes[0].impact, ChangeImpact.POTENTIALLY_BREAKING)

    def test_apply_changes(self):
        self.tracker.register("ds1", {"id": "int"})
        report = self.tracker.apply_changes("ds1", {"id": "int", "name": "string"}, description="add name")
        self.assertEqual(report["total_changes"], 1)
        self.assertFalse(report["has_breaking"])

    def test_apply_breaking_change(self):
        self.tracker.register("ds1", {"id": "int", "name": "string"})
        report = self.tracker.apply_changes("ds1", {"id": "int"})
        self.assertTrue(report["has_breaking"])
        self.assertEqual(report["breaking_changes"], 1)

    def test_is_compatible(self):
        self.tracker.register("ds1", {"id": "int", "name": "string"})
        result = self.tracker.is_compatible("ds1", {"id": "int"})
        self.assertTrue(result["compatible"])

    def test_is_compatible_missing_column(self):
        self.tracker.register("ds1", {"id": "int"})
        result = self.tracker.is_compatible("ds1", {"id": "int", "email": "string"})
        self.assertFalse(result["compatible"])
        self.assertGreater(len(result["issues"]), 0)

    def test_is_compatible_type_mismatch(self):
        self.tracker.register("ds1", {"id": "int"})
        result = self.tracker.is_compatible("ds1", {"id": "string"})
        self.assertFalse(result["compatible"])

    def test_no_schema_registered(self):
        result = self.tracker.is_compatible("nonexistent", {"id": "int"})
        self.assertFalse(result["compatible"])

    def test_stats(self):
        self.tracker.register("ds1", {"id": "int"})
        self.tracker.register("ds2", {"x": "float"})
        stats = self.tracker.get_stats()
        self.assertEqual(stats["datasets_tracked"], 2)
        self.assertEqual(stats["total_versions"], 2)


class TestSchemaVersion(unittest.TestCase):

    def test_to_dict(self):
        v = SchemaVersion("v1", "ds1", {"id": "int"}, description="initial")
        d = v.to_dict()
        self.assertEqual(d["version_id"], "v1")
        self.assertEqual(d["dataset_id"], "ds1")


class TestSchemaChange(unittest.TestCase):

    def test_to_dict(self):
        c = SchemaChange(SchemaChangeType.COLUMN_ADDED, "email", new_value="string")
        d = c.to_dict()
        self.assertEqual(d["change_type"], "column_added")
        self.assertEqual(d["column_name"], "email")


class TestChangeImpact(unittest.TestCase):

    def test_values(self):
        self.assertEqual(ChangeImpact.BREAKING.value, "breaking")
        self.assertEqual(ChangeImpact.NON_BREAKING.value, "non_breaking")
        self.assertEqual(ChangeImpact.POTENTIALLY_BREAKING.value, "potentially_breaking")


if __name__ == "__main__":
    unittest.main()
