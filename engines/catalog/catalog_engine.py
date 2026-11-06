"""
Bounded catalog inventory and data-health summary for DataOS.
"""

from __future__ import annotations

import datetime
import math
from typing import Any, Dict, List, Optional

from core.object.model import ObjectType
from infrastructure.storage.base import StorageBackend


DEFAULT_CATALOG_OBJECT_SAMPLE_LIMIT = 10_000
DEFAULT_CATALOG_RELATIONSHIP_SAMPLE_LIMIT = 50_000


class DataCatalogEngine:
    """Maintains bounded asset inventory, usage statistics, and health summaries."""

    def __init__(
        self,
        storage: StorageBackend,
        max_objects: int = DEFAULT_CATALOG_OBJECT_SAMPLE_LIMIT,
        max_relationships: int = DEFAULT_CATALOG_RELATIONSHIP_SAMPLE_LIMIT,
    ):
        for name, value in (
            ("max_objects", max_objects),
            ("max_relationships", max_relationships),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        self.storage = storage
        self.max_objects = max_objects
        self.max_relationships = max_relationships

    def get_catalog_summary(self) -> Dict[str, Any]:
        """Return exact totals plus metrics calculated from explicitly bounded samples."""
        objects = self.storage.list_objects(limit=self.max_objects)
        relationships = self.storage.list_relationships(limit=self.max_relationships)

        total_objects = self.storage.count_objects()
        total_relationships = self.storage.count_relationships()
        quality_reports_count = self.storage.count_objects(
            object_type=ObjectType.QUALITY_REPORT.value
        )

        object_types: Dict[str, int] = {}
        for obj in objects:
            object_type = str(obj.type)
            object_types[object_type] = object_types.get(object_type, 0) + 1

        relationship_types: Dict[str, int] = {}
        for relationship in relationships:
            relation_type = str(relationship.relation_type)
            relationship_types[relation_type] = relationship_types.get(relation_type, 0) + 1

        quality_reports = [
            obj for obj in objects if obj.type == ObjectType.QUALITY_REPORT.value
        ]
        quality_scores: List[float] = []
        for report in quality_reports:
            properties = report.properties if isinstance(report.properties, dict) else {}
            score = properties.get("quality_score")
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                continue
            if not math.isfinite(float(score)):
                continue
            quality_scores.append(max(0.0, min(100.0, float(score))))

        confidences: List[float] = []
        for relationship in relationships:
            confidence = relationship.confidence
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
                continue
            if math.isfinite(float(confidence)):
                confidences.append(max(0.0, min(1.0, float(confidence))))

        average_quality = (
            sum(quality_scores) / len(quality_scores) if quality_scores else None
        )
        average_confidence = (
            sum(confidences) / len(confidences) if confidences else None
        )

        # Missing quality or relationship evidence is unknown, not a perfect score.
        score_components = []
        if average_quality is not None:
            score_components.append((average_quality, 0.6))
        if average_confidence is not None:
            score_components.append((average_confidence * 100.0, 0.4))

        if score_components:
            weight_total = sum(weight for _, weight in score_components)
            composite = sum(value * weight for value, weight in score_components) / weight_total
            health_score: Optional[float] = round(max(0.0, min(100.0, composite)), 1)
            health_grade = "A" if health_score >= 90 else ("B" if health_score >= 75 else "C")
        else:
            health_score = None
            health_grade = "unrated"

        is_partial = (
            total_objects > len(objects)
            or total_relationships > len(relationships)
        )

        return {
            "total_objects": total_objects,
            "sampled_objects": len(objects),
            "total_relationships": total_relationships,
            "sampled_relationships": len(relationships),
            "object_types": object_types,
            "relationship_types": relationship_types,
            "data_health_score": health_score,
            "health_grade": health_grade,
            "quality_reports_count": quality_reports_count,
            "quality_reports_sampled": len(quality_reports),
            "quality_scores_used": len(quality_scores),
            "quality_scores_ignored": len(quality_reports) - len(quality_scores),
            "average_quality_score": (
                round(average_quality, 2) if average_quality is not None else None
            ),
            "average_relationship_confidence": (
                round(average_confidence, 4) if average_confidence is not None else None
            ),
            "is_partial": is_partial,
            "metrics_scope": "sampled" if is_partial else "complete",
            "sample_limits": {
                "objects": self.max_objects,
                "relationships": self.max_relationships,
            },
            "catalog_refreshed_at": datetime.datetime.now(
                datetime.timezone.utc
            ).isoformat(),
        }
