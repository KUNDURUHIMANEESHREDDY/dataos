"""Regression tests for object-list pagination metadata."""

import asyncio
import importlib

from core.object.model import DataObject
from core.relation.model import Relationship
from infrastructure.storage.sqlite_store import SQLiteStorage


def test_object_list_total_counts_all_filtered_rows(monkeypatch, tmp_path):
    api = importlib.import_module("backend.app")
    store = SQLiteStorage(str(tmp_path / "pagination.sqlite"))
    monkeypatch.setattr(api.dataos, "storage", store)
    try:
        store.save_object(DataObject(type="dataset", source="imports/alpha"))
        store.save_object(DataObject(type="dataset", source="imports/alpha-2"))
        store.save_object(DataObject(type="report", source="imports/beta"))

        response = asyncio.run(
            api.list_objects(object_type="dataset", source="alpha", limit=1, offset=0)
        )

        assert response["total"] == 2
        assert len(response["objects"]) == 1
    finally:
        store.close()


def test_relationship_list_total_counts_all_filtered_rows(monkeypatch, tmp_path):
    api = importlib.import_module("backend.app")
    store = SQLiteStorage(str(tmp_path / "relationships.sqlite"))
    monkeypatch.setattr(api.dataos, "storage", store)
    try:
        source_a = store.save_object(DataObject(type="dataset", source="api://source-a"))
        source_b = store.save_object(DataObject(type="dataset", source="api://source-b"))
        target_1 = store.save_object(DataObject(type="report", source="api://target-1"))
        target_2 = store.save_object(DataObject(type="report", source="api://target-2"))
        target_3 = store.save_object(DataObject(type="report", source="api://target-3"))
        target_4 = store.save_object(DataObject(type="report", source="api://target-4"))

        store.save_relationship(Relationship(source=source_a.id, target=target_1.id, relation_type="references", confidence=0.9))
        store.save_relationship(Relationship(source=source_a.id, target=target_2.id, relation_type="references", confidence=0.8))
        store.save_relationship(Relationship(source=source_a.id, target=target_3.id, relation_type="references", confidence=0.2))
        store.save_relationship(Relationship(source=source_b.id, target=target_4.id, relation_type="references", confidence=0.95))

        response = asyncio.run(
            api.list_relationships(source_id=source_a.id, min_confidence=0.5, limit=1, offset=0)
        )
        assert response["total"] == 2
        assert len(response["relationships"]) == 1

        visible = store.list_relationships(source_id=source_a.id, min_confidence=0.5, limit=1)
        assert store.delete_relationship(visible[0].id, soft=True)
        after_delete = asyncio.run(
            api.list_relationships(source_id=source_a.id, min_confidence=0.5, limit=1, offset=0)
        )
        assert after_delete["total"] == 1
    finally:
        store.close()
