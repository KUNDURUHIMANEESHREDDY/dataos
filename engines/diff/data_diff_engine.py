"""
Data Diff Engine for DataOS (Rule #24).
Compares two datasets to detect structural and content differences.
Supports row-level, column-level, schema-level, and summary diffs.
"""

from __future__ import annotations
import datetime
from typing import Dict, Any, List, Optional, Set, Tuple
from enum import Enum


class DiffType(str, Enum):
    """Types of differences detected between datasets."""
    ROW_ADDED = "row_added"
    ROW_REMOVED = "row_removed"
    ROW_MODIFIED = "row_modified"
    COLUMN_ADDED = "column_added"
    COLUMN_REMOVED = "column_removed"
    COLUMN_RENAMED = "column_renamed"
    VALUE_CHANGED = "value_changed"


class DiffSeverity(str, Enum):
    """Severity levels for diff results."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class DiffResult:
    """Single diff entry."""

    def __init__(
        self,
        diff_type: DiffType,
        target: str,
        old_value: Any = None,
        new_value: Any = None,
        row_id: Optional[str] = None,
        severity: DiffSeverity = DiffSeverity.INFO,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.diff_type = diff_type
        self.target = target
        self.old_value = old_value
        self.new_value = new_value
        self.row_id = row_id
        self.severity = severity
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the diff result to a dictionary."""
        return {
            "diff_type": self.diff_type.value,
            "target": self.target,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "row_id": self.row_id,
            "severity": self.severity.value,
            "details": self.details,
        }


