"""
Tests for Ingestion Adapters (Rule #33).
Validates Archive, Database, API, and Git ingestion sources.
"""

import warnings
warnings.filterwarnings("ignore", category=ResourceWarning, message="Implicitly cleaning up")

import unittest
import io
import json
import zipfile
from unittest.mock import patch, MagicMock
from infrastructure.io.ingestion_adapters import (
    IngestionAdapterManager, ArchiveIngestionAdapter, DatabaseIngestionAdapter,
    APIIngestionAdapter, GitIngestionAdapter, IngestionSource,
)


class TestIngestionAdapterManager(unittest.TestCase):

    def setUp(self):
        self.manager = IngestionAdapterManager()

    def test_list_sources(self):
        sources = self.manager.list_sources()
        self.assertIn("archive", sources)
        self.assertIn("database", sources)
        self.assertIn("api", sources)
        self.assertIn("git", sources)

    def test_get_adapter(self):
        adapter = self.manager.get("archive")
        self.assertIsNotNone(adapter)

    def test_get_nonexistent(self):
        adapter = self.manager.get("nonexistent")
        self.assertIsNone(adapter)

    def test_ingest_unknown_source(self):
        result = self.manager.ingest("nonexistent", {})
        self.assertIn("error", result)

    def test_ingest_validation_failure(self):
        result = self.manager.ingest("archive", {})
        self.assertIn("error", result)
        self.assertIn("Validation failed", result["error"])


class TestArchiveIngestionAdapter(unittest.TestCase):

    def setUp(self):
        self.adapter = ArchiveIngestionAdapter()

    def test_validate_config(self):
        errors = self.adapter.validate_config({})
        self.assertGreater(len(errors), 0)

    def test_validate_config_valid(self):
        errors = self.adapter.validate_config({"archive_path": "test.zip"})
        self.assertEqual(len(errors), 0)

    def test_ingest_zip(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("file1.txt", "Hello World")
            z.writestr("data/file2.csv", "id,name\n1,Alice")
        result = self.adapter.ingest({"archive_bytes": buf.getvalue()})
        self.assertEqual(result["format"], "zip")
        self.assertEqual(result["total_files"], 2)

    def test_ingest_zip_with_filter(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("data.csv", "id\n1")
            z.writestr("readme.txt", "hi")
        result = self.adapter.ingest({"archive_bytes": buf.getvalue(), "filter": "*.csv"})
        self.assertEqual(result["total_files"], 1)

    def test_ingest_empty_zip(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            pass
        result = self.adapter.ingest({"archive_bytes": buf.getvalue()})
        self.assertEqual(result["total_files"], 0)

    def test_ingest_invalid_zip(self):
        result = self.adapter.ingest({"archive_bytes": b"not a zip"})
        self.assertIn("error", result)

    def test_ingest_no_data(self):
        result = self.adapter.ingest({})
        self.assertIn("error", result)

    def test_file_metadata(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("test.txt", "content")
        result = self.adapter.ingest({"archive_bytes": buf.getvalue()})
        f = result["files"][0]
        self.assertEqual(f["filename"], "test.txt")
        self.assertIn("sha256", f)


class TestDatabaseIngestionAdapter(unittest.TestCase):

    def setUp(self):
        self.adapter = DatabaseIngestionAdapter()

    def test_validate_config(self):
        errors = self.adapter.validate_config({})
        self.assertGreater(len(errors), 0)

    def test_validate_config_valid(self):
        errors = self.adapter.validate_config({"db_type": "sqlite", "query": "SELECT 1"})
        self.assertEqual(len(errors), 0)

    def test_ingest_sqlite_memory(self):
        result = self.adapter.ingest({
            "db_type": "sqlite",
            "connection_string": ":memory:",
            "query": "SELECT 1 as id, 'Alice' as name",
        })
        self.assertEqual(result["db_type"], "sqlite")
        self.assertEqual(result["row_count"], 1)
        self.assertEqual(result["data"][0]["name"], "Alice")

    def test_ingest_sqlite_invalid(self):
        result = self.adapter.ingest({
            "db_type": "sqlite",
            "connection_string": ":memory:",
            "query": "SELECT * FROM nonexistent_table",
        })
        self.assertTrue("error" in result or result.get("row_count", 0) == 0)

    def test_ingest_unsupported_db(self):
        result = self.adapter.ingest({"db_type": "oracle", "query": "SELECT 1"})
        self.assertIn("error", result)

    def test_ingest_postgresql_import_error(self):
        result = self.adapter.ingest({
            "db_type": "postgresql",
            "connection_string": "postgresql://localhost/test",
            "query": "SELECT 1",
        })
        self.assertIn("error", result)


class TestAPIIngestionAdapter(unittest.TestCase):

    def setUp(self):
        self.adapter = APIIngestionAdapter()

    def test_validate_config(self):
        errors = self.adapter.validate_config({})
        self.assertGreater(len(errors), 0)

    def test_validate_config_valid(self):
        errors = self.adapter.validate_config({"url": "https://example.com"})
        self.assertEqual(len(errors), 0)

    @patch("urllib.request.urlopen")
    def test_ingest_json(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"key": "value"}).encode()
        mock_resp.status = 200
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = self.adapter.ingest({"url": "https://api.example.com/data"})
        self.assertEqual(result["status_code"], 200)
        self.assertEqual(result["data"]["key"], "value")

    @patch("urllib.request.urlopen")
    def test_ingest_text(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"plain text"
        mock_resp.status = 200
        mock_resp.headers = {}
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = self.adapter.ingest({"url": "https://example.com/data", "response_type": "text"})
        self.assertEqual(result["data"], "plain text")

    @patch("urllib.request.urlopen")
    def test_ingest_http_error(self, mock_urlopen):
        import warnings
        from urllib.error import HTTPError
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)
            mock_urlopen.side_effect = HTTPError("https://x", 404, "Not Found", {}, None)
            result = self.adapter.ingest({"url": "https://api.example.com/missing"})
            mock_urlopen.side_effect = None
        self.assertIn("error", result)


class TestGitIngestionAdapter(unittest.TestCase):

    def setUp(self):
        self.adapter = GitIngestionAdapter()

    def test_validate_config(self):
        errors = self.adapter.validate_config({})
        self.assertGreater(len(errors), 0)

    def test_validate_config_valid(self):
        errors = self.adapter.validate_config({"local_path": "/some/path"})
        self.assertEqual(len(errors), 0)

    def test_ingest_nonexistent_path(self):
        result = self.adapter.ingest({"local_path": "/nonexistent/path"})
        self.assertIn("error", result)


class TestIngestionSource(unittest.TestCase):

    def test_values(self):
        self.assertEqual(IngestionSource.ARCHIVE.value, "archive")
        self.assertEqual(IngestionSource.DATABASE.value, "database")
        self.assertEqual(IngestionSource.API.value, "api")
        self.assertEqual(IngestionSource.GIT.value, "git")


if __name__ == "__main__":
    unittest.main()
