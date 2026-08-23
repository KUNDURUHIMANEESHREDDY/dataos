"""
Universal Graph Engine for DataOS (Rule #4, Rule #24).
Provides graph querying, multi-hop traversal, neighborhood exploration,
and dependency path analysis directly over persistent storage.
"""

from __future__ import annotations
import collections
from typing import Dict, Any, List, Optional, Set, Tuple
from core.object.model import DataObject
from core.relation.model import Relationship, RelationType
from infrastructure.storage.base import StorageBackend


class GraphEngine:
    """
    Graph Engine over persistent StorageBackend.
    The database is the authoritative graph store.
    """

    def __init__(self, storage: StorageBackend):
        self.storage = storage

    def create_relation(
        self,
        source_id: str,
        target_id: str,
        relation_type: str,
        metadata: Optional[Dict[str, Any]] = None,
        confidence: float = 1.0,
        provenance: Optional[Dict[str, Any]] = None,
        evidence: Optional[List[Dict[str, Any]]] = None
    ) -> Relationship:
        """Create and persist a first-class relationship."""
        rel = Relationship(
            source=source_id,
            target=target_id,
            relation_type=relation_type,
            metadata=metadata or {},
            confidence=confidence,
            provenance=provenance or {},
            evidence=evidence or []
        )
        return self.storage.save_relationship(rel)

    def get_neighbors(
        self,
        object_id: str,
        direction: str = "both",  # "outgoing", "incoming", "both"
        relation_types: Optional[List[str]] = None,
        min_confidence: float = 0.0
    ) -> List[Dict[str, Any]]:
        """
        Get all neighboring objects and the connecting relationships.
        Returns: list of {neighbor_id, neighbor_object, relationship, direction}
        """
        neighbors = []
        
        # Outgoing
        if direction in ("outgoing", "both"):
            out_rels = self.storage.list_relationships(source_id=object_id, min_confidence=min_confidence)
            for rel in out_rels:
                if relation_types and rel.relation_type not in relation_types:
                    continue
                target_obj = self.storage.get_object(rel.target)
                neighbors.append({
                    "neighbor_id": rel.target,
                    "neighbor_object": target_obj.to_dict() if target_obj else None,
                    "relationship": rel.to_dict(),
                    "direction": "outgoing"
                })

        # Incoming
        if direction in ("incoming", "both"):
            in_rels = self.storage.list_relationships(target_id=object_id, min_confidence=min_confidence)
            for rel in in_rels:
                if relation_types and rel.relation_type not in relation_types:
                    continue
                src_obj = self.storage.get_object(rel.source)
                neighbors.append({
                    "neighbor_id": rel.source,
                    "neighbor_object": src_obj.to_dict() if src_obj else None,
                    "relationship": rel.to_dict(),
                    "direction": "incoming"
                })

        return neighbors

    def traverse(
        self,
        start_id: str,
        max_hops: int = 3,
        direction: str = "outgoing",
        relation_types: Optional[List[str]] = None,
        min_confidence: float = 0.0
    ) -> Dict[str, Any]:
        """
        Multi-hop BFS graph traversal from a root object.
        Returns reachable nodes, edges, paths, and depth levels.
        """
        visited_nodes: Set[str] = {start_id}
        queue = collections.deque([(start_id, 0, [start_id])])  # (current_node, depth, path)
        
        traversed_nodes: Dict[str, Dict[str, Any]] = {}
        traversed_edges: List[Dict[str, Any]] = []
        paths_found: List[Dict[str, Any]] = []

        start_obj = self.storage.get_object(start_id)
        if start_obj:
            traversed_nodes[start_id] = {
                "id": start_id,
                "depth": 0,
                "type": start_obj.type,
                "schema": start_obj.schema,
                "source": start_obj.source
            }

        while queue:
            curr_id, depth, path = queue.popleft()
            
            if depth >= max_hops:
                continue

            # Query neighbors from persistent storage
            neighbors = self.get_neighbors(
                object_id=curr_id,
                direction=direction,
                relation_types=relation_types,
                min_confidence=min_confidence
            )

            for neighbor in neighbors:
                nbr_id = neighbor["neighbor_id"]
                rel_dict = neighbor["relationship"]
                traversed_edges.append(rel_dict)

                new_path = path + [nbr_id]
                paths_found.append({
                    "path": new_path,
                    "length": len(new_path) - 1,
                    "confidence": rel_dict.get("confidence", 1.0)
                })

                if nbr_id not in visited_nodes:
                    visited_nodes.add(nbr_id)
                    nbr_obj = self.storage.get_object(nbr_id)
                    traversed_nodes[nbr_id] = {
                        "id": nbr_id,
                        "depth": depth + 1,
                        "type": nbr_obj.type if nbr_obj else "unknown",
                        "schema": nbr_obj.schema if nbr_obj else "unknown",
                        "source": nbr_obj.source if nbr_obj else "unknown"
                    }
                    queue.append((nbr_id, depth + 1, new_path))

        return {
            "root_id": start_id,
            "max_hops": max_hops,
            "total_nodes_reached": len(traversed_nodes),
            "total_edges_traversed": len(traversed_edges),
            "nodes": list(traversed_nodes.values()),
            "edges": traversed_edges,
            "paths": paths_found
        }

    def find_paths(
        self,
        source_id: str,
        target_id: str,
        max_depth: int = 5,
        min_confidence: float = 0.0
    ) -> List[List[str]]:
        """Find all directed simple paths between source_id and target_id up to max_depth."""
        if source_id == target_id:
            return [[source_id]]

        paths: List[List[str]] = []
        queue = collections.deque([(source_id, [source_id])])

        while queue:
            curr_id, path = queue.popleft()
            if len(path) > max_depth + 1:
                continue

            rels = self.storage.list_relationships(source_id=curr_id, min_confidence=min_confidence)
            for r in rels:
                nxt = r.target
                if nxt == target_id:
                    paths.append(path + [nxt])
                elif nxt not in path and len(path) <= max_depth:
                    queue.append((nxt, path + [nxt]))

        return paths

    def get_subgraph(self, object_ids: List[str]) -> Dict[str, Any]:
        """Extract exact subgraph for a subset of object IDs."""
        id_set = set(object_ids)
        nodes = []
        for obj_id in id_set:
            obj = self.storage.get_object(obj_id)
            if obj:
                nodes.append(obj.to_dict())

        edges = []
        for obj_id in id_set:
            rels = self.storage.list_relationships(source_id=obj_id)
            for r in rels:
                if r.target in id_set:
                    edges.append(r.to_dict())

        return {
            "nodes": nodes,
            "edges": edges,
            "node_count": len(nodes),
            "edge_count": len(edges)
        }
