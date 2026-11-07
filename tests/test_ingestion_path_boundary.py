"""Regression tests for the explicit local-file ingestion boundary."""

import tempfile
import unittest
from pathlib import Path

from dataos_system import DataOS


class TestIngestionPathBoundary(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.dataos = DataOS(
            db_path=str(root / "dataos.db"),
            blob_dir=str(root / "blobs"),
        )

    def tearDown(self):
        self.dataos.close()
        self.temp_dir.cleanup()

    def test_string_that_names_existing_file_is_ingested_as_content(self):
        source = Path(self.temp_dir.name) / "private.txt"
        source.write_text("server-only secret marker", encoding="utf-8")

        result = self.dataos.ingest(
            str(source),
            filename="submitted.bin",
            discover_relations=False,
        )
        obj = self.dataos.objects.get(result["primary_object_id"])

        self.assertEqual(obj.content, str(source))
        self.assertNotIn("server-only secret marker", str(obj.content))



if __name__ == "__main__":
    unittest.main()
