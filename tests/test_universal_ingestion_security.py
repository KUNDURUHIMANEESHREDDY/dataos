"""Security regression tests for local-file ingestion boundaries."""

from pathlib import Path
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

            with self.assertRaisesRegex(ValueError, "basename"):
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


if __name__ == "__main__":
    unittest.main()
