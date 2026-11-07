"""End-to-end request ACL propagation through the universal ingestion pipeline."""
from __future__ import annotations

import json

from infrastructure.io.universal_ingest import UniversalIngestionPipeline


class MemoryStorage:
    def __init__(self):
        self.objects = {}
        self.relationships = []

    def save_object(self, obj):
        self.objects[obj.id] = obj
        return obj

    def get_object(self, object_id):
        return self.objects.get(object_id)

    def list_objects(self, object_type=None, source=None, limit=100, offset=0):
        rows = list(self.objects.values())
        if object_type:
            rows = [item for item in rows if item.type == object_type]
        if source:
            rows = [item for item in rows if source in item.source]
        return rows[offset:offset + limit]

    def save_relationship(self, relationship):
        self.relationships.append(relationship)
        return relationship

    def list_relationships(self, source_id=None, target_id=None, **kwargs):
        rows = self.relationships
        if source_id:
            rows = [item for item in rows if item.source == source_id]
        if target_id:
            rows = [item for item in rows if item.target == target_id]
        return rows

    def count_objects(self, object_type=None, source=None):
        return len(self.list_objects(object_type=object_type, source=source))


def _ingest(content: str, filename: str, permissions: dict, monkeypatch):
    storage = MemoryStorage()
    pipeline = UniversalIngestionPipeline(storage, db_path=":memory:")
    monkeypatch.setattr(pipeline.vector_index, "index_object", lambda obj: None)
    result = pipeline.ingest(
        content,
        filename=filename,
        discover_relations=False,
        permissions=permissions,
    )
    assert result["status"] == "ingested"
    assert storage.objects
    assert all(obj.permissions == permissions for obj in storage.objects.values())
    return result, storage


def test_json_ingestion_assigns_creator_acl(monkeypatch):
    permissions = {"owner": "alice", "read": ["alice"], "write": ["alice"]}
    result, storage = _ingest(json.dumps({"customer": "synthetic"}), "private.json", permissions, monkeypatch)
    assert result["created_objects_count"] == 1
    assert next(iter(storage.objects.values())).permissions == permissions


def test_notebook_ingestion_propagates_acl_to_parent_and_every_cell(monkeypatch):
    permissions = {"owner": "alice", "read": ["alice"], "write": ["alice"]}
    notebook = json.dumps({
        "cells": [
            {"cell_type": "code", "source": ["value = 1"], "metadata": {}, "outputs": []},
            {"cell_type": "markdown", "source": ["# Private notes"], "metadata": {}},
        ],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 5,
    })
    result, storage = _ingest(notebook, "private.ipynb", permissions, monkeypatch)
    assert result["created_objects_count"] == 1
    assert len(storage.objects) == 3
    assert all(obj.permissions == permissions for obj in storage.objects.values())
    assert len(storage.relationships) == 2


def test_rich_document_ingestion_propagates_acl_to_parent_tables_and_citations(monkeypatch):
    permissions = {"owner": "alice", "read": ["alice"], "write": ["alice"]}
    markdown = (
        "# Private report\n\n"
        "| Metric | Value |\n|---|---|\n| Revenue | 10 |\n\n"
        "[^1]: Internal source"
    )
    result, storage = _ingest(markdown, "private.md", permissions, monkeypatch)
    assert result["created_objects_count"] == 1
    assert result["extracted_tables_count"] == 1
    assert len(storage.objects) == 3
    assert all(obj.permissions == permissions for obj in storage.objects.values())
    assert len(storage.relationships) == 2
