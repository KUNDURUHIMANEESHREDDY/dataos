"""
Data Profiling Engine for DataOS (Rule #10).
Computes real statistical metrics: row/column counts, null ratios, uniqueness,
cardinality, distributions, descriptive statistics, correlations, and outlier detection.
All results computed from actual data—NEVER simulated.
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional
from core.object.model import DataObject, ObjectType
from core.provenance.model import ProvenanceRecord


class DataProfiler:
    """Computes comprehensive, real statistical profiles of tabular datasets."""

    @classmethod
    def profile_dataframe(cls, df: pd.DataFrame, dataset_name: str = "dataset") -> Dict[str, Any]:
        """Compute verified profile from pandas DataFrame."""
        total_rows = int(len(df))
        total_cols = int(len(df.columns))

        if total_rows == 0:
            return {
                "dataset_name": dataset_name,
                "row_count": 0,
                "column_count": total_cols,
                "columns": {},
                "correlations": {},
                "summary": {"completeness_ratio": 0.0}
            }

        total_cells = total_rows * total_cols
        total_nulls = int(df.isnull().sum().sum())
        completeness_ratio = round(1.0 - (total_nulls / max(1, total_cells)), 4)

        column_profiles: Dict[str, Dict[str, Any]] = {}
        numeric_cols: List[str] = []

        for col in df.columns:
            col_series = df[col]
            null_count = int(col_series.isnull().sum())
            null_ratio = round(null_count / total_rows, 4)
            unique_count = int(col_series.nunique())
            uniqueness_ratio = round(unique_count / total_rows, 4)
            dtype_str = str(col_series.dtype)

            col_meta: Dict[str, Any] = {
                "name": str(col),
                "dtype": dtype_str,
                "null_count": null_count,
                "null_ratio": null_ratio,
                "unique_count": unique_count,
                "uniqueness_ratio": uniqueness_ratio,
                "is_unique": bool(unique_count == total_rows and null_count == 0),
            }

            if pd.api.types.is_numeric_dtype(col_series):
                numeric_cols.append(str(col))
                clean_series = col_series.dropna().astype(float)
                
                if len(clean_series) > 0:
                    mean_val = float(clean_series.mean())
                    std_val = float(clean_series.std()) if len(clean_series) > 1 else 0.0
                    min_val = float(clean_series.min())
                    max_val = float(clean_series.max())
                    q25 = float(clean_series.quantile(0.25))
                    median_val = float(clean_series.median())
                    q75 = float(clean_series.quantile(0.75))
                    iqr = q75 - q25

                    # Outlier detection via IQR
                    lower_bound = q25 - (1.5 * iqr)
                    upper_bound = q75 + (1.5 * iqr)
                    outliers = clean_series[(clean_series < lower_bound) | (clean_series > upper_bound)]
                    outlier_count = int(len(outliers))

                    # Histogram bins
                    hist_counts, bin_edges = np.histogram(clean_series, bins=min(10, max(2, len(clean_series))))
                    hist_bins = [
                        {"range": f"{round(bin_edges[i], 2)} - {round(bin_edges[i+1], 2)}", "count": int(hist_counts[i])}
                        for i in range(len(hist_counts))
                    ]

                    col_meta.update({
                        "kind": "numeric",
                        "mean": round(mean_val, 4),
                        "std": round(std_val, 4),
                        "min": round(min_val, 4),
                        "q25": round(q25, 4),
                        "median": round(median_val, 4),
                        "q75": round(q75, 4),
                        "max": round(max_val, 4),
                        "iqr": round(iqr, 4),
                        "outlier_count": outlier_count,
                        "outlier_ratio": round(outlier_count / total_rows, 4),
                        "histogram": hist_bins,
                        "skewness": round(float(clean_series.skew()), 4) if len(clean_series) > 2 else 0.0
                    })
                else:
                    col_meta["kind"] = "numeric_all_null"
            else:
                # Categorical
                top_values = col_series.value_counts().head(10).to_dict()
                col_meta.update({
                    "kind": "categorical",
                    "top_values": {str(k): int(v) for k, v in top_values.items()},
                    "mode": str(col_series.mode().iloc[0]) if not col_series.empty and len(col_series.mode()) > 0 else None
                })

            column_profiles[str(col)] = col_meta

        # Correlation matrix for numeric columns
        correlations: Dict[str, Dict[str, float]] = {}
        if len(numeric_cols) >= 2:
            corr_df = df[numeric_cols].corr(method="pearson")
            for col_a in numeric_cols:
                correlations[col_a] = {}
                for col_b in numeric_cols:
                    val = corr_df.loc[col_a, col_b]
                    correlations[col_a][col_b] = round(float(val), 4) if pd.notnull(val) else 0.0

        return {
            "dataset_name": dataset_name,
            "row_count": total_rows,
            "column_count": total_cols,
            "total_cells": total_cells,
            "total_nulls": total_nulls,
            "completeness_ratio": completeness_ratio,
            "columns": column_profiles,
            "correlations": correlations,
            "numeric_columns": numeric_cols,
            "summary": {
                "rows": total_rows,
                "columns": total_cols,
                "completeness_ratio": completeness_ratio,
                "numeric_column_count": len(numeric_cols),
                "categorical_column_count": total_cols - len(numeric_cols)
            }
        }
