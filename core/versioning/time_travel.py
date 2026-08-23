"""
Bi-Temporal Time-Travel Engine for DataOS (Rule #27).
Supports:
- Validity Time: when the fact is true in the real world (valid_from, valid_to).
- Transaction / System Time: when DataOS recorded it (recorded_at, superseded_at).
- as_of(timestamp): Point-in-time object and graph topology reconstruction.
- changes_between(t1, t2): State and topology difference between two historical timestamps.
"""

from __future__ import annotations
import datetime
from typing import Dict, Any, List, Optional, Tuple, Set
from dataclasses import dataclass, field
from core.object.model import DataObject
from core.relation.model import Relationship
from infrastructure.storage.base import StorageBackend


@dataclass
class BiTemporalInterval:
    """Bi-temporal interval representing both real-world validity and system recording time."""
    valid_from: str
    valid_to: Optional[str] = None  # None indicates currently valid
    system_recorded_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    system_superseded_at: Optional[str] = None  # None indicates current system state

    def is_valid_at(self, timestamp: str, axis: str = "system_time") -> bool:
        """Check if this interval is active at the given timestamp along the specified axis."""
        if axis == "validity_time":
            if self.valid_from > timestamp:
                return False
            if self.valid_to and self.valid_to < timestamp:
                return False
            return True
        else:  # system_time
            if self.system_recorded_at > timestamp:
                return False
            if self.system_superseded_at and self.system_superseded_at <= timestamp:
                return False
            return True


class TimeTravelEngine:
    """Reconstructs historical object states and graph topologies as of any point in time."""

    def __init__(self, storage: StorageBackend):
        self.storage = storage

    def get_object_as_of(
        self,
        object_id: str,
        as_of_timestamp: str,
        temporal_axis: str = "system_time"
    ) -> Optional[DataObject]:
        """
        Reconstruct the state of a DataObject as it existed at `as_of_timestamp`.
        Uses version history snapshots in storage.
        """
        # Fetch all version snapshots for this object from storage
        snapshots = self.storage.get_version_history(object_id)
        if not snapshots:
            # Check current object if no snapshot history exists
            current = self.storage.get_object(object_id)
            if current and current.timestamps["created_at"] <= as_of_timestamp:
                return current
            return None

        # Filter snapshots valid as of timestamp
        valid_snapshots = []
        for s in snapshots:
            rec_time = s.get("created_at") or s.get("system_recorded_at") or ""
            if temporal_axis == "validity_time":
                val_from = s.get("data_snapshot", {}).get("properties", {}).get("valid_from", rec_time)
                val_to = s.get("data_snapshot", {}).get("properties", {}).get("valid_to")
                if val_from <= as_of_timestamp and (val_to is None or val_to >= as_of_timestamp):
                    valid_snapshots.append(s)
            else:  # system_time
                if rec_time <= as_of_timestamp:
                    valid_snapshots.append(s)

        if not valid_snapshots:
            return None

        # Pick the latest valid snapshot
        valid_snapshots.sort(key=lambda x: x.get("version", 0))
        latest_snapshot = valid_snapshots[-1]
        
        # Reconstruct DataObject from snapshot dictionary
        return DataObject.from_dict(latest_snapshot["data_snapshot"])

    def get_graph_as_of(
        self,
        as_of_timestamp: str,
        temporal_axis: str = "system_time"
    ) -> Dict[str, Any]:
        """
        Reconstruct the entire graph topology (active objects and active relationships)
        as it existed at `as_of_timestamp`.
        """
        all_objects = self.storage.list_objects(limit=10000)
        all_relationships = self.storage.list_relationships(limit=10000)

        active_objects: List[DataObject] = []
        for obj in all_objects:
            historical_obj = self.get_object_as_of(obj.id, as_of_timestamp, temporal_axis=temporal_axis)
            if historical_obj:
                active_objects.append(historical_obj)

        active_obj_ids = {o.id for o in active_objects}

        # Filter relationships created on or before timestamp between active objects
        active_relationships: List[Relationship] = []
        for rel in all_relationships:
            created_at = rel.created_at or ""
            if created_at <= as_of_timestamp:
                if rel.source in active_obj_ids and rel.target in active_obj_ids:
                    active_relationships.append(rel)

        return {
            "as_of_timestamp": as_of_timestamp,
            "temporal_axis": temporal_axis,
            "total_objects": len(active_objects),
            "total_relationships": len(active_relationships),
            "objects": [o.to_dict() for o in active_objects],
            "relationships": [r.to_dict() for r in active_relationships]
        }

    def changes_between(
        self,
        t1: str,
        t2: str,
        temporal_axis: str = "system_time"
    ) -> Dict[str, Any]:
        """
        Compute differences and mutations that occurred between timestamp t1 and t2:
        - Created objects
        - Modified objects (property level diffs)
        - Deleted/superseded objects
        - Added/removed relationships
        """
        g1 = self.get_graph_as_of(t1, temporal_axis=temporal_axis)
        g2 = self.get_graph_as_of(t2, temporal_axis=temporal_axis)

        g1_objs = {o["id"]: o for o in g1["objects"]}
        g2_objs = {o["id"]: o for o in g2["objects"]}

        created_objects = [g2_objs[oid] for oid in g2_objs if oid not in g1_objs]
        deleted_objects = [g1_objs[oid] for oid in g1_objs if oid not in g2_objs]

        modified_objects = []
        for oid in g1_objs:
            if oid in g2_objs:
                o1 = g1_objs[oid]
                o2 = g2_objs[oid]
                if o1.get("version") != o2.get("version") or o1.get("metadata", {}).get("content_hash") != o2.get("metadata", {}).get("content_hash"):
                    # Compute property differences
                    prop_diffs = {}
                    p1 = o1.get("properties", {})
                    p2 = o2.get("properties", {})
                    all_keys = set(p1.keys()).union(p2.keys())
                    for k in all_keys:
                        if p1.get(k) != p2.get(k):
                            prop_diffs[k] = {"before": p1.get(k), "after": p2.get(k)}

                    modified_objects.append({
                        "object_id": oid,
                        "version_before": o1.get("version"),
                        "version_after": o2.get("version"),
                        "property_changes": prop_diffs
                    })

        g1_rel_keys = {(r["source"], r["target"], r["relation_type"]): r for r in g1["relationships"]}
        g2_rel_keys = {(r["source"], r["target"], r["relation_type"]): r for r in g2["relationships"]}

        added_relationships = [g2_rel_keys[k] for k in g2_rel_keys if k not in g1_rel_keys]
        removed_relationships = [g1_rel_keys[k] for k in g1_rel_keys if k not in g2_rel_keys]

        return {
            "from_timestamp": t1,
            "to_timestamp": t2,
            "created_objects_count": len(created_objects),
            "modified_objects_count": len(modified_objects),
            "deleted_objects_count": len(deleted_objects),
            "added_relationships_count": len(added_relationships),
            "removed_relationships_count": len(removed_relationships),
            "created_objects": created_objects,
            "modified_objects": modified_objects,
            "deleted_objects": deleted_objects,
            "added_relationships": added_relationships,
            "removed_relationships": removed_relationships
        }
