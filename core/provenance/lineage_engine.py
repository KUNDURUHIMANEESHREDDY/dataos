"""
Data Lineage & Provenance Traversal Engine (Rule #6, Rule #7).
Performs upstream root-cause traversal ("Where did this result originate?")
and downstream impact analysis ("What artifacts depend on this object?").
Generates OpenLineage-compliant lineage graphs.
"""

from __future__ import annotations
import collections
import datetime
from typing import Dict, Any, List, Optional, Set
from infrastructure.storage.base import StorageBackend
from core.relation.types import RelationType


class LineageEngine:
    """Traverses data provenance and OpenLineage lineage across layers."""

    def __init__(self, storage: StorageBackend):
        self.storage = storage

    def trace_upstream_lineage(self, object_id: str, max_depth: int = 10) -> Dict[str, Any]:
        """
        Answers: 'Where did this result originate? What inputs contributed to it?'
        Follows 'derived_from', 'reads_from', 'cites', 'transforms_to' edges in reverse.
        """
        visited: Set[str] = {object_id}
        queue = collections.deque([(object_id, 0)])
        lineage_tree: List[Dict[str, Any]] = []
        root_inputs: List[Dict[str, Any]] = []

        while queue:
            curr_id, depth = queue.popleft()
            if depth >= max_depth:
                continue

            # All derivation relation types that signal parent → child or child ← parent relationships
            DERIVATION_TYPES = {
                RelationType.DERIVED_FROM.value,
                RelationType.TRANSFORMS_TO.value,
                RelationType.READS_FROM.value,
                RelationType.PRODUCES.value
            }

            # Direction 1: Incoming edges (predecessor → curr_id)
            # e.g. "raw TRANSFORMS_TO clean" means raw is an ancestor of clean
            incoming_rels = self.storage.list_relationships(target_id=curr_id)
            parent_ids_from_incoming = [
                r.source for r in incoming_rels
                if r.relation_type in DERIVATION_TYPES
            ]

            # Direction 2: Outgoing DERIVED_FROM / READS_FROM where curr_id explicitly points to its sources
            # e.g. "report DERIVED_FROM orders" means orders is an ancestor of report
            outgoing_rels = self.storage.list_relationships(source_id=curr_id)
            parent_ids_from_outgoing = [
                r.target for r in outgoing_rels
                if r.relation_type == RelationType.DERIVED_FROM.value
            ]

            all_parent_ids = list(dict.fromkeys(parent_ids_from_incoming + parent_ids_from_outgoing))

            curr_obj = self.storage.get_object(curr_id)
            node_info = {
                "object_id": curr_id,
                "type": curr_obj.type if curr_obj else "unknown",
                "depth": depth,
                "source": curr_obj.source if curr_obj else "unknown",
                "parent_count": len(all_parent_ids)
            }
            lineage_tree.append(node_info)

            if not all_parent_ids and depth > 0:
                root_inputs.append(node_info)

            for parent_id in all_parent_ids:
                if parent_id not in visited:
                    visited.add(parent_id)
                    queue.append((parent_id, depth + 1))

        return {
            "target_object_id": object_id,
            "max_depth": max_depth,
            "total_ancestors": len(lineage_tree) - 1,
            "lineage_nodes": lineage_tree,
            "root_sources": root_inputs,
            "traced_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }

    def trace_downstream_impact(self, object_id: str, max_depth: int = 10) -> Dict[str, Any]:
        """
        Answers: 'What downstream artifacts depend on this object?'
        Follows outgoing derivation relationships (Source -> Target where Source is curr_id).
        """
        visited: Set[str] = {object_id}
        queue = collections.deque([(object_id, 0)])
        impacted_nodes: List[Dict[str, Any]] = []

        while queue:
            curr_id, depth = queue.popleft()
            if depth >= max_depth:
                continue

            rels = self.storage.list_relationships(source_id=curr_id)
            derivation_rels = [
                r for r in rels
                if r.relation_type in (
                    RelationType.DERIVED_FROM.value,
                    RelationType.TRANSFORMS_TO.value,
                    RelationType.READS_FROM.value,
                    RelationType.PRODUCES.value,
                    RelationType.DEPENDS_ON.value
                )
            ]

            for rel in derivation_rels:
                child_id = rel.target
                if child_id not in visited:
                    visited.add(child_id)
                    child_obj = self.storage.get_object(child_id)
                    impacted_nodes.append({
                        "object_id": child_id,
                        "type": child_obj.type if child_obj else "unknown",
                        "depth": depth + 1,
                        "relation_type": rel.relation_type,
                        "source": child_obj.source if child_obj else "unknown"
                    })
                    queue.append((child_id, depth + 1))

        return {
            "root_object_id": object_id,
            "total_downstream_dependents": len(impacted_nodes),
            "impacted_nodes": impacted_nodes,
            "analyzed_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
