"""Tests for bounded DataOS catalog summaries."""

from types import SimpleNamespace

import pytest

from engines.catalog.catalog_engine import DataCatalogEngine
from core.object.model import ObjectType


class FakeStorage:
    def __init__(self, objects=None, relationships=None, total_objects=None, total_relationships=None):
        self.objects = list(objects or [])
        self.relationships = list(relationships or [])
        self.total_objects = len(self.objects) if total_objects is None else total_objects
        self.total_relationships = (
            len(self.relationships) if total_relationships is None else total_relationships
        )

    def list_objects(self, limit=100, **kwargs):
        return self.objects[:limit]

    def list_relationships(self, limit=1000, **kwargs):
        return self.relationships[:limit]

    def count_objects(self, object_type=None, **kwargs):
        if object_type == ObjectType.QUALITY_REPORT.value:
            return sum(1 for item in self.objects if item.type == object_type)
        return self.total_objects

    def count_relationships(self, **kwargs):
        return self.total_relationships


def test_summary_returns_exact_totals_and_evidence_based_health_score():
    storage = FakeStorage(
        objects=[
            SimpleNamespace(type="dataset", properties={}),
            SimpleNamespace(
                type=ObjectType.QUALITY_REPORT.value,
                properties={"quality_score": 80},
            ),
        ],
        relationships=[
            SimpleNamespace(relation_type="depends_on", confidence=0.8),
        ],
    )

    summary = DataCatalogEngine(storage).get_catalog_summary()

    assert summary["total_objects"] == 2
    assert summary["sampled_objects"] == 2
    assert summary["total_relationships"] == 1
    assert summary["sampled_relationships"] == 1
    assert summary["object_types"] == {"dataset": 1, ObjectType.QUALITY_REPORT.value: 1}
    assert summary["relationship_types"] == {"depends_on": 1}
    assert summary["average_quality_score"] == 80.0
    assert summary["average_relationship_confidence"] == 0.8
    assert summary["data_health_score"] == 80.0
    assert summary["health_grade"] == "B"
    assert summary["metrics_scope"] == "complete"
    assert summary["is_partial"] is False


def test_summary_marks_metrics_as_sampled_when_catalog_exceeds_limits():
    storage = FakeStorage(
        objects=[SimpleNamespace(type="dataset", properties={})],
        relationships=[SimpleNamespace(relation_type="depends_on", confidence=0.9)],
        total_objects=4,
        total_relationships=7,
    )

    summary = DataCatalogEngine(
        storage,
        max_objects=1,
        max_relationships=1,
    ).get_catalog_summary()

    assert summary["total_objects"] == 4
    assert summary["sampled_objects"] == 1
    assert summary["total_relationships"] == 7
    assert summary["sampled_relationships"] == 1
    assert summary["is_partial"] is True
    assert summary["metrics_scope"] == "sampled"
    assert summary["sample_limits"] == {"objects": 1, "relationships": 1}


def test_summary_does_not_invent_a_perfect_score_without_health_evidence():
    summary = DataCatalogEngine(FakeStorage()).get_catalog_summary()

    assert summary["data_health_score"] is None
    assert summary["health_grade"] == "unrated"
    assert summary["average_quality_score"] is None
    assert summary["average_relationship_confidence"] is None


def test_summary_ignores_non_finite_and_boolean_quality_scores():
    storage = FakeStorage(
        objects=[
            SimpleNamespace(
                type=ObjectType.QUALITY_REPORT.value,
                properties={"quality_score": float("nan")},
            ),
            SimpleNamespace(
                type=ObjectType.QUALITY_REPORT.value,
                properties={"quality_score": True},
            ),
        ],
    )

    summary = DataCatalogEngine(storage).get_catalog_summary()

    assert summary["quality_reports_count"] == 2
    assert summary["quality_reports_sampled"] == 2
    assert summary["quality_scores_used"] == 0
    assert summary["quality_scores_ignored"] == 2
    assert summary["data_health_score"] is None
    assert summary["health_grade"] == "unrated"


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "10"])
def test_summary_rejects_invalid_sample_limits(value):
    with pytest.raises(ValueError):
        DataCatalogEngine(FakeStorage(), max_objects=value)
