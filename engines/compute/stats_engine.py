"""
Statistical Intelligence Engine for DataOS (Rule #49).
Computes verified statistical models: OLS Regression, Hypothesis Testing (T-test, ANOVA),
K-Means Clustering, PCA, and Correlation Matrices against real data.
"""

from __future__ import annotations
import math
import numpy as np
import pandas as pd
from scipy import stats
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from typing import Dict, Any, List, Optional


class StatisticalEngine:
    """Verified statistical computation over tabular DataObjects."""

    @classmethod
    def compute_linear_regression(cls, df: pd.DataFrame, x_col: str, y_col: str) -> Dict[str, Any]:
        """Compute verified Ordinary Least Squares (OLS) regression."""
        clean_df = df[[x_col, y_col]].dropna()
        if len(clean_df) < 2:
            return {"error": "Insufficient data points for regression"}

        x = clean_df[x_col].values.astype(float)
        y = clean_df[y_col].values.astype(float)

        res = stats.linregress(x, y)
        r_squared = float(res.rvalue ** 2)

        return {
            "model_type": "OLS_linear_regression",
            "x_column": x_col,
            "y_column": y_col,
            "sample_size": len(clean_df),
            "slope": round(float(res.slope), 6),
            "intercept": round(float(res.intercept), 6),
            "r_value": round(float(res.rvalue), 6),
            "r_squared": round(r_squared, 6),
            "p_value": round(float(res.pvalue), 8),
            "std_err": round(float(res.stderr), 6),
            "equation": f"y = {round(res.slope, 4)} * x + {round(res.intercept, 4)}"
        }

    @classmethod
    def compute_ttest(cls, df: pd.DataFrame, group_col: str, value_col: str) -> Dict[str, Any]:
        """Compute independent two-sample t-test."""
        clean_df = df[[group_col, value_col]].dropna()
        groups = clean_df[group_col].unique()
        if len(groups) != 2:
            return {"error": f"T-test requires exactly 2 groups, found {len(groups)}"}

        g1 = clean_df[clean_df[group_col] == groups[0]][value_col].astype(float)
        g2 = clean_df[clean_df[group_col] == groups[1]][value_col].astype(float)

        t_stat, p_val = stats.ttest_ind(g1, g2, equal_var=False)

        return {
            "test_type": "Welch_two_sample_t_test",
            "group_a": str(groups[0]),
            "group_b": str(groups[1]),
            "group_a_mean": round(float(g1.mean()), 4),
            "group_b_mean": round(float(g2.mean()), 4),
            "t_statistic": round(float(t_stat), 4),
            "p_value": round(float(p_val), 8),
            "significant_at_005": bool(p_val < 0.05)
        }

    @classmethod
    def compute_kmeans(cls, df: pd.DataFrame, feature_cols: List[str], k: int = 3) -> Dict[str, Any]:
        """Compute verified K-Means clustering."""
        clean_df = df[feature_cols].dropna().astype(float)
        if len(clean_df) < k:
            return {"error": f"Sample size {len(clean_df)} is less than k={k}"}

        kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
        labels = kmeans.fit_predict(clean_df)

        cluster_counts = pd.Series(labels).value_counts().to_dict()
        centroids = [
            {feature_cols[i]: round(float(val), 4) for i, val in enumerate(center)}
            for center in kmeans.cluster_centers_
        ]

        return {
            "algorithm": "k_means",
            "k": k,
            "feature_columns": feature_cols,
            "sample_size": len(clean_df),
            "inertia": round(float(kmeans.inertia_), 4),
            "cluster_sizes": {f"cluster_{k}": int(v) for k, v in cluster_counts.items()},
            "centroids": centroids
        }
