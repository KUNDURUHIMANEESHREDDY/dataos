"""Regression tests for timezone-correct bitemporal comparisons."""

import unittest

from core.object.model import DataObject
from core.relation.model import Relationship
from core.versioning.time_travel import BiTemporalInterval, TimeTravelEngine


class MemoryStorage:
    def __init__(self, objects=None, snapshots=None, relationships=None):
        self.objects = {obj.id: obj for obj in (objects or [])}
        self.snapshots = snapshots or {}
        self.relationships = relationships or []

    def get_version_history(self, object_id):
        return self.snapshots.get(object_id, [])

    def get_object(self, object_id):
        return self.objects.get(object_id)

    def list_objects(self, limit=10000):
        return list(self.objects.values())[:limit]

    def list_relationships(self, limit=10000):
        return self.relationships[:limit]


def snapshot_for(obj, created_at=None):
    return {
        "created_at": created_at or obj.timestamps.created_at,
        "version": obj.version,
        "data_snapshot": obj.to_dict(),
    }


class TestTimeTravelTimezoneOrdering(unittest.TestCase):
    def test_system_time_compares_offset_timestamp_as_an_instant(self):
        stored_at = "2026-01-01T01:00:00+01:00"
        obj = DataObject(
            id="offset-object",
            timestamps={"created_at": stored_at, "updated_at": stored_at},
            properties={"source": "offset"},
        )
        storage = MemoryStorage(
            objects=[obj],
            snapshots={obj.id: [snapshot_for(obj, stored_at)]},
        )

        result = TimeTravelEngine(storage).get_object_as_of(
            obj.id, "2026-01-01T00:30:00Z"
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.id, obj.id)

    def test_current_object_fallback_reads_timestamp_dataclass(self):
        created_at = "2026-01-01T01:00:00+01:00"
        obj = DataObject(
            id="current-only",
            timestamps={"created_at": created_at, "updated_at": created_at},
        )
        storage = MemoryStorage(objects=[obj])

        result = TimeTravelEngine(storage).get_object_as_of(
            obj.id, "2026-01-01T00:30:00Z"
        )

        self.assertIs(result, obj)

    def test_validity_window_compares_mixed_offsets_chronologically(self):
        recorded_at = "2025-12-31T23:00:00Z"
        obj = DataObject(
            id="validity-object",
            timestamps={"created_at": recorded_at, "updated_at": recorded_at},
            properties={
                "valid_from": "2026-01-01T01:00:00+01:00",
                "valid_to": "2026-01-01T02:00:00+01:00",
            },
        )
        storage = MemoryStorage(
            objects=[obj],
            snapshots={obj.id: [snapshot_for(obj, recorded_at)]},
        )

        result = TimeTravelEngine(storage).get_object_as_of(
            obj.id, "2026-01-01T00:30:00Z", temporal_axis="validity_time"
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.id, obj.id)

    def test_graph_includes_relationship_created_before_boundary_in_other_offset(self):
        created_at = "2025-12-31T22:00:00Z"
        source = DataObject(
            id="source",
            timestamps={"created_at": created_at, "updated_at": created_at},
        )
        target = DataObject(
            id="target",
            timestamps={"created_at": created_at, "updated_at": created_at},
        )
        relationship = Relationship(
            source=source.id,
            target=target.id,
            created_at="2026-01-01T01:00:00+01:00",
        )
        storage = MemoryStorage(
            objects=[source, target],
            snapshots={
                source.id: [snapshot_for(source, created_at)],
                target.id: [snapshot_for(target, created_at)],
            },
            relationships=[relationship],
        )

        graph = TimeTravelEngine(storage).get_graph_as_of("2026-01-01T00:30:00Z")

        self.assertEqual(graph["total_relationships"], 1)
        self.assertEqual(graph["relationships"][0]["id"], relationship.id)

    def test_system_time_graph_excludes_soft_deleted_relationship_at_deletion(self):
        created_at = "2026-01-01T00:00:00Z"
        source = DataObject(id="source-deleted-edge", timestamps={"created_at": created_at, "updated_at": created_at})
        target = DataObject(id="target-deleted-edge", timestamps={"created_at": created_at, "updated_at": created_at})
        relationship = Relationship(
            source=source.id,
            target=target.id,
            created_at="2026-01-01T01:00:00+01:00",
            deleted_at="2026-01-01T02:00:00+01:00",
        )
        storage = MemoryStorage(
            objects=[source, target],
            snapshots={source.id: [snapshot_for(source)], target.id: [snapshot_for(target)]},
            relationships=[relationship],
        )
        engine = TimeTravelEngine(storage)

        before_deletion = engine.get_graph_as_of("2026-01-01T00:30:00Z")
        at_deletion = engine.get_graph_as_of("2026-01-01T01:00:00Z")

        self.assertEqual(before_deletion["total_relationships"], 1)
        self.assertEqual(at_deletion["total_relationships"], 0)

    def test_validity_time_graph_uses_explicit_relationship_interval(self):
        created_at = "2025-12-31T23:00:00Z"
        source = DataObject(id="source-valid-edge", timestamps={"created_at": created_at, "updated_at": created_at})
        target = DataObject(id="target-valid-edge", timestamps={"created_at": created_at, "updated_at": created_at})
        relationship = Relationship(
            source=source.id,
            target=target.id,
            created_at=created_at,
            metadata={
                "valid_from": "2026-01-01T01:00:00+01:00",
                "valid_to": "2026-01-01T02:00:00+01:00",
            },
        )
        storage = MemoryStorage(
            objects=[source, target],
            snapshots={source.id: [snapshot_for(source)], target.id: [snapshot_for(target)]},
            relationships=[relationship],
        )
        engine = TimeTravelEngine(storage)

        inside_interval = engine.get_graph_as_of("2026-01-01T00:30:00Z", temporal_axis="validity_time")
        outside_interval = engine.get_graph_as_of("2026-01-01T01:30:00Z", temporal_axis="validity_time")

        self.assertEqual(inside_interval["total_relationships"], 1)
        self.assertEqual(outside_interval["total_relationships"], 0)

    def test_validity_time_graph_does_not_infer_validity_from_creation_time(self):
        created_at = "2026-01-01T00:00:00Z"
        source = DataObject(id="source-no-validity", timestamps={"created_at": created_at, "updated_at": created_at})
        target = DataObject(id="target-no-validity", timestamps={"created_at": created_at, "updated_at": created_at})
        relationship = Relationship(source=source.id, target=target.id, created_at=created_at)
        storage = MemoryStorage(
            objects=[source, target],
            snapshots={source.id: [snapshot_for(source)], target.id: [snapshot_for(target)]},
            relationships=[relationship],
        )

        graph = TimeTravelEngine(storage).get_graph_as_of(
            "2026-01-02T00:00:00Z", temporal_axis="validity_time"
        )

        self.assertEqual(graph["total_relationships"], 0)

    def test_validity_time_relationship_interval_includes_exact_end_boundary(self):
        created_at = "2025-12-31T23:00:00Z"
        source = DataObject(id="source-valid-boundary", timestamps={"created_at": created_at, "updated_at": created_at})
        target = DataObject(id="target-valid-boundary", timestamps={"created_at": created_at, "updated_at": created_at})
        relationship = Relationship(
            source=source.id,
            target=target.id,
            created_at=created_at,
            metadata={"valid_from": "2026-01-01T00:00:00Z", "valid_to": "2026-01-01T01:00:00Z"},
        )
        storage = MemoryStorage(
            objects=[source, target],
            snapshots={source.id: [snapshot_for(source)], target.id: [snapshot_for(target)]},
            relationships=[relationship],
        )

        graph = TimeTravelEngine(storage).get_graph_as_of(
            "2026-01-01T01:00:00Z", temporal_axis="validity_time"
        )

        self.assertEqual(graph["total_relationships"], 1)

    def test_invalid_relationship_validity_timestamp_fails_closed(self):
        created_at = "2026-01-01T00:00:00Z"
        source = DataObject(id="source-invalid-validity", timestamps={"created_at": created_at, "updated_at": created_at})
        target = DataObject(id="target-invalid-validity", timestamps={"created_at": created_at, "updated_at": created_at})
        relationship = Relationship(
            source=source.id,
            target=target.id,
            created_at=created_at,
            metadata={"valid_from": "not-a-timestamp"},
        )
        storage = MemoryStorage(
            objects=[source, target],
            snapshots={source.id: [snapshot_for(source)], target.id: [snapshot_for(target)]},
            relationships=[relationship],
        )

        with self.assertRaisesRegex(ValueError, "relationship.valid_from must be a valid ISO 8601 timestamp"):
            TimeTravelEngine(storage).get_graph_as_of(
                "2026-01-02T00:00:00Z", temporal_axis="validity_time"
            )

    def test_bitemporal_interval_uses_utc_instants(self):
        interval = BiTemporalInterval(
            valid_from="2026-01-01T01:00:00+01:00",
            valid_to="2026-01-01T02:00:00+01:00",
            system_recorded_at="2025-12-31T23:00:00Z",
        )

        self.assertTrue(interval.is_valid_at("2026-01-01T00:30:00Z", "validity_time"))
        self.assertTrue(interval.is_valid_at("2026-01-01T00:30:00Z", "system_time"))


    def test_unsupported_temporal_axis_is_rejected_by_engine_contracts(self):
        interval = BiTemporalInterval(valid_from="2026-01-01T00:00:00Z")
        engine = TimeTravelEngine(MemoryStorage())

        with self.assertRaisesRegex(ValueError, "temporal_axis must be"):
            interval.is_valid_at("2026-01-01T00:00:00Z", "transaction_time")

        with self.assertRaisesRegex(ValueError, "temporal_axis must be"):
            engine.get_object_as_of("missing", "2026-01-01T00:00:00Z", temporal_axis="transaction_time")

        with self.assertRaisesRegex(ValueError, "temporal_axis must be"):
            engine.get_graph_as_of("2026-01-01T00:00:00Z", temporal_axis="transaction_time")

        with self.assertRaisesRegex(ValueError, "temporal_axis must be"):
            engine.changes_between(
                "2026-01-01T00:00:00Z",
                "2026-01-02T00:00:00Z",
                temporal_axis="transaction_time",
            )


if __name__ == "__main__":
    unittest.main()
