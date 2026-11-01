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


def _parse_timestamp(value: Optional[str], field_name: str) -> Optional[datetime.datetime]:
    """Parse persisted ISO timestamps into UTC instants.

    DataOS-generated timestamps are UTC-aware. Older imported records may be
    timezone-naive; for backward compatibility those values are interpreted as
    UTC. API request timestamps are validated more strictly at the HTTP boundary.
    Invalid persisted values fail explicitly instead of producing a false
    historical result through lexicographic string comparison.
    """
    if value is None or value == "":
        return None
    if not isinstance(value, str) or value != value.strip() or len(value) > 64:
        raise ValueError(f"{field_name} must be a bounded ISO 8601 timestamp")

    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.datetime.fromisoformat(candidate)
    except (ValueError, OverflowError):
        raise ValueError(f"{field_name} must be a valid ISO 8601 timestamp") from None

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.astimezone(datetime.timezone.utc)


@dataclass
class BiTemporalInterval:
    """Bi-temporal interval representing both real-world validity and system recording time."""
    valid_from: str
    valid_to: Optional[str] = None  # None indicates currently valid
    system_recorded_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    system_superseded_at: Optional[str] = None  # None indicates current system state

    def is_valid_at(self, timestamp: str, axis: str = "system_time") -> bool:
        """Check interval membership using chronological UTC instants."""
        instant = _parse_timestamp(timestamp, "timestamp")
        if instant is None:
            return False

        if axis == "validity_time":
            start = _parse_timestamp(self.valid_from, "valid_from")
            end = _parse_timestamp(self.valid_to, "valid_to")
            if start is None or start > instant:
                return False
            if end is not None and end < instant:
                return False
            return True

        start = _parse_timestamp(self.system_recorded_at, "system_recorded_at")
        end = _parse_timestamp(self.system_superseded_at, "system_superseded_at")
        if start is None or start > instant:
            return False
        if end is not None and end <= instant:
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
        """Reconstruct an object using timezone-correct historical comparisons."""
        boundary = _parse_timestamp(as_of_timestamp, "as_of_timestamp")
        if boundary is None:
            raise ValueError("as_of_timestamp is required")

        snapshots = self.storage.get_version_history(object_id)
        if not snapshots:
            current = self.storage.get_object(object_id)
            if current:
                timestamps = current.timestamps
                created_at = (
                    timestamps.get("created_at")
                    if isinstance(timestamps, dict)
                    else getattr(timestamps, "created_at", None)
                )
                created = _parse_timestamp(created_at, "object.created_at")
                if created is not None and created <= boundary:
                    return current
            return None

        valid_snapshots = []
        for snapshot in snapshots:
            recorded_at = snapshot.get("created_at") or snapshot.get("system_recorded_at")
            if temporal_axis == "validity_time":
                properties = snapshot.get("data_snapshot", {}).get("properties", {})
                valid_from = properties.get("valid_from") or recorded_at
                valid_to = properties.get("valid_to")
                start = _parse_timestamp(valid_from, "snapshot.valid_from")
                end = _parse_timestamp(valid_to, "snapshot.valid_to")
                if start is not None and start <= boundary and (end is None or end >= boundary):
                    valid_snapshots.append(snapshot)
            else:  # system_time
                recorded = _parse_timestamp(recorded_at, "snapshot.created_at")
                if recorded is not None and recorded <= boundary:
                    valid_snapshots.append(snapshot)

        if not valid_snapshots:
            return None

        # Version numbers define the object's revision order; timestamps only
        # determine which revisions existed at the requested instant.
        valid_snapshots.sort(key=lambda item: item.get("version", 0))
        latest_snapshot = valid_snapshots[-1]
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
        boundary = _parse_timestamp(as_of_timestamp, "as_of_timestamp")
        if boundary is None:
            raise ValueError("as_of_timestamp is required")
        for rel in all_relationships:
            created_at = _parse_timestamp(getattr(rel, "created_at", None), "relationship.created_at")
            if created_at is not None and created_at <= boundary:
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
