"""
Data Export Formats for DataOS (Rule #28).
Provides CSV and Parquet export handlers for datasets and DataObjects.
"""

from __future__ import annotations
import csv
import io
import json
import datetime
from typing import Dict, Any, List, Optional


class CSVExporter:
    """Exports data to CSV format."""

    @classmethod
    def export_rows(cls, rows: List[Dict[str, Any]], filename: str = "data.csv") -> Dict[str, Any]:
        """Export a list of dictionaries to CSV."""
        if not rows:
            return {"filename": filename, "format": "csv", "row_count": 0, "content": ""}

        columns = list(rows[0].keys())
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: _csv_safe(v) for k, v in row.items()})

        content = buf.getvalue()
        return {
            "filename": filename,
            "format": "csv",
            "row_count": len(rows),
            "column_count": len(columns),
            "columns": columns,
            "content": content,
            "size_bytes": len(content.encode("utf-8")),
        }

    @classmethod
    def export_from_dataframe(cls, df: Any, filename: str = "data.csv") -> Dict[str, Any]:
        """Export a pandas DataFrame to CSV."""
        try:
            import pandas as pd
            rows = df.to_dict(orient="records")
            result = cls.export_rows(rows, filename)
            result["source_type"] = "dataframe"
            return result
        except ImportError:
            return {"error": "pandas is required for DataFrame export"}

    @classmethod
    def export_objects(cls, objects: List[Any], filename: str = "objects.csv") -> Dict[str, Any]:
        """Export DataObject list to CSV with flattened fields."""
        rows = []
        for obj in objects:
            d = obj.to_dict() if hasattr(obj, "to_dict") else obj
            row = {
                "id": d.get("id", ""),
                "type": d.get("type", ""),
                "schema": d.get("schema", ""),
                "version": d.get("version", ""),
                "source": d.get("source", ""),
                "created_at": d.get("timestamps", {}).get("created_at", ""),
                "updated_at": d.get("timestamps", {}).get("updated_at", ""),
                "properties_json": json.dumps(d.get("properties", {}), default=str),
            }
            rows.append(row)
        return cls.export_rows(rows, filename)

    @classmethod
    def export_relationships(cls, relationships: List[Any], filename: str = "relationships.csv") -> Dict[str, Any]:
        """Export Relationship list to CSV."""
        rows = []
        for rel in relationships:
            d = rel.to_dict() if hasattr(rel, "to_dict") else rel
            rows.append({
                "id": d.get("id", ""),
                "source": d.get("source", ""),
                "target": d.get("target", ""),
                "relation_type": d.get("relation_type", ""),
                "confidence": d.get("confidence", 0),
                "created_at": d.get("created_at", ""),
            })
        return cls.export_rows(rows, filename)


class ParquetExporter:
    """Exports data to Parquet format. Falls back to CSV if pyarrow is unavailable."""

    @classmethod
    def export_rows(cls, rows: List[Dict[str, Any]], filename: str = "data.parquet") -> Dict[str, Any]:
        """Export a list of dictionaries to Parquet."""
        if not rows:
            return {"filename": filename, "format": "parquet", "row_count": 0}

        try:
            import pyarrow as pa
            import pyarrow.parquet as pq

            table = pa.Table.from_pylist(rows)
            buf = io.BytesIO()
            pq.write_table(table, buf)
            content = buf.getvalue()

            return {
                "filename": filename,
                "format": "parquet",
                "row_count": len(rows),
                "column_count": len(rows[0]) if rows else 0,
                "columns": list(rows[0].keys()) if rows else [],
                "content_bytes": content,
                "size_bytes": len(content),
            }
        except ImportError:
            # Fallback to CSV
            csv_result = CSVExporter.export_rows(rows, filename.replace(".parquet", ".csv"))
            csv_result["format"] = "parquet_fallback_csv"
            csv_result["warning"] = "pyarrow not installed, exported as CSV"
            return csv_result

    @classmethod
    def export_from_dataframe(cls, df: Any, filename: str = "data.parquet") -> Dict[str, Any]:
        """Export a pandas DataFrame to Parquet."""
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq

            table = pa.Table.from_pandas(df)
            buf = io.BytesIO()
            pq.write_table(table, buf)
            content = buf.getvalue()

            return {
                "filename": filename,
                "format": "parquet",
                "row_count": len(df),
                "column_count": len(df.columns),
                "columns": list(df.columns),
                "content_bytes": content,
                "size_bytes": len(content),
            }
        except ImportError:
            # Fallback to CSV
            rows = df.to_dict(orient="records") if hasattr(df, "to_dict") else []
            csv_result = CSVExporter.export_rows(rows, filename.replace(".parquet", ".csv"))
            csv_result["format"] = "parquet_fallback_csv"
            csv_result["warning"] = "pyarrow not installed, exported as CSV"
            return csv_result

    @classmethod
    def write_parquet_file(cls, rows: List[Dict[str, Any]], file_path: str) -> Dict[str, Any]:
        """Write Parquet to a file path."""
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq

            table = pa.Table.from_pylist(rows)
            pq.write_table(table, file_path)
            return {"filename": file_path, "format": "parquet", "row_count": len(rows), "status": "written"}
        except ImportError:
            return {"error": "pyarrow is required for Parquet write"}


class DataFormatExporter:
    """Unified exporter that routes to the correct format handler."""

    FORMATS = {
        "csv": CSVExporter,
        "parquet": ParquetExporter,
        "tsv": CSVExporter,
    }

    @classmethod
    def export(cls, data: List[Dict[str, Any]], format: str = "csv", filename: str = "", **kwargs) -> Dict[str, Any]:
        """Export data to the specified format."""
        if not filename:
            timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
            filename = f"export_{timestamp}.{format}"

        if format == "tsv":
            return CSVExporter.export_rows(data, filename)

        exporter = cls.FORMATS.get(format)
        if not exporter:
            return {"error": f"Unsupported format: {format}. Supported: {list(cls.FORMATS.keys())}"}

        return exporter.export_rows(data, filename, **kwargs)

    @classmethod
    def export_objects(cls, objects: List[Any], format: str = "csv", filename: str = "") -> Dict[str, Any]:
        """Export DataObjects to the specified format."""
        if not filename:
            filename = f"objects_export.{format}"
        if format == "csv":
            return CSVExporter.export_objects(objects, filename)
        rows = []
        for obj in objects:
            d = obj.to_dict() if hasattr(obj, "to_dict") else obj
            rows.append(d)
        return cls.export(rows, format, filename)

    @classmethod
    def list_formats(cls) -> List[str]:
        """Return list of supported export formats."""
        return list(cls.FORMATS.keys())


def _csv_safe(val: Any) -> str:
    """Convert a value to a CSV-safe string."""
    if val is None:
        return ""
    if isinstance(val, (dict, list)):
        return json.dumps(val, default=str)
    return str(val)
