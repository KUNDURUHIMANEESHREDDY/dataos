"""
Fuzzy & Semantic Duplicate Detection Engine for DataOS (Rule #58).
Implements:
- Exact content hash matching
- MinHash Jaccard similarity for text and tabular datasets
- Levenshtein edit distance for titles and names
- Explicit duplicate cluster modeling (NEVER silently deletes data; preserves full provenance).
"""

from __future__ import annotations
import hashlib
import re
from typing import Dict, Any, List, Set, Tuple, Optional
from core.object.model import DataObject
from core.relation.model import Relationship, RelationType
from infrastructure.storage.base import StorageBackend

DEFAULT_DUPLICATE_SCAN_LIMIT = 1000


def compute_levenshtein_distance(s1: str, s2: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if s1 == s2:
        return 0
    if not s1:
        return len(s2)
    if not s2:
        return len(s1)

    previous_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def compute_levenshtein_similarity(s1: str, s2: str) -> float:
    """Normalized Levenshtein similarity between 0.0 and 1.0."""
    max_len = max(len(s1), len(s2))
    if max_len == 0:
        return 1.0
    dist = compute_levenshtein_distance(s1.lower(), s2.lower())
    return round(1.0 - (dist / max_len), 4)


def get_k_shingles(text: str, k: int = 3) -> Set[str]:
    """Extract character k-shingles from text."""
    clean = re.sub(r"\s+", " ", text.strip().lower())
    if not clean:
        return set()
    if len(clean) < k:
        return {clean}
    return {clean[i:i + k] for i in range(len(clean) - k + 1)}


def compute_minhash_jaccard(text1: str, text2: str, num_perm: int = 64) -> float:
    """
    Compute MinHash Jaccard similarity estimation between two text documents.
    """
    shingles1 = get_k_shingles(text1)
    shingles2 = get_k_shingles(text2)

    # Empty content carries no evidence of similarity. Treating two empty
    # shingle sets as identical makes unrelated blank documents look like matches.
    if not shingles1 or not shingles2:
        return 0.0

    # Exact Jaccard on shingles
    intersection = len(shingles1.intersection(shingles2))
    union = len(shingles1.union(shingles2))
    return round(intersection / union, 4) if union > 0 else 0.0


class DuplicateDetectionEngine:
    """Scans and detects duplicate and near-duplicate objects in DataOS without data loss."""

    def __init__(self, storage: StorageBackend):
        self.storage = storage

    def find_duplicates(
        self,
        target_object_id: Optional[str] = None,
        min_similarity: float = 0.75,
        auto_link_graph: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Detect duplicates against a target object or across the entire catalog.
        Categorizes matches into:
        - exact_hash (1.0 similarity)
        - near_duplicate_minhash (high Jaccard overlap)
        - title_similar_levenshtein (high string similarity)
        """
        all_objects = self.storage.list_objects(limit=DEFAULT_DUPLICATE_SCAN_LIMIT)
        results: List[Dict[str, Any]] = []

        target_object = self.storage.get_object(target_object_id) if target_object_id else None
        target_pool = [target_object] if target_object_id else all_objects
        target_pool = [obj for obj in target_pool if obj is not None]

        # Resolve each object's hash/content/title once. dict.get(key, obj.compute_hash())
        # evaluates compute_hash even when the key exists, and doing that inside the
        # pairwise loop makes hashing O(n^2) for a catalog scan.
        objects_by_id = {obj.id: obj for obj in all_objects}
        for obj in target_pool:
            objects_by_id[obj.id] = obj

        comparison_data: Dict[str, Dict[str, Any]] = {}
        for object_id, obj in objects_by_id.items():
            metadata = obj.metadata or {}
            properties = obj.properties or {}
            content = str(obj.content)
            content_hash = (
                metadata["content_hash"]
                if "content_hash" in metadata
                else obj.compute_hash()
            )
            comparison_data[object_id] = {
                "content": content,
                "normalized_content": content.strip(),
                "content_hash": content_hash,
                "title": properties.get("title") or properties.get("filename", ""),
                "properties": properties,
            }

        for i, obj_a in enumerate(target_pool):
            search_pool = all_objects[i + 1:] if not target_object_id else all_objects
            data_a = comparison_data[obj_a.id]

            for obj_b in search_pool:
                if obj_a.id == obj_b.id:
                    continue

                data_b = comparison_data[obj_b.id]
                content_a = data_a["normalized_content"]
                content_b = data_b["normalized_content"]
                hash_a = data_a["content_hash"]
                hash_b = data_b["content_hash"]

                is_exact = (hash_a == hash_b) or (bool(content_a) and content_a == content_b)
                method = "exact_hash" if is_exact else None
                sim_score = 1.0 if is_exact else 0.0

                # 2. MinHash Jaccard Check on Content
                if not is_exact:
                    jaccard_sim = compute_minhash_jaccard(data_a["content"], data_b["content"])
                    if jaccard_sim >= min_similarity:
                        sim_score = jaccard_sim
                        method = "minhash_jaccard"

                # 3. Levenshtein Check on Titles / Filenames
                title_a = data_a["title"]
                title_b = data_b["title"]
                if title_a and title_b:
                    lev_sim = compute_levenshtein_similarity(title_a, title_b)
                    if lev_sim > sim_score and lev_sim >= min_similarity:
                        sim_score = lev_sim
                        method = "levenshtein_title"

                if sim_score >= min_similarity:
                    properties_a = data_a["properties"]
                    properties_b = data_b["properties"]
                    duplicate_entry = {
                        "object_a_id": obj_a.id,
                        "object_b_id": obj_b.id,
                        "object_a_name": properties_a.get("filename", properties_a.get("title", obj_a.id[:8])),
                        "object_b_name": properties_b.get("filename", properties_b.get("title", obj_b.id[:8])),
                        "similarity_score": sim_score,
                        "method": method,
                        "is_exact_duplicate": is_exact
                    }
                    results.append(duplicate_entry)

                    # Auto-link candidate duplicates in the graph (Rule #58)
                    if auto_link_graph:
                        self.storage.save_relationship(Relationship(
                            source=obj_a.id,
                            target=obj_b.id,
                            relation_type=RelationType.SIMILAR_TO.value,
                            confidence=sim_score,
                            metadata={"method": method, "is_exact": is_exact}
                        ))

        results.sort(key=lambda x: x["similarity_score"], reverse=True)
        return results

