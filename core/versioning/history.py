"""
Versioning & Snapshotting for DataOS (Rule #25).
Provides immutable history tracking and time-travel reconstruction.
"""

from __future__ import annotations
import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict


@dataclass
class VersionSnapshot:
    """Immutable point-in-time snapshot of an object or schema."""
    object_id: str
    version: int
    data_snapshot: Dict[str, Any]
    content_hash: str
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    created_by: str = "system"
    change_summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize snapshot to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> VersionSnapshot:
        """Construct snapshot from dictionary."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class VersionHistory:
    """Manages version lineage and snapshots for an entity."""
    def __init__(self, entity_id: str):
        """Initialize version history for an entity."""
        self.entity_id = entity_id
        self.snapshots: List[VersionSnapshot] = []

    def add_snapshot(
        self,
        version: int,
        data: Dict[str, Any],
        content_hash: str,
        created_by: str = "system",
        change_summary: str = ""
    ) -> VersionSnapshot:
        """Add a new version snapshot to the history."""
        snapshot = VersionSnapshot(
            object_id=self.entity_id,
            version=version,
            data_snapshot=data,
            content_hash=content_hash,
            created_by=created_by,
            change_summary=change_summary
        )
        self.snapshots.append(snapshot)
        return snapshot

    def get_version(self, version: int) -> Optional[VersionSnapshot]:
        """Get snapshot by version number."""
        for s in self.snapshots:
            if s.version == version:
                return s
        return None

    def get_latest(self) -> Optional[VersionSnapshot]:
        """Get the most recent snapshot."""
        return self.snapshots[-1] if self.snapshots else None

    def get_as_of(self, timestamp_iso: str) -> Optional[VersionSnapshot]:
        """Find the snapshot valid as of a specific point in time (Time-travel)."""
        valid_snapshots = [s for s in self.snapshots if s.created_at <= timestamp_iso]
        return valid_snapshots[-1] if valid_snapshots else (self.snapshots[0] if self.snapshots else None)

    def list_history(self) -> List[Dict[str, Any]]:
        """List all snapshots as dictionaries."""
        return [s.to_dict() for s in self.snapshots]
