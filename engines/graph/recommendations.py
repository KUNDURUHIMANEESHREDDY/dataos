"""
Graph Recommendation & Missing Edge Discovery Engine for DataOS (Rule #57).
Suggests related objects, missing connections, and relevant datasets with
confidence scores and explainable evidence paths.
"""

from __future__ import annotations
import math
from typing import Dict, Any, List, Optional, Set, Tuple
from core.object.model import DataObject
from core.relation.model import Relationship, RelationType
from infrastructure.storage.base import StorageBackend
from .engine import GraphEngine


class GraphRecommendationEngine:
    """Computes explainable graph link predictions, dataset recommendations, and missing edges."""

    def __init__(self, storage: StorageBackend):
        self.storage = storage
        self.graph_engine = GraphEngine(storage)

    def recommend_connections(
        self,
        target_object_id: str,
        top_k: int = 10,
        min_confidence: float = 0.2
    ) -> List[Dict[str, Any]]:
        """
        Suggest missing relationship edges for `target_object_id` with explainable evidence:
        1. Common Neighbors (Jaccard similarity on graph neighborhood)
        2. Bibliographic Coupling (Objects that cite/read the same upstream sources)
        3. Co-Occurrence (Objects that appear in the same collections/documents)
        """
        target_obj = self.storage.get_object(target_object_id)
        if not target_obj:
            return []

        all_objects = self.storage.list_objects(limit=1000)
        existing_neighbors = {n["neighbor_id"] for n in self.graph_engine.get_neighbors(target_object_id)}
        existing_neighbors.add(target_object_id)  # Exclude self

        target_outgoing = {r.target for r in self.storage.list_relationships(source_id=target_object_id)}
        target_incoming = {r.source for r in self.storage.list_relationships(target_id=target_object_id)}
        target_all_links = target_outgoing.union(target_incoming)

        recommendations: List[Dict[str, Any]] = []

        for candidate in all_objects:
            if candidate.id in existing_neighbors:
                continue

            cand_outgoing = {r.target for r in self.storage.list_relationships(source_id=candidate.id)}
            cand_incoming = {r.source for r in self.storage.list_relationships(target_id=candidate.id)}
            cand_all_links = cand_outgoing.union(cand_incoming)

            evidence_paths: List[str] = []
            score = 0.0

            # Signal 1: Common Neighbors / Structural Co-occurrence
            common_neighbors = target_all_links.intersection(cand_all_links)
            if common_neighbors:
                jaccard = len(common_neighbors) / len(target_all_links.union(cand_all_links))
                score += jaccard * 0.5
                neighbor_names = []
                for n_id in list(common_neighbors)[:3]:
                    n_obj = self.storage.get_object(n_id)
                    neighbor_names.append(n_obj.properties.get("filename", n_id[:8]) if n_obj else n_id[:8])
                evidence_paths.append(f"Shares {len(common_neighbors)} common neighbor(s): [{', '.join(neighbor_names)}]")

            # Signal 2: Bibliographic Coupling (Both cite/read same upstream datasets/papers)
            common_upstream = target_outgoing.intersection(cand_outgoing)
            if common_upstream:
                score += 0.35
                evidence_paths.append(f"Both depend on/cite the same upstream source(s) ({len(common_upstream)} shared)")

            # Signal 3: Schema / Type compatibility
            if target_obj.type == "code" and candidate.type == "dataset":
                # Check if code reads dataset filename in content
                fn = candidate.properties.get("filename", "")
                if fn and fn in str(target_obj.content):
                    score += 0.4
                    evidence_paths.append(f"Code directly references dataset file '{fn}'")

            elif target_obj.type == "document" and candidate.type == "dataset":
                fn = candidate.properties.get("filename", "")
                if fn and fn in str(target_obj.content):
                    score += 0.35
                    evidence_paths.append(f"Document mentions dataset '{fn}'")

            confidence = min(1.0, round(score, 3))
            if confidence >= min_confidence:
                recommendations.append({
                    "target_object_id": target_object_id,
                    "candidate_object_id": candidate.id,
                    "candidate_name": candidate.properties.get("filename", candidate.properties.get("title", candidate.id[:8])),
                    "candidate_type": candidate.type,
                    "suggested_relation_type": RelationType.SIMILAR_TO.value if candidate.type == target_obj.type else RelationType.REFERENCES.value,
                    "confidence": confidence,
                    "evidence_paths": evidence_paths
                })

        recommendations.sort(key=lambda x: x["confidence"], reverse=True)
        return recommendations[:top_k]

    def recommend_relevant_datasets(self, target_object_id: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Find relevant tabular datasets for an analysis or document."""
        recs = self.recommend_connections(target_object_id, top_k=20, min_confidence=0.1)
        dataset_recs = [r for r in recs if r["candidate_type"] in ("dataset", "table")]
        return dataset_recs[:top_k]
