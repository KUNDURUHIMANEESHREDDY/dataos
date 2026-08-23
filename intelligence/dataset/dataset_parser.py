"""
Dataset Intelligence Parser for DataOS (Rule #8, Rule #10).
Parses CSV, JSON, TSV, Parquet structures into structured table metadata and records.
"""

from __future__ import annotations
import csv
import json
import io
from typing import Dict, Any, List, Optional
import pandas as pd


class DatasetParser:
    """Parses tabular and structured datasets into structured schemas and records."""

    @classmethod
    def parse_csv(cls, text_content: str, filename: str = "data.csv") -> Dict[str, Any]:
        """Parse CSV text using pandas with automatic type inference."""
        df = pd.read_csv(io.StringIO(text_content))
        return cls._dataframe_to_metadata(df, filename, "csv")

    @classmethod
    def parse_json(cls, json_content: str, filename: str = "data.json") -> Dict[str, Any]:
        """Parse JSON text into structured schema and records."""
        data = json.loads(json_content)
        if isinstance(data, list) and all(isinstance(item, dict) for item in data):
            df = pd.DataFrame(data)
            return cls._dataframe_to_metadata(df, filename, "json_records")
        elif isinstance(data, dict):
            # Dict with keys
            return {
                "format": "json_object",
                "filename": filename,
                "row_count": 1,
                "column_count": len(data.keys()),
                "columns": [{"name": k, "type": type(v).__name__} for k, v in data.items()],
                "sample_rows": [data],
                "shape": [1, len(data.keys())]
            }
        else:
            return {
                "format": "json_primitive",
                "filename": filename,
                "row_count": len(data) if isinstance(data, list) else 1,
                "column_count": 1,
                "columns": [{"name": "value", "type": "any"}],
                "sample_rows": data[:10] if isinstance(data, list) else [data],
                "shape": [len(data) if isinstance(data, list) else 1, 1]
            }

    @classmethod
    def _dataframe_to_metadata(cls, df: pd.DataFrame, filename: str, format_name: str) -> Dict[str, Any]:
        columns_meta = []
        for col_name in df.columns:
            dtype_str = str(df[col_name].dtype)
            null_count = int(df[col_name].isnull().sum())
            unique_count = int(df[col_name].nunique())
            
            # Simplified DataOS type
            if "int" in dtype_str:
                os_type = "integer"
            elif "float" in dtype_str:
                os_type = "float"
            elif "bool" in dtype_str:
                os_type = "boolean"
            elif "datetime" in dtype_str:
                os_type = "datetime"
            else:
                os_type = "string"

            columns_meta.append({
                "name": str(col_name),
                "pandas_dtype": dtype_str,
                "type": os_type,
                "null_count": null_count,
                "null_ratio": round(null_count / max(1, len(df)), 4),
                "unique_count": unique_count,
            })

        # Replace NaN with None for JSON serialization
        sample_df = df.head(10).where(pd.notnull(df.head(10)), None)
        
        return {
            "format": format_name,
            "filename": filename,
            "row_count": int(len(df)),
            "column_count": int(len(df.columns)),
            "columns": columns_meta,
            "shape": [int(len(df)), int(len(df.columns))],
            "sample_rows": sample_df.to_dict(orient="records"),
            "column_names": [str(c) for c in df.columns]
        }
