"""
Tests for Export Formats (Rule #28).
Validates CSV and Parquet export handlers.
"""

import unittest
import io
from infrastructure.io.format_export import CSVExporter, ParquetExporter, DataFormatExporter


class TestCSVExporter(unittest.TestCase):

    def test_export_rows(self):
        data = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
        result = CSVExporter.export_rows(data, "test.csv")
        self.assertEqual(result["row_count"], 2)
        self.assertEqual(result["column_count"], 2)
        self.assertIn("id", result["columns"])

    def test_export_empty(self):
        result = CSVExporter.export_rows([], "empty.csv")
        self.assertEqual(result["row_count"], 0)

    def test_export_content(self):
        data = [{"id": 1, "name": "Alice"}]
        result = CSVExporter.export_rows(data, "test.csv")
        self.assertIn("id", result["content"])
        self.assertIn("Alice", result["content"])

    def test_export_with_dict_column(self):
        data = [{"id": 1, "meta": {"key": "val"}}]
        result = CSVExporter.export_rows(data, "test.csv")
        self.assertIn("key", result["content"])

    def test_export_with_none(self):
        data = [{"id": 1, "val": None}]
        result = CSVExporter.export_rows(data, "test.csv")
        self.assertEqual(result["row_count"], 1)

    def test_export_objects(self):
        from core.object.model import DataObject
        objects = [DataObject(id="o1", type="document"), DataObject(id="o2", type="dataset")]
        result = CSVExporter.export_objects(objects, "objects.csv")
        self.assertEqual(result["row_count"], 2)
        self.assertIn("o1", result["content"])

    def test_export_relationships(self):
        from core.relation.model import Relationship
        rels = [Relationship(id="r1", source="a", target="b", relation_type="X")]
        result = CSVExporter.export_relationships(rels, "rels.csv")
        self.assertEqual(result["row_count"], 1)
        self.assertIn("X", result["content"])

    def test_size_bytes(self):
        data = [{"a": 1}]
        result = CSVExporter.export_rows(data)
        self.assertGreater(result["size_bytes"], 0)


class TestParquetExporter(unittest.TestCase):

    def test_export_rows_fallback(self):
        """Without pyarrow, should fall back to CSV."""
        data = [{"id": 1, "name": "Alice"}]
        result = ParquetExporter.export_rows(data, "test.parquet")
        self.assertIn("format", result)
        # May be parquet or parquet_fallback_csv depending on pyarrow availability

    def test_export_empty(self):
        result = ParquetExporter.export_rows([], "empty.parquet")
        self.assertEqual(result["row_count"], 0)

    def test_export_from_dataframe_fallback(self):
        """Without pyarrow, should handle gracefully."""
        try:
            import pandas as pd
            df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
            result = ParquetExporter.export_from_dataframe(df, "test.parquet")
            self.assertIn("format", result)
        except ImportError:
            self.skipTest("pandas not available")


class TestDataFormatExporter(unittest.TestCase):

    def test_export_csv(self):
        data = [{"id": 1}]
        result = DataFormatExporter.export(data, "csv")
        self.assertEqual(result["row_count"], 1)

    def test_export_tsv(self):
        data = [{"id": 1}]
        result = DataFormatExporter.export(data, "tsv")
        self.assertEqual(result["row_count"], 1)

    def test_export_unsupported(self):
        result = DataFormatExporter.export([{"id": 1}], "yaml")
        self.assertIn("error", result)

    def test_list_formats(self):
        formats = DataFormatExporter.list_formats()
        self.assertIn("csv", formats)
        self.assertIn("parquet", formats)

    def test_export_auto_filename(self):
        result = DataFormatExporter.export([{"id": 1}], "csv")
        self.assertIn(".csv", result["filename"])


if __name__ == "__main__":
    unittest.main()
