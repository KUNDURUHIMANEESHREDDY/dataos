"""
Data Lineage & Provenance Traversal Engine (Rule #6, Rule #7).
Performs upstream root-cause traversal ("Where did this result originate?")
and downstream impact analysis ("What artifacts depend on this object?").
Generates OpenLineage-compliant lineage graphs.
"""

from __future__ import annotations

import collections
import datetime
from typing import Any, Dict, List, Set

from infrastructure.storage.base import StorageBackend
from core.relation.types import RelationType


class LineageEngine:
    """Traverses data provenance with explicit global work budgets."""

    DEFAULT_MAX_NODES = 1_000
    DEFAULT_MAX_RELATIONSHIPS = 10_000
    MAX_ALLOWED_NODES = 5_000
    MAX_ALLOWED_RELATIONSHIPS = 50_000
    MAX_DEPTH = 32

    def __init__(self, storage: StorageBackend):
        self.storage = storage

    @classmethod
    def _validate_limits(
        cls,
        max_depth: int,
        max_nodes: int,
        max_relationships: int,
    ) -> None:
        limits = (
            ("max_depth", max_depth, cls.MAX_DEPTH),
            ("max_nodes", max_nodes, cls.MAX_ALLOWED_NODES),
            ("max_relationships", max_relationships, cls.MAX_ALLOWED_RELATIONSHIPS),
        )
        for name, value, upper_bound in limits:
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= upper_bound:
                raise ValueError(f"{name} must be between 1 and {upper_bound}")

    def _read_relationships(
        self,
        remaining_budget: int,
        **filters: Any,
    ) -> tuple[List[Any], int, bool]:
        """Read at most the remaining global budget plus one sentinel row.

        The sentinel distinguishes an exactly exhausted result set from a
        truncated one. The storage query itself is bounded even for a
        high-fan-out object.
        """
        request_limit = remaining_budget + 1
        rows = self.storage.list_relationships(limit=request_limit, **filters)
        accepted = rows[:remaining_budget]
        return accepted, len(accepted), len(rows) > len(accepted)

    def trace_upstream_lineage(
        self,
        object_id: str,
        max_depth: int = 10,
        max_nodes: int = DEFAULT_MAX_NODES,
        max_relationships: int = DEFAULT_MAX_RELATIONSHIPS,
    ) -> Dict[str, Any]:
        """
        Trace ancestors while enforcing global node and relationship budgets.

        max_nodes includes the starting object. max_relationships counts
        relationship rows read across both incoming and outgoing lookups.
        A partial result is explicitly marked with truncated=true.
        """
        self._validate_limits(max_depth, max_nodes, max_relationships)

        visited: Set[str] = {object_id}
        queue = collections.deque([(object_id, 0)])
        lineage_tree: List[Dict[str, Any]] = []
        root_inputs: List[Dict[str, Any]] = []
        relationships_scanned = 0
        truncated = False
        truncation_reason = None

        derivation_types = {
            RelationType.DERIVED_FROM.value,
            RelationType.TRANSFORMS_TO.value,
            RelationType.READS_FROM.value,
            RelationType.PRODUCES.value,
        }

        while queue:
            curr_id, depth = queue.popleft()
            if depth >= max_depth:
                continue

            incoming_rels, consumed, incoming_truncated = self._read_relationships(
                max_relationships - relationships_scanned,
                target_id=curr_id,
            )
            relationships_scanned += consumed
            parent_ids_from_incoming = [
                rel.source for rel in incoming_rels
                if rel.relation_type in derivation_types
            ]

            outgoing_rels: List[Any] = []
            outgoing_truncated = False
            if not incoming_truncated:
                outgoing_rels, consumed, outgoing_truncated = self._read_relationships(
                    max_relationships - relationships_scanned,
                    source_id=curr_id,
                )
                relationships_scanned += consumed

            parent_ids_from_outgoing = [
                rel.target for rel in outgoing_rels
                if rel.relation_type == RelationType.DERIVED_FROM.value
            ]
            all_parent_ids = list(dict.fromkeys(
                parent_ids_from_incoming + parent_ids_from_outgoing
            ))

            curr_obj = self.storage.get_object(curr_id)
            node_info = {
                "object_id": curr_id,
                "type": curr_obj.type if curr_obj else "unknown",
                "depth": depth,
                "source": curr_obj.source if curr_obj else "unknown",
                "parent_count": len(all_parent_ids),
            }
            lineage_tree.append(node_info)

            if not all_parent_ids and depth > 0:
                root_inputs.append(node_info)

            for parent_id in all_parent_ids:
                if parent_id in visited:
                    continue
                if len(visited) >= max_nodes:
                    truncated = True
                    truncation_reason = "max_nodes"
                    break
                visited.add(parent_id)
                queue.append((parent_id, depth + 1))

            if incoming_truncated or outgoing_truncated:
                truncated = True
                truncation_reason = truncation_reason or "max_relationships"
            if truncated:
                break

        return {
            "target_object_id": object_id,
            "max_depth": max_depth,
            "total_ancestors": len(lineage_tree) - 1,
            "lineage_nodes": lineage_tree,
            "root_sources": root_inputs,
            "max_nodes": max_nodes,
            "max_relationships": max_relationships,
            "relationships_scanned": relationships_scanned,
            "truncated": truncated,
            "truncation_reason": truncation_reason,
            "traced_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

    def trace_downstream_impact(
        self,
        object_id: str,
        max_depth: int = 10,
        max_nodes: int = DEFAULT_MAX_NODES,
        max_relationships: int = DEFAULT_MAX_RELATIONSHIPS,
    ) -> Dict[str, Any]:
        """
        Trace downstream dependents with global node and relationship budgets.

        max_nodes includes the starting object. max_relationships counts
        relationship rows read across the complete traversal. A partial result
        is explicitly marked with truncated=true.
        """
        self._validate_limits(max_depth, max_nodes, max_relationships)

        visited: Set[str] = {object_id}
        queue = collections.deque([(object_id, 0)])
        impacted_nodes: List[Dict[str, Any]] = []
        relationships_scanned = 0
        truncated = False
        truncation_reason = None

        derivation_types = {
            RelationType.DERIVED_FROM.value,
            RelationType.TRANSFORMS_TO.value,
            RelationType.READS_FROM.value,
            RelationType.PRODUCES.value,
            RelationType.DEPENDS_ON.value,
        }

        while queue:
            curr_id, depth = queue.popleft()
            if depth >= max_depth:
                continue

            rels, consumed, relationship_truncated = self._read_relationships(
                max_relationships - relationships_scanned,
                source_id=curr_id,
            )
            relationships_scanned += consumed

            for rel in rels:
                if rel.relation_type not in derivation_types:
                    continue
                child_id = rel.target
                if child_id in visited:
                    continue
                if len(visited) >= max_nodes:
                    truncated = True
                    truncation_reason = "max_nodes"
                    break

                visited.add(child_id)
                child_obj = self.storage.get_object(child_id)
                impacted_nodes.append({
                    "object_id": child_id,
                    "type": child_obj.type if child_obj else "unknown",
                    "depth": depth + 1,
                    "relation_type": rel.relation_type,
                    "source": child_obj.source if child_obj else "unknown",
                })
                queue.append((child_id, depth + 1))

            if relationship_truncated:
                truncated = True
                truncation_reason = truncation_reason or "max_relationships"
            if truncated:
                break

        return {
            "root_object_id": object_id,
            "max_depth": max_depth,
            "total_downstream_dependents": len(impacted_nodes),
            "impacted_nodes": impacted_nodes,
            "max_nodes": max_nodes,
            "max_relationships": max_relationships,
            "relationships_scanned": relationships_scanned,
            "truncated": truncated,
            "truncation_reason": truncation_reason,
            "analyzed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
