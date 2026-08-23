"""
Data Catalog & System Health Engine for DataOS (Rule #37, Rule #40).
Indexes assets, evaluates freshness, quality pass ratios, and overall health scores.
"""

from __future__ import annotations
import datetime
from typing import Dict, Any, List, Optional
from core.object.model import DataObject, ObjectType
from infrastructure.storage.base import StorageBackend


class DataCatalogEngine:
    """Maintains automated asset inventory, usage statistics, and data health scores."""

    def __init__(self, storage: StorageBackend):
        self.storage = storage

    def get_catalog_summary(self) -> Dict[str, Any]:
        """Aggregate catalog metrics across all DataOS assets."""
        objects = self.storage.list_objects(limit=10000)
        relationships = self.storage.list_relationships(limit=50000)

        type_counts: Dict[str, int] = {}
        for obj in objects:
            type_counts[obj.type] = type_counts.get(obj.type, 0) + 1

        rel_type_counts: Dict[str, int] = {}
        for rel in relationships:
            rel_type_counts[rel.relation_type] = rel_type_counts.get(rel.relation_type, 0) + 1

        # Calculate data health score (0-100%)
        # Based on: non-empty objects, average relationship confidence, quality check scores
        quality_reports = [obj for obj in objects if obj.type == ObjectType.QUALITY_REPORT.value]
        avg_quality = 100.0
        if quality_reports:
            scores = [r.properties.get("quality_score", 100.0) for r in quality_reports]
            avg_quality = sum(scores) / len(scores)

        avg_confidence = 1.0
        if relationships:
            avg_confidence = sum(r.confidence for r in relationships) / len(relationships)

        composite_health_score = round((avg_quality * 0.6) + (avg_confidence * 100.0 * 0.4), 1)

        return {
            "total_objects": len(objects),
            "total_relationships": len(relationships),
            "object_types": type_counts,
            "relationship_types": rel_type_counts,
            "data_health_score": min(100.0, composite_health_score),
            "health_grade": "A" if composite_health_score >= 90 else ("B" if composite_health_score >= 75 else "C"),
            "quality_reports_count": len(quality_reports),
            "average_quality_score": round(avg_quality, 2),
            "average_relationship_confidence": round(avg_confidence, 4),
            "catalog_refreshed_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
