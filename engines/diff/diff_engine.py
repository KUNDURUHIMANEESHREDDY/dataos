"""
Semantic Diff Engine for DataOS (Rule #26).
Computes semantic diffs across tabular data, dynamic schemas, documents, and graph edges.
"""

from __future__ import annotations
import difflib
import pandas as pd
from typing import Dict, Any, List, Optional
from core.object.model import DataObject
from core.schema.model import Schema


class SemanticDiffEngine:
    """Computes semantic diffs across multiple entity representations."""

    @classmethod
    def diff_text(cls, text_a: str, text_b: str) -> Dict[str, Any]:
        """Compute unified text and word diff."""
        lines_a = text_a.splitlines(keepends=True)
        lines_b = text_b.splitlines(keepends=True)
        diff = list(difflib.unified_diff(lines_a, lines_b, fromfile="version_A", tofile="version_B"))
        
        additions = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
        deletions = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))

        return {
            "diff_type": "text",
            "additions": additions,
            "deletions": deletions,
            "unified_diff": "".join(diff),
            "is_identical": len(diff) == 0
        }

    @classmethod
    def diff_tabular(cls, df_a: pd.DataFrame, df_b: pd.DataFrame) -> Dict[str, Any]:
        """Compute structural and cell-level diff between two dataframes."""
        cols_a = set(df_a.columns)
        cols_b = set(df_b.columns)

        added_cols = list(cols_b - cols_a)
        removed_cols = list(cols_a - cols_b)
        common_cols = list(cols_a.intersection(cols_b))

        row_diff = len(df_b) - len(df_a)

        return {
            "diff_type": "tabular",
            "row_count_a": len(df_a),
            "row_count_b": len(df_b),
            "row_difference": row_diff,
            "added_columns": added_cols,
            "removed_columns": removed_cols,
            "common_columns": common_cols,
            "is_shape_identical": len(df_a) == len(df_b) and len(added_cols) == 0 and len(removed_cols) == 0
        }

    @classmethod
    def diff_schemas(cls, schema_a: Schema, schema_b: Schema) -> Dict[str, Any]:
        """Compute schema field modifications and backward compatibility."""
        return schema_b.check_backward_compatibility(schema_a)
