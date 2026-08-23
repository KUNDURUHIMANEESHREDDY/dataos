"""
Schema Evolution Tracker for DataOS (Rule #14).
Tracks schema changes over time, detects breaking changes, and manages migrations.
"""

from __future__ import annotations
import datetime
import uuid
from typing import Dict, Any, List, Optional, Set
from enum import Enum


class SchemaChangeType(str, Enum):
    COLUMN_ADDED = "column_added"
    COLUMN_REMOVED = "column_removed"
    COLUMN_RENAMED = "column_renamed"
    TYPE_CHANGED = "type_changed"
    NULLABILITY_CHANGED = "nullability_changed"
    COLUMNS_REORDERED = "columns_reordered"


class ChangeImpact(str, Enum):
    NON_BREAKING = "non_breaking"
    POTENTIALLY_BREAKING = "potentially_breaking"
    BREAKING = "breaking"


class SchemaVersion:
    """A snapshot of a schema at a point in time."""

    def __init__(
        self,
        version_id: str,
        dataset_id: str,
        columns: Dict[str, str],
        description: str = "",
    ):
        self.version_id = version_id or str(uuid.uuid4())[:12]
        self.dataset_id = dataset_id
        self.columns = columns  # {column_name: type_string}
        self.description = description
        self.created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize schema version to dictionary."""
        return {
            "version_id": self.version_id,
            "dataset_id": self.dataset_id,
            "columns": self.columns.copy(),
            "description": self.description,
            "created_at": self.created_at,
        }


class SchemaChange:
    """A detected change between two schema versions."""

    def __init__(
        self,
        change_type: SchemaChangeType,
        column_name: str,
        old_value: Any = None,
        new_value: Any = None,
        impact: ChangeImpact = ChangeImpact.NON_BREAKING,
    ):
        self.change_type = change_type
        self.column_name = column_name
        self.old_value = old_value
        self.new_value = new_value
        self.impact = impact

    def to_dict(self) -> Dict[str, Any]:
        """Serialize schema change to dictionary."""
        return {
            "change_type": self.change_type.value,
            "column_name": self.column_name,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "impact": self.impact.value,
        }


class SchemaEvolutionTracker:
    """Tracks schema evolution for datasets."""

    def __init__(self):
        self._versions: Dict[str, List[SchemaVersion]] = {}  # dataset_id -> [versions]
        self._current: Dict[str, SchemaVersion] = {}  # dataset_id -> current

    def register(self, dataset_id: str, columns: Dict[str, str], description: str = "") -> SchemaVersion:
        """Register a new schema version for a dataset."""
        version = SchemaVersion(
            version_id=str(uuid.uuid4())[:12],
            dataset_id=dataset_id,
            columns=columns,
            description=description,
        )
        if dataset_id not in self._versions:
            self._versions[dataset_id] = []
        self._versions[dataset_id].append(version)
        self._current[dataset_id] = version
        return version

    def get_current(self, dataset_id: str) -> Optional[SchemaVersion]:
        """Get the current schema version for a dataset."""
        return self._current.get(dataset_id)

    def get_versions(self, dataset_id: str) -> List[Dict[str, Any]]:
        """Get all schema versions for a dataset as dictionaries."""
        versions = self._versions.get(dataset_id, [])
        return [v.to_dict() for v in versions]

    def detect_changes(self, dataset_id: str, new_columns: Dict[str, str]) -> List[SchemaChange]:
        """Compare new schema against current and return detected changes."""
        current = self._current.get(dataset_id)
        if not current:
            return []

        changes: List[SchemaChange] = []
        old_cols = current.columns
        new_cols = new_columns

        old_set = set(old_cols.keys())
        new_set = set(new_cols.keys())

        for col in new_set - old_set:
            changes.append(SchemaChange(SchemaChangeType.COLUMN_ADDED, col, new_value=new_cols[col], impact=ChangeImpact.NON_BREAKING))

        for col in old_set - new_set:
            changes.append(SchemaChange(SchemaChangeType.COLUMN_REMOVED, col, old_value=old_cols[col], impact=ChangeImpact.BREAKING))

        for col in old_set & new_set:
            if old_cols[col] != new_cols[col]:
                changes.append(SchemaChange(
                    SchemaChangeType.TYPE_CHANGED,
                    col,
                    old_value=old_cols[col],
                    new_value=new_cols[col],
                    impact=ChangeImpact.POTENTIALLY_BREAKING,
                ))
        return changes

    def apply_changes(self, dataset_id: str, new_columns: Dict[str, str], description: str = "") -> Dict[str, Any]:
        """Detect changes and create a new version. Returns change report."""
        changes = self.detect_changes(dataset_id, new_columns)
        version = self.register(dataset_id, new_columns, description)
        breaking = [c for c in changes if c.impact == ChangeImpact.BREAKING]
        return {
            "version_id": version.version_id,
            "changes": [c.to_dict() for c in changes],
            "total_changes": len(changes),
            "breaking_changes": len(breaking),
            "has_breaking": len(breaking) > 0,
        }

    def is_compatible(self, dataset_id: str, required_columns: Dict[str, str]) -> Dict[str, Any]:
        """Check if current schema is compatible with required schema."""
        current = self._current.get(dataset_id)
        if not current:
            return {"compatible": False, "reason": "No schema registered"}

        issues = []
        current_cols = current.columns
        for col, col_type in required_columns.items():
            if col not in current_cols:
                issues.append(f"Missing required column '{col}'")
            elif current_cols[col] != col_type:
                issues.append(f"Column '{col}' type mismatch: expected {col_type}, got {current_cols[col]}")

        return {
            "compatible": len(issues) == 0,
            "issues": issues,
            "current_version": current.version_id,
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get summary statistics of tracked schemas."""
        total_versions = sum(len(v) for v in self._versions.values())
        return {
            "datasets_tracked": len(self._versions),
            "total_versions": total_versions,
        }
