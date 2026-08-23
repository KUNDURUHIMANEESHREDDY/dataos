"""
Distributed Synchronization & Conflict Engine for DataOS (Rule #29, Rule #59).
Features:
- Vector Clocks for causal ordering across distributed DataOS nodes.
- 3-Way Merge Engine for reconciling concurrent branches.
- Explicit Conflict Modeling: Conflicting concurrent updates produce first-class Conflict objects
  with full resolution strategies, rather than silently overwriting data.
"""

from __future__ import annotations
import uuid
import datetime
from enum import Enum
from typing import Dict, Any, List, Optional, Tuple
from core.object.model import DataObject, ObjectType
from core.relation.model import Relationship, RelationType
from infrastructure.storage.base import StorageBackend


class ClockOrdering(str, Enum):
    EQUAL = "equal"
    BEFORE = "before"
    AFTER = "after"
    CONCURRENT = "concurrent"


class VectorClock:
    """Vector clock representation for distributed causal tracking."""

    def __init__(self, clock_dict: Optional[Dict[str, int]] = None):
        self.clock: Dict[str, int] = dict(clock_dict or {})

    def increment(self, node_id: str) -> VectorClock:
        """Increment sequence counter for the given node."""
        self.clock[node_id] = self.clock.get(node_id, 0) + 1
        return self

    def merge(self, other: VectorClock) -> VectorClock:
        """Merge with another vector clock by taking the element-wise maximum."""
        all_nodes = set(self.clock.keys()).union(other.clock.keys())
        merged = {}
        for n in all_nodes:
            merged[n] = max(self.clock.get(n, 0), other.clock.get(n, 0))
        return VectorClock(merged)

    def compare(self, other: VectorClock) -> ClockOrdering:
        """Determine causal relationship between two vector clocks."""
        all_nodes = set(self.clock.keys()).union(other.clock.keys())
        
        has_greater = False
        has_smaller = False

        for n in all_nodes:
            c1 = self.clock.get(n, 0)
            c2 = other.clock.get(n, 0)
            if c1 > c2:
                has_greater = True
            elif c1 < c2:
                has_smaller = True

        if has_greater and has_smaller:
            return ClockOrdering.CONCURRENT
        elif has_greater and not has_smaller:
            return ClockOrdering.AFTER
        elif not has_greater and has_smaller:
            return ClockOrdering.BEFORE
        else:
            return ClockOrdering.EQUAL

    def to_dict(self) -> Dict[str, int]:
        """Return vector clock as dictionary."""
        return dict(self.clock)

    @classmethod
    def from_dict(cls, data: Dict[str, int]) -> VectorClock:
        """Create vector clock from dictionary."""
        return cls(data)


class ConflictRecord:
    """Explicit representation of a concurrent update conflict on a DataObject."""

    def __init__(
        self,
        object_id: str,
        base_version: int,
        local_version: int,
        incoming_version: int,
        local_properties: Dict[str, Any],
        incoming_properties: Dict[str, Any],
        conflicting_fields: List[str],
        local_clock: Optional[Dict[str, int]] = None,
        incoming_clock: Optional[Dict[str, int]] = None
    ):
        self.conflict_id = str(uuid.uuid4())
        self.object_id = object_id
        self.base_version = base_version
        self.local_version = local_version
        self.incoming_version = incoming_version
        self.local_properties = local_properties
        self.incoming_properties = incoming_properties
        self.conflicting_fields = conflicting_fields
        self.local_clock = local_clock or {}
        self.incoming_clock = incoming_clock or {}
        self.detected_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.resolved = False
        self.resolution_strategy: Optional[str] = None
        self.resolved_properties: Optional[Dict[str, Any]] = None

    def to_object(self) -> DataObject:
        """Convert conflict to DataObject."""
        return DataObject(
            id=f"conflict-{self.conflict_id}",
            type=ObjectType.CUSTOM.value,
            schema="conflict.v1",
            properties={
                "target_object_id": self.object_id,
                "base_version": self.base_version,
                "conflicting_fields": self.conflicting_fields,
                "resolved": self.resolved,
                "resolution_strategy": self.resolution_strategy,
                "detected_at": self.detected_at
            },
            content={
                "local_properties": self.local_properties,
                "incoming_properties": self.incoming_properties,
                "resolved_properties": self.resolved_properties
            },
            source="dataos://sync/conflict"
        )


