"""
Tests for Bi-Temporal Time-Travel & Distributed Sync with Conflict Modeling (Rules #27, #29, #59).
"""

import unittest
import tempfile
import os
import time
import datetime
from core.object.model import DataObject, ObjectType
from core.relation.model import Relationship, RelationType
from infrastructure.storage.sqlite_store import SQLiteStorage
from core.versioning.time_travel import TimeTravelEngine, BiTemporalInterval
from infrastructure.sync.sync_engine import VectorClock, ClockOrdering, DistributedSyncEngine


class TestBiTemporalAndTimeTravel(unittest.TestCase):

    def setUp(self):
        self.temp_db = tempfile.mktemp(suffix=".db")
        self.storage = SQLiteStorage(db_path=self.temp_db)
        self.time_travel = TimeTravelEngine(self.storage)
        self.sync_engine = DistributedSyncEngine(self.storage, node_id="node_us_east")

    def tearDown(self):
        if os.path.exists(self.temp_db):
            os.remove(self.temp_db)

    def test_point_in_time_object_travel(self):
        """Rule #27: Query historical state of an object as_of(timestamp)."""
        t0 = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=10)).isoformat()
        
        # Version 1
        obj = DataObject(
            type="dataset",
            properties={"name": "q1_metrics", "revenue": 100000, "status": "draft"},
            source="file://q1.csv"
        )
        saved_v1 = self.storage.save_object(obj)
        t1 = saved_v1.timestamps.updated_at

        # Version 2
        time.sleep(0.01)
        v2 = saved_v1.create_new_version(
            new_properties={"revenue": 125000, "status": "reviewed"},
            transformation_desc="Updated revenue after review"
        )
        saved_v2 = self.storage.save_object(v2)
        t2 = saved_v2.timestamps.updated_at

        # Version 3
        time.sleep(0.01)
        v3 = saved_v2.create_new_version(
            new_properties={"revenue": 130000, "status": "audited"},
            transformation_desc="Final audit adjustment"
        )
        saved_v3 = self.storage.save_object(v3)
        t3 = saved_v3.timestamps.updated_at

        # 1. Travel to t0 (Before object existed)
        obj_at_t0 = self.time_travel.get_object_as_of(obj.id, t0)
        self.assertIsNone(obj_at_t0)

        # 2. Travel to t1 (Version 1)
        obj_at_t1 = self.time_travel.get_object_as_of(obj.id, t1)
        self.assertIsNotNone(obj_at_t1)
        self.assertEqual(obj_at_t1.version, 1)
        self.assertEqual(obj_at_t1.properties["revenue"], 100000)
        self.assertEqual(obj_at_t1.properties["status"], "draft")

        # 3. Travel to t2 (Version 2)
        obj_at_t2 = self.time_travel.get_object_as_of(obj.id, t2)
        self.assertIsNotNone(obj_at_t2)
        self.assertEqual(obj_at_t2.version, 2)
        self.assertEqual(obj_at_t2.properties["revenue"], 125000)
        self.assertEqual(obj_at_t2.properties["status"], "reviewed")

        # 4. Travel to t3 (Version 3)
        obj_at_t3 = self.time_travel.get_object_as_of(obj.id, t3)
        self.assertIsNotNone(obj_at_t3)
        self.assertEqual(obj_at_t3.version, 3)
        self.assertEqual(obj_at_t3.properties["revenue"], 130000)
        self.assertEqual(obj_at_t3.properties["status"], "audited")

    def test_changes_between_historical_timestamps(self):
        """Rule #27: Compute exact state & relationship diffs between t1 and t2."""
        obj = self.storage.save_object(DataObject(
            type="document",
            properties={"title": "Original Title", "score": 10},
            source="file://doc.md"
        ))
        t1 = obj.timestamps.updated_at

        time.sleep(0.01)
        obj_target = self.storage.save_object(DataObject(type="dataset", source="file://data.csv"))
        
        # Modify object and add relationship
        v2 = obj.create_new_version(new_properties={"title": "Updated Title", "score": 25})
        self.storage.save_object(v2)
        self.storage.save_relationship(Relationship(
            source=obj.id,
            target=obj_target.id,
            relation_type=RelationType.DERIVED_FROM.value
        ))
        t2 = datetime.datetime.now(datetime.timezone.utc).isoformat()

        changes = self.time_travel.changes_between(t1, t2)
        self.assertEqual(changes["modified_objects_count"], 1)
        self.assertEqual(changes["added_relationships_count"], 1)
        
        prop_changes = changes["modified_objects"][0]["property_changes"]
        self.assertEqual(prop_changes["title"]["before"], "Original Title")
        self.assertEqual(prop_changes["title"]["after"], "Updated Title")
        self.assertEqual(prop_changes["score"]["before"], 10)
        self.assertEqual(prop_changes["score"]["after"], 25)

    def test_vector_clock_causal_ordering(self):
        """Rule #29: Vector clock causal relationship detection."""
        clock_a = VectorClock({"node_1": 1, "node_2": 0})
        clock_b = VectorClock({"node_1": 2, "node_2": 1})
        clock_c = VectorClock({"node_1": 1, "node_2": 2})

        self.assertEqual(clock_a.compare(clock_b), ClockOrdering.BEFORE)
        self.assertEqual(clock_b.compare(clock_a), ClockOrdering.AFTER)
        self.assertEqual(clock_a.compare(clock_a), ClockOrdering.EQUAL)
        self.assertEqual(clock_b.compare(clock_c), ClockOrdering.CONCURRENT)

        # Merge
        merged = clock_b.merge(clock_c)
        self.assertEqual(merged.clock, {"node_1": 2, "node_2": 2})

    def test_three_way_merge_and_explicit_conflict_modeling(self):
        """Rule #29 & Rule #59: Clean merge vs Explicit Conflict Object generation and resolution."""
        base_obj = self.storage.save_object(DataObject(
            type="dataset",
            properties={"author": "Alice", "status": "draft", "max_rows": 1000},
            content="col1,col2\n1,2"
        ))

        # Scenario 1: Clean merge (Local changes status, Remote changes max_rows)
        local_obj_clean = base_obj.create_new_version(new_properties={"status": "published"})
        incoming_obj_clean = base_obj.create_new_version(new_properties={"max_rows": 5000})

        clean_res = self.sync_engine.three_way_merge(
            base_obj=base_obj,
            local_obj=local_obj_clean,
            incoming_obj=incoming_obj_clean,
            local_clock=VectorClock({"node_a": 2, "node_b": 1}),
            incoming_clock=VectorClock({"node_a": 1, "node_b": 2})
        )
        self.assertTrue(clean_res["merged"])
        self.assertEqual(clean_res["status"], "clean_merge")
        self.assertEqual(clean_res["merged_object"]["properties"]["status"], "published")
        self.assertEqual(clean_res["merged_object"]["properties"]["max_rows"], 5000)

        # Scenario 2: Concurrent Conflict (Both modify 'status' with different values)
        local_obj_conflict = base_obj.create_new_version(new_properties={"status": "approved_by_legal"})
        incoming_obj_conflict = base_obj.create_new_version(new_properties={"status": "rejected_by_audit"})

        conflict_res = self.sync_engine.three_way_merge(
            base_obj=base_obj,
            local_obj=local_obj_conflict,
            incoming_obj=incoming_obj_conflict
        )
        self.assertFalse(conflict_res["merged"])
        self.assertEqual(conflict_res["status"], "conflict_detected")
        self.assertIn("status", conflict_res["conflicting_fields"])

        # Verify conflict is stored as a first-class DataObject
        conflict_obj_id = conflict_res["conflict_object_id"]
        conflict_obj = self.storage.get_object(conflict_obj_id)
        self.assertIsNotNone(conflict_obj)
        self.assertEqual(conflict_obj.schema, "conflict.v1")
        self.assertFalse(conflict_obj.properties["resolved"])

        # Scenario 3: Explicit Conflict Resolution
        resolve_res = self.sync_engine.resolve_conflict(
            conflict_object_id=conflict_obj_id,
            strategy="manual_merge",
            manual_properties={"author": "Alice", "status": "approved_with_audit_conditions", "max_rows": 1000}
        )
        self.assertEqual(resolve_res["status"], "resolved")
        self.assertEqual(resolve_res["strategy"], "manual_merge")

        # Verify target object is updated to resolved version
        resolved_target = self.storage.get_object(base_obj.id)
        self.assertEqual(resolved_target.properties["status"], "approved_with_audit_conditions")


if __name__ == "__main__":
    unittest.main()