class DiffReport:
    """Aggregated diff report comparing two datasets."""

    def __init__(self, source_name: str, target_name: str):
        self.source_name = source_name
        self.target_name = target_name
        self.results: List[DiffResult] = []
        self.diffed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    def add(self, result: DiffResult) -> None:
        """Add a diff result to the report."""
        self.results.append(result)

    def summary(self) -> Dict[str, Any]:
        """Generate a summary of all diffs in the report."""
        by_type = {}
        for r in self.results:
            t = r.diff_type.value
            by_type[t] = by_type.get(t, 0) + 1
        by_severity = {}
        for r in self.results:
            s = r.severity.value
            by_severity[s] = by_severity.get(s, 0) + 1
        return {
            "source": self.source_name,
            "target": self.target_name,
            "total_diffs": len(self.results),
            "by_type": by_type,
            "by_severity": by_severity,
            "diffed_at": self.diffed_at,
        }

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the full diff report to a dictionary."""
        s = self.summary()
        s["results"] = [r.to_dict() for r in self.results]
        return s


class DataDiffEngine:
    """Engine for comparing two datasets."""

    def __init__(self, key_column: str = "id"):
        self.key_column = key_column

    def diff_schemas(self, source: Dict[str, Any], target: Dict[str, Any]) -> DiffReport:
        """Compare the schemas (column names) of two datasets."""
        report = DiffReport("source_schema", "target_schema")
        source_cols = set(source.keys()) if isinstance(source, dict) else set(source[0].keys()) if source and isinstance(source[0], dict) else set()
        target_cols = set(target.keys()) if isinstance(target, dict) else set(target[0].keys()) if target and isinstance(target[0], dict) else set()

        for col in source_cols - target_cols:
            report.add(DiffResult(DiffType.COLUMN_REMOVED, col, severity=DiffSeverity.WARNING))
        for col in target_cols - source_cols:
            report.add(DiffResult(DiffType.COLUMN_ADDED, col, severity=DiffSeverity.INFO))
        return report

    def diff_rows(
        self,
        source: List[Dict[str, Any]],
        target: List[Dict[str, Any]],
        primary_key: Optional[str] = None,
    ) -> DiffReport:
        """Compare row-level content between two datasets."""
        pk = primary_key or self.key_column
        report = DiffReport("source_data", "target_data")

        source_map = {str(row.get(pk, i)): row for i, row in enumerate(source)}
        target_map = {str(row.get(pk, i)): row for i, row in enumerate(target)}

        source_keys = set(source_map.keys())
        target_keys = set(target_map.keys())

        for key in source_keys - target_keys:
            report.add(DiffResult(DiffType.ROW_REMOVED, pk, old_value=key, row_id=key, severity=DiffSeverity.WARNING))
        for key in target_keys - source_keys:
            report.add(DiffResult(DiffType.ROW_ADDED, pk, new_value=key, row_id=key, severity=DiffSeverity.INFO))

        for key in source_keys & target_keys:
            src_row = source_map[key]
            tgt_row = target_map[key]
            all_cols = set(src_row.keys()) | set(tgt_row.keys())
            for col in all_cols:
                if col == pk:
                    continue
                src_val = src_row.get(col)
                tgt_val = tgt_row.get(col)
                if src_val != tgt_val:
                    report.add(DiffResult(
                        DiffType.VALUE_CHANGED,
                        col,
                        old_value=src_val,
                        new_value=tgt_val,
                        row_id=key,
                        severity=DiffSeverity.INFO,
                    ))
        return report

    def diff_summaries(
        self,
        source: List[Dict[str, Any]],
        target: List[Dict[str, Any]],
    ) -> DiffReport:
        """Compare summary statistics of two datasets."""
        report = DiffReport("source_summary", "target_summary")

        report.add(DiffResult(DiffType.ROW_ADDED, "row_count", old_value=len(source), new_value=len(target),
                              severity=DiffSeverity.INFO))

        if source:
            source_cols = set(source[0].keys())
        else:
            source_cols = set()
        if target:
            target_cols = set(target[0].keys())
        else:
            target_cols = set()

        report.add(DiffResult(DiffType.COLUMN_REMOVED, "column_count", old_value=len(source_cols), new_value=len(target_cols),
                              severity=DiffSeverity.INFO if len(source_cols) == len(target_cols) else DiffSeverity.WARNING))
        return report

    def full_diff(
        self,
        source: List[Dict[str, Any]],
        target: List[Dict[str, Any]],
        primary_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run all diff types and return a combined report."""
        schema_diff = self.diff_schemas(source, target)
        row_diff = self.diff_rows(source, target, primary_key)
        summary_diff = self.diff_summaries(source, target)

        all_results = schema_diff.results + row_diff.results + summary_diff.results
        combined = DiffReport("source_full", "target_full")
        combined.results = all_results
        return combined.to_dict()

    def diff_columns(
        self,
        source: List[Dict[str, Any]],
        target: List[Dict[str, Any]],
        column: str,
    ) -> Dict[str, Any]:
        """Compare a specific column across two datasets."""
        source_vals = [row.get(column) for row in source]
        target_vals = [row.get(column) for row in target]
        source_set = set(source_vals)
        target_set = set(target_vals)
        return {
            "column": column,
            "source_count": len(source_vals),
            "target_count": len(target_vals),
            "source_unique": len(source_set),
            "target_unique": len(target_set),
            "values_added": list(target_set - source_set),
            "values_removed": list(source_set - target_set),
        }


class DiffEngineManager:
    """Manages multiple diff engines for different datasets."""

    def __init__(self):
        self._engines: Dict[str, DataDiffEngine] = {}
        self._history: List[Dict[str, Any]] = []

    def register_dataset(self, dataset_id: str, key_column: str = "id") -> DataDiffEngine:
        """Register a diff engine for a specific dataset."""
        engine = DataDiffEngine(key_column=key_column)
        self._engines[dataset_id] = engine
        return engine

    def diff(self, source_id: str, target_id: str, source_data: List[Dict], target_data: List[Dict], primary_key: Optional[str] = None) -> Dict[str, Any]:
        """Run a full diff between two datasets and record the result."""
        engine = self._engines.get(source_id) or self._engines.get(target_id) or DataDiffEngine()
        result = engine.full_diff(source_data, target_data, primary_key)
        result["source_id"] = source_id
        result["target_id"] = target_id
        self._history.append(result)
        return result

    def get_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Return recent diff history."""
        return self._history[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        """Return diff engine usage statistics."""
        return {
            "registered_engines": len(self._engines),
            "total_diffs": len(self._history),
        }
