"""Security regression tests for local-file ingestion and request-scoped ACLs."""

from pathlib import Path
import json
import tempfile
import unittest

from infrastructure.io.universal_ingest import UniversalIngestionPipeline
from infrastructure.storage.sqlite_store import SQLiteStorage


class TestUniversalIngestionSecurity(unittest.TestCase):
    def test_path_ingestion_requires_a_trusted_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = SQLiteStorage(db_path=str(Path(tmp) / "storage.db"))
            pipeline = UniversalIngestionPipeline(
                storage,
                db_path=str(Path(tmp) / "index.db"),
            )
            with self.assertRaisesRegex(ValueError, "DATAOS_INGEST_ROOT"):
                pipeline.ingest(Path("safe.csv"), filename="safe.csv")

    def test_path_ingestion_is_confined_to_root_and_basename(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ingest"
            root.mkdir()
            (root / "safe.csv").write_text("name,value\nalpha,1\n", encoding="utf-8")
            storage = SQLiteStorage(db_path=str(Path(tmp) / "storage.db"))
            pipeline = UniversalIngestionPipeline(
                storage,
                db_path=str(Path(tmp) / "index.db"),
                allowed_file_root=str(root),
            )

            result = pipeline.ingest(
                Path("safe.csv"),
                filename="safe.csv",
                discover_relations=False,
            )
            self.assertEqual(result["status"], "ingested")
            self.assertEqual(result["filename"], "safe.csv")

            with self.assertRaisesRegex(ValueError, "filename"):
                pipeline.ingest(Path("../outside.csv"), filename="outside.csv")

    def test_string_paths_are_content_not_filesystem_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ingest"
            root.mkdir()
            secret = root / "secret.txt"
            secret.write_text("should not be read implicitly", encoding="utf-8")
            storage = SQLiteStorage(db_path=str(Path(tmp) / "storage.db"))
            pipeline = UniversalIngestionPipeline(
                storage,
                db_path=str(Path(tmp) / "index.db"),
                allowed_file_root=str(root),
            )

            result = pipeline.ingest(str(secret), filename="path-string.txt", discover_relations=False)
            saved = storage.get_object(result["primary_object_id"])
            self.assertEqual(saved.content, str(secret))

    def test_csv_ingestion_preserves_request_scoped_permissions_and_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = SQLiteStorage(db_path=str(Path(tmp) / "storage.db"))
            pipeline = UniversalIngestionPipeline(
                storage,
                db_path=str(Path(tmp) / "index.db"),
            )
            permissions = {
                "owner": "alice",
                "read": ["alice"],
                "write": ["alice"],
            }

            result = pipeline.ingest(
                "name,value\nalpha,1\n",
                filename="private.csv",
                discover_relations=False,
                permissions=permissions,
            )
            saved = storage.get_object(result["primary_object_id"])

            self.assertEqual(saved.permissions, permissions)
            self.assertEqual(saved.content, [{"name": "alpha", "value": 1}])

    def test_notebook_and_rich_document_children_inherit_request_acl(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = SQLiteStorage(db_path=str(Path(tmp) / "storage.db"))
            pipeline = UniversalIngestionPipeline(
                storage,
                db_path=str(Path(tmp) / "index.db"),
            )
            permissions = {
                "owner": "alice",
                "read": ["alice"],
                "write": ["alice"],
            }

            notebook_content = json.dumps({
                "cells": [{
                    "cell_type": "code",
                    "execution_count": 1,
                    "metadata": {},
                    "outputs": [],
                    "source": ["value = 1\n"],
                }],
                "metadata": {},
                "nbformat": 4,
                "nbformat_minor": 5,
            })
            notebook_result = pipeline.ingest(
                notebook_content,
                filename="private.ipynb",
                discover_relations=False,
                permissions=permissions,
            )
            notebook_objects = [
                obj for obj in storage.list_objects(limit=1000)
                if obj.id == notebook_result["primary_object_id"]
                or obj.properties.get("notebook_id") == notebook_result["primary_object_id"]
            ]
            self.assertEqual(len(notebook_objects), 2)
            self.assertTrue(all(obj.permissions == permissions for obj in notebook_objects))

            markdown = (
                "# Private report\n\n"
                "| Name | Value |\n"
                "| --- | --- |\n"
                "| alpha | 1 |\n\n"
                "[^source]: Private citation\n"
            )
            document_result = pipeline.ingest(
                markdown,
                filename="private.md",
                discover_relations=False,
                permissions=permissions,
            )
            document_objects = [
                obj for obj in storage.list_objects(limit=1000)
                if obj.id == document_result["primary_object_id"]
                or obj.properties.get("parent_document_id") == document_result["primary_object_id"]
            ]
            self.assertEqual(len(document_objects), 3)
            self.assertTrue(all(obj.permissions == permissions for obj in document_objects))


if __name__ == "__main__":
    unittest.main()