class DistributedSyncEngine:
    """Reconciles updates between distributed nodes using 3-way merge and explicit conflicts."""

    def __init__(self, storage: StorageBackend, node_id: str = "node_local"):
        self.storage = storage
        self.node_id = node_id

    def three_way_merge(
        self,
        base_obj: DataObject,
        local_obj: DataObject,
        incoming_obj: DataObject,
        local_clock: Optional[VectorClock] = None,
        incoming_clock: Optional[VectorClock] = None
    ) -> Dict[str, Any]:
        """Execute 3-way merge between base, local, and incoming objects."""
        base_props = base_obj.properties
        local_props = local_obj.properties
        incoming_props = incoming_obj.properties

        all_keys = set(base_props.keys()).union(local_props.keys()).union(incoming_props.keys())

        merged_properties: Dict[str, Any] = {}
        conflicting_fields: List[str] = []

        for key in all_keys:
            base_val = base_props.get(key)
            local_val = local_props.get(key)
            incoming_val = incoming_props.get(key)

            if local_val == incoming_val:
                # Both agreed or made identical edit
                merged_properties[key] = local_val
            elif local_val == base_val and incoming_val != base_val:
                # Modified only by incoming
                merged_properties[key] = incoming_val
            elif incoming_val == base_val and local_val != base_val:
                # Modified only by local
                merged_properties[key] = local_val
            else:
                # Concurrent differing modifications -> Conflict!
                conflicting_fields.append(key)
                # Keep local as default unmerged state
                merged_properties[key] = local_val

        # Causal clock comparison
        clock_order = ClockOrdering.CONCURRENT
        merged_clock = None
        if local_clock and incoming_clock:
            clock_order = local_clock.compare(incoming_clock)
            merged_clock = local_clock.merge(incoming_clock).increment(self.node_id)

        if conflicting_fields:
            # Create first-class Conflict record
            conflict = ConflictRecord(
                object_id=base_obj.id,
                base_version=base_obj.version,
                local_version=local_obj.version,
                incoming_version=incoming_obj.version,
                local_properties=local_props,
                incoming_properties=incoming_props,
                conflicting_fields=conflicting_fields,
                local_clock=local_clock.to_dict() if local_clock else {},
                incoming_clock=incoming_clock.to_dict() if incoming_clock else {}
            )
            conflict_obj = conflict.to_object()
            self.storage.save_object(conflict_obj)

            # Link target object -> conflicts_with -> conflict object
            self.storage.save_relationship(Relationship(
                source=local_obj.id,
                target=conflict_obj.id,
                relation_type=RelationType.CONFLICTS_WITH.value,
                confidence=1.0,
                metadata={"conflicting_fields": conflicting_fields}
            ))

            return {
                "status": "conflict_detected",
                "merged": False,
                "conflict_id": conflict.conflict_id,
                "conflict_object_id": conflict_obj.id,
                "conflicting_fields": conflicting_fields,
                "unresolved_properties": merged_properties,
                "clock_ordering": clock_order.value
            }
        else:
            # Clean merge! Create new version
            new_version = local_obj.create_new_version(
                new_properties=merged_properties,
                new_content=incoming_obj.content if incoming_obj.content != base_obj.content else local_obj.content,
                transformation_desc=f"3-Way sync merge with node {incoming_clock.to_dict() if incoming_clock else 'remote'}"
            )
            self.storage.save_object(new_version)

            return {
                "status": "clean_merge",
                "merged": True,
                "merged_object": new_version.to_dict(),
                "merged_version": new_version.version,
                "merged_clock": merged_clock.to_dict() if merged_clock else {},
                "clock_ordering": clock_order.value
            }

    def resolve_conflict(
        self,
        conflict_object_id: str,
        strategy: str = "last_write_wins",
        manual_properties: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Resolve a conflict using the specified strategy."""
        conflict_obj = self.storage.get_object(conflict_object_id)
        if not conflict_obj or conflict_obj.schema != "conflict.v1":
            raise ValueError(f"Invalid conflict object: {conflict_object_id}")

        target_obj_id = conflict_obj.properties["target_object_id"]
        target_obj = self.storage.get_object(target_obj_id)
        if not target_obj:
            raise ValueError(f"Target object not found: {target_obj_id}")

        local_props = conflict_obj.content["local_properties"]
        incoming_props = conflict_obj.content["incoming_properties"]

        resolved_props = {}
        if strategy == "last_write_wins":
            resolved_props = {**local_props, **incoming_props}
        elif strategy == "source_priority":
            resolved_props = {**incoming_props, **local_props}
        elif strategy == "manual_merge":
            if not manual_properties:
                raise ValueError("manual_properties must be provided for manual_merge strategy")
            resolved_props = manual_properties
        else:
            raise ValueError(f"Unsupported resolution strategy: {strategy}")

        # Update target object to new resolved version
        resolved_version = target_obj.create_new_version(
            new_properties=resolved_props,
            transformation_desc=f"Resolved conflict {conflict_object_id} using strategy '{strategy}'"
        )
        self.storage.save_object(resolved_version)

        # Update conflict object
        conflict_obj.properties["resolved"] = True
        conflict_obj.properties["resolution_strategy"] = strategy
        conflict_obj.content["resolved_properties"] = resolved_props
        self.storage.save_object(conflict_obj)

        return {
            "status": "resolved",
            "conflict_id": conflict_object_id,
            "strategy": strategy,
            "resolved_object_id": resolved_version.id,
            "resolved_version": resolved_version.version,
            "properties": resolved_props
        }
