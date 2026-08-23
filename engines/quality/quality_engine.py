"""
Data Quality Engine & Assertion Validator for DataOS (Rule #11).
Executes reusable quality checks: schema enforcement, null limits, range/regex checks,
statistical drift detection, and stores reports as first-class DataOS objects.
"""

from __future__ import annotations
import re
import datetime
import pandas as pd
from scipy import stats
from typing import Dict, Any, List, Optional
from core.object.model import DataObject, ObjectType


class QualityCheckResult:
    """Result of a single quality check evaluation."""

    def __init__(self, check_name: str, passed: bool, severity: str, message: str, details: Optional[Dict[str, Any]] = None):
        self.check_name = check_name
        self.passed = passed
        self.severity = severity  # "ERROR", "WARNING", "INFO"
        self.message = message
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the quality check result to a dictionary."""
        return {
            "check_name": self.check_name,
            "passed": self.passed,
            "severity": self.severity,
            "message": self.message,
            "details": self.details
        }


class DataQualityEngine:
    """Evaluates data quality assertions and statistical drift on real data."""

    @classmethod
    def evaluate_rules(cls, df: pd.DataFrame, rules: List[Dict[str, Any]], target_object_id: str = "") -> DataObject:
        """
        Evaluate quality rules against a DataFrame and produce a first-class QualityReport DataObject.
        Supported rule types:
        - "not_null": {"column": str, "max_null_ratio": float}
        - "unique": {"column": str}
        - "range": {"column": str, "min": float, "max": float}
        - "regex": {"column": str, "pattern": str}
        - "row_count_min": {"min_rows": int}
        """
        results: List[QualityCheckResult] = []

        for rule in rules:
            rtype = rule.get("type")
            col = rule.get("column")

            if rtype == "row_count_min":
                min_rows = rule.get("min_rows", 1)
                passed = len(df) >= min_rows
                results.append(QualityCheckResult(
                    check_name="row_count_min",
                    passed=passed,
                    severity="ERROR" if not passed else "INFO",
                    message=f"Row count {len(df)} >= {min_rows}" if passed else f"Row count {len(df)} is below minimum {min_rows}",
                    details={"actual_rows": len(df), "min_rows": min_rows}
                ))

            elif col and col not in df.columns:
                results.append(QualityCheckResult(
                    check_name=f"column_exists_{col}",
                    passed=False,
                    severity="ERROR",
                    message=f"Required column '{col}' does not exist in dataset",
                    details={"missing_column": col}
                ))
                continue

            elif rtype == "not_null":
                max_null_ratio = rule.get("max_null_ratio", 0.0)
                actual_ratio = float(df[col].isnull().sum()) / max(1, len(df))
                passed = actual_ratio <= max_null_ratio
                results.append(QualityCheckResult(
                    check_name=f"not_null_{col}",
                    passed=passed,
                    severity="ERROR" if not passed else "INFO",
                    message=f"Column '{col}' null ratio {round(actual_ratio, 4)} <= threshold {max_null_ratio}" if passed else f"Column '{col}' null ratio {round(actual_ratio, 4)} exceeds {max_null_ratio}",
                    details={"actual_null_ratio": actual_ratio, "threshold": max_null_ratio}
                ))

            elif rtype == "unique":
                total = len(df)
                unique_cnt = df[col].nunique()
                passed = bool(unique_cnt == total)
                results.append(QualityCheckResult(
                    check_name=f"unique_{col}",
                    passed=passed,
                    severity="ERROR" if not passed else "INFO",
                    message=f"Column '{col}' is strictly unique" if passed else f"Column '{col}' has duplicates ({unique_cnt} unique of {total} rows)",
                    details={"unique_count": unique_cnt, "total_rows": total}
                ))

            elif rtype == "range":
                min_v = rule.get("min")
                max_v = rule.get("max")
                num_series = df[col].dropna().astype(float)
                violations = 0
                if min_v is not None:
                    violations += int((num_series < min_v).sum())
                if max_v is not None:
                    violations += int((num_series > max_v).sum())
                passed = violations == 0
                results.append(QualityCheckResult(
                    check_name=f"range_{col}",
                    passed=passed,
                    severity="ERROR" if not passed else "INFO",
                    message=f"Column '{col}' all values within range [{min_v}, {max_v}]" if passed else f"Column '{col}' has {violations} values outside [{min_v}, {max_v}]",
                    details={"violations": violations, "min": min_v, "max": max_v}
                ))

            elif rtype == "regex":
                pattern = rule.get("pattern", ".*")
                compiled = re.compile(pattern)
                str_series = df[col].dropna().astype(str)
                non_matching = int((~str_series.str.match(compiled)).sum())
                passed = non_matching == 0
                results.append(QualityCheckResult(
                    check_name=f"regex_{col}",
                    passed=passed,
                    severity="ERROR" if not passed else "INFO",
                    message=f"Column '{col}' matches regex '{pattern}'" if passed else f"Column '{col}' has {non_matching} values failing regex '{pattern}'",
                    details={"failing_rows": non_matching, "pattern": pattern}
                ))

        total_checks = len(results)
        passed_checks = sum(1 for r in results if r.passed)
        failed_checks = total_checks - passed_checks
        overall_pass = failed_checks == 0
        quality_score = round((passed_checks / max(1, total_checks)) * 100.0, 2)

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Store as first-class DataOS QualityReport Object
        return DataObject(
            type=ObjectType.QUALITY_REPORT.value,
            schema="quality_report.v1",
            properties={
                "target_object_id": target_object_id,
                "overall_pass": overall_pass,
                "quality_score": quality_score,
                "total_checks": total_checks,
                "passed_checks": passed_checks,
                "failed_checks": failed_checks,
                "evaluated_at": now
            },
            content={
                "checks": [r.to_dict() for r in results]
            },
            source="dataos://engine/quality"
        )

    @classmethod
    def detect_drift(cls, baseline_df: pd.DataFrame, current_df: pd.DataFrame, column: str) -> Dict[str, Any]:
        """Detect statistical distribution drift using Kolmogorov-Smirnov test."""
        if column not in baseline_df.columns or column not in current_df.columns:
            return {"error": f"Column '{column}' missing in baseline or current dataset"}

        s1 = baseline_df[column].dropna().astype(float)
        s2 = current_df[column].dropna().astype(float)

        if len(s1) < 5 or len(s2) < 5:
            return {"error": "Insufficient sample size for Kolmogorov-Smirnov test"}

        ks_stat, p_value = stats.ks_2samp(s1, s2)
        drift_detected = bool(p_value < 0.05)

        return {
            "test": "Kolmogorov_Smirnov_2Sample",
            "column": column,
            "ks_statistic": round(float(ks_stat), 6),
            "p_value": round(float(p_value), 8),
            "drift_detected": drift_detected,
            "baseline_mean": round(float(s1.mean()), 4),
            "current_mean": round(float(s2.mean()), 4),
            "message": f"Statistical drift detected in column '{column}' (p={round(p_value, 4)})" if drift_detected else f"No significant drift in column '{column}'"
        }
