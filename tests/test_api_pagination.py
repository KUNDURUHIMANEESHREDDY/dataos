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
        store.save_relationship(Relationship(source="source-a", target="target-1", relation_type="references", confidence=0.9))
        store.save_relationship(Relationship(source="source-a", target="target-2", relation_type="references", confidence=0.8))
        store.save_relationship(Relationship(source="source-a", target="target-3", relation_type="references", confidence=0.2))
        store.save_relationship(Relationship(source="source-b", target="target-4", relation_type="references", confidence=0.95))

        response = asyncio.run(
            api.list_relationships(source_id="source-a", min_confidence=0.5, limit=1, offset=0)
        )
        assert response["total"] == 2
        assert len(response["relationships"]) == 1

        visible = store.list_relationships(source_id="source-a", min_confidence=0.5, limit=1)
        assert store.delete_relationship(visible[0].id, soft=True)
        after_delete = asyncio.run(
            api.list_relationships(source_id="source-a", min_confidence=0.5, limit=1, offset=0)
        )
        assert after_delete["total"] == 1
    finally:
        store.close()
