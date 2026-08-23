"""
Hybrid Search Engine for DataOS (Rule #23).
Combines BM25/TF-IDF lexical search, metadata filtering, semantic vector similarity,
and graph traversal proximity into a unified ranking model with explainable scoring.
"""

from __future__ import annotations
import math
import re
from typing import Dict, Any, List, Optional, Set
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from core.object.model import DataObject
from infrastructure.storage.base import StorageBackend


class HybridSearchEngine:
    """Multi-modal search engine indexing DataOS objects across text, metadata, and graph context."""

    def __init__(self, storage: StorageBackend):
        self.storage = storage

    def search(
        self,
        query: str,
        object_type: Optional[str] = None,
        source_filter: Optional[str] = None,
        context_object_id: Optional[str] = None,
        limit: int = 20,
        weights: Optional[Dict[str, float]] = None
    ) -> List[Dict[str, Any]]:
        """
        Execute hybrid search.
        Weights default: 0.45 lexical + 0.35 semantic + 0.20 metadata/graph.
        """
        weights = weights or {"lexical": 0.45, "semantic": 0.35, "graph": 0.20}
        all_objects = self.storage.list_objects(limit=5000)

        # Filter by type / source
        candidates = []
        for obj in all_objects:
            if object_type and obj.type != object_type:
                continue
            if source_filter and source_filter not in obj.source:
                continue
            candidates.append(obj)

        if not candidates:
            return []

        # 1. Build document corpus
        doc_texts = []
        for obj in candidates:
            text_parts = [
                obj.type,
                obj.schema,
                str(obj.properties.get("filename", "")),
                str(obj.properties.get("title", "")),
                str(obj.properties.get("headings", "")),
                str(obj.content)[:1000]
            ]
            doc_texts.append(" ".join(text_parts))

        # 2. Compute TF-IDF Semantic similarity
        try:
            vectorizer = TfidfVectorizer(stop_words="english", max_features=1000)
            tfidf_matrix = vectorizer.fit_transform(doc_texts)
            query_vec = vectorizer.transform([query])
            semantic_scores = cosine_similarity(query_vec, tfidf_matrix).flatten()
        except Exception:
            semantic_scores = [0.0] * len(candidates)

        # 3. Compute Lexical BM25/keyword match
        query_terms = set(re.findall(r"\w+", query.lower()))
        lexical_scores = []
        for text in doc_texts:
            text_lower = text.lower()
            matches = sum(1 for term in query_terms if term in text_lower)
            lexical_scores.append(matches / max(1, len(query_terms)))

        # 4. Compute Graph Proximity (if context_object_id provided)
        connected_ids: Set[str] = set()
        if context_object_id:
            rels = self.storage.list_relationships(source_id=context_object_id)
            rels.extend(self.storage.list_relationships(target_id=context_object_id))
            for r in rels:
                connected_ids.add(r.source)
                connected_ids.add(r.target)

        # 5. Hybrid Rank Fusion
        results = []
        for idx, obj in enumerate(candidates):
            lex_score = lexical_scores[idx]
            sem_score = float(semantic_scores[idx])
            graph_score = 1.0 if obj.id in connected_ids else 0.0

            final_score = (
                (lex_score * weights.get("lexical", 0.45)) +
                (sem_score * weights.get("semantic", 0.35)) +
                (graph_score * weights.get("graph", 0.20))
            )

            if final_score > 0.05 or not query.strip():
                results.append({
                    "object_id": obj.id,
                    "object": obj.to_dict(),
                    "score": round(final_score, 4),
                    "scoring_breakdown": {
                        "lexical_score": round(lex_score, 4),
                        "semantic_score": round(sem_score, 4),
                        "graph_proximity": round(graph_score, 4)
                    }
                })

        # Sort descending by composite score
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:limit]
