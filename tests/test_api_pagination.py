"""Regression tests for object-list pagination metadata."""

import asyncio
import importlib

from core.object.model import DataObject
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
