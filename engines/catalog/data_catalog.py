"""
Data Catalog for DataOS (Rule #37).
Auto-discovers, maintains, and organizes metadata for datasets, tables, columns, and pipelines.
Supports search, lineage, and freshness tracking.
"""

from __future__ import annotations
import datetime
import uuid
from typing import Dict, Any, List, Optional
from enum import Enum


class CatalogEntryType(str, Enum):
    """Types of entries tracked in the data catalog."""
    DATASET = "dataset"
    TABLE = "table"
    COLUMN = "column"
    PIPELINE = "pipeline"
    DASHBOARD = "dashboard"


class CatalogEntry:
    """A single metadata entry in the catalog."""

    def __init__(
        self,
        entry_id: str,
        entry_type: CatalogEntryType,
        name: str,
        owner: str = "",
        description: str = "",
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.entry_id = entry_id or str(uuid.uuid4())[:12]
        self.entry_type = entry_type
        self.name = name
        self.owner = owner
        self.description = description
        self.tags = tags or []
        self.metadata = metadata or {}
        self.created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.updated_at = self.created_at
        self.last_profiled_at: Optional[str] = None
        self.freshness_status: str = "unknown"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the catalog entry to a dictionary."""
        return {
            "entry_id": self.entry_id,
            "entry_type": self.entry_type.value,
            "name": self.name,
            "owner": self.owner,
            "description": self.description,
            "tags": self.tags.copy(),
            "metadata": self.metadata.copy(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_profiled_at": self.last_profiled_at,
            "freshness_status": self.freshness_status,
        }


class DataCatalog:
    """Central data catalog with auto-maintenance."""

    def __init__(self):
        self._entries: Dict[str, CatalogEntry] = {}
        self._lineage: Dict[str, List[str]] = {}  # entry_id -> [upstream_ids]
        self._search_index: Dict[str, set] = {}  # tag -> {entry_ids}

    def add_entry(
        self,
        entry_type: CatalogEntryType,
        name: str,
        owner: str = "",
        description: str = "",
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        parent_id: Optional[str] = None,
    ) -> CatalogEntry:
        """Add a new entry to the catalog."""
        entry = CatalogEntry(
            entry_id=str(uuid.uuid4())[:12],
            entry_type=entry_type,
            name=name,
            owner=owner,
            description=description,
            tags=tags or [],
            metadata=metadata or {},
        )
        self._entries[entry.entry_id] = entry
        # Update search index
        for tag in entry.tags:
            if tag not in self._search_index:
                self._search_index[tag] = set()
            self._search_index[tag].add(entry.entry_id)
        return entry

    def get_entry(self, entry_id: str) -> Optional[CatalogEntry]:
        """Retrieve a catalog entry by its ID."""
        return self._entries.get(entry_id)

    def update_entry(self, entry_id: str, **kwargs) -> bool:
        """Update fields of an existing catalog entry."""
        entry = self._entries.get(entry_id)
        if not entry:
            return False
        for key, val in kwargs.items():
            if key == "tags":
                # Remove old tags from index
                for old_tag in entry.tags:
                    if old_tag in self._search_index:
                        self._search_index[old_tag].discard(entry_id)
                entry.tags = val
                # Add new tags to index
                for new_tag in val:
                    if new_tag not in self._search_index:
                        self._search_index[new_tag] = set()
                    self._search_index[new_tag].add(entry_id)
            elif hasattr(entry, key):
                setattr(entry, key, val)
        entry.updated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        return True

    def delete_entry(self, entry_id: str) -> bool:
        """Remove a catalog entry and clean up its index references."""
        entry = self._entries.pop(entry_id, None)
        if entry:
            for tag in entry.tags:
                if tag in self._search_index:
                    self._search_index[tag].discard(entry_id)
            self._lineage.pop(entry_id, None)
            return True
        return False

    def search(
        self,
        query: str = "",
        entry_type: Optional[CatalogEntryType] = None,
        tags: Optional[List[str]] = None,
        owner: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Search catalog entries by name, type, tags, or owner."""
        results = list(self._entries.values())

        if query:
            query_lower = query.lower()
            results = [e for e in results if query_lower in e.name.lower() or query_lower in e.description.lower()]
        if entry_type:
            results = [e for e in results if e.entry_type == entry_type]
        if tags:
            tag_set = set(tags)
            results = [e for e in results if tag_set.intersection(set(e.tags))]
        if owner:
            results = [e for e in results if e.owner == owner]

        return [e.to_dict() for e in results[:limit]]

    def add_lineage(self, downstream_id: str, upstream_id: str) -> None:
        """Record a lineage edge from upstream to downstream entry."""
        if downstream_id not in self._lineage:
            self._lineage[downstream_id] = []
        if upstream_id not in self._lineage[downstream_id]:
            self._lineage[downstream_id].append(upstream_id)

    def get_upstream(self, entry_id: str) -> List[Dict[str, Any]]:
        """Get all upstream dependencies of an entry."""
        upstream_ids = self._lineage.get(entry_id, [])
        return [self._entries[uid].to_dict() for uid in upstream_ids if uid in self._entries]

    def get_downstream(self, entry_id: str) -> List[Dict[str, Any]]:
        """Get all downstream dependents of an entry."""
        downstream = [eid for eid, ups in self._lineage.items() if entry_id in ups]
        return [self._entries[did].to_dict() for did in downstream if did in self._entries]

    def auto_profile(self, entry_id: str, profile_data: Dict[str, Any]) -> bool:
        """Auto-profile an entry and update metadata."""
        entry = self._entries.get(entry_id)
        if not entry:
            return False
        entry.metadata["profile"] = profile_data
        entry.last_profiled_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        return True

    def update_freshness(self, entry_id: str, last_updated: str) -> None:
        """Update freshness status based on last_updated timestamp."""
        entry = self._entries.get(entry_id)
        if not entry:
            return
        try:
            dt = datetime.datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
            age_hours = (datetime.datetime.now(datetime.timezone.utc) - dt).total_seconds() / 3600
            if age_hours < 24:
                entry.freshness_status = "fresh"
            elif age_hours < 168:
                entry.freshness_status = "stale"
            else:
                entry.freshness_status = "expired"
            entry.metadata["last_data_update"] = last_updated
        except (ValueError, TypeError):
            entry.freshness_status = "unknown"

    def get_stats(self) -> Dict[str, Any]:
        """Return summary statistics for the catalog."""
        by_type = {}
        for e in self._entries.values():
            t = e.entry_type.value
            by_type[t] = by_type.get(t, 0) + 1
        by_freshness = {}
        for e in self._entries.values():
            f = e.freshness_status
            by_freshness[f] = by_freshness.get(f, 0) + 1
        return {
            "total_entries": len(self._entries),
            "by_type": by_type,
            "by_freshness": by_freshness,
            "total_lineage_edges": sum(len(v) for v in self._lineage.values()),
        }

    def export_metadata(self) -> List[Dict[str, Any]]:
        """Export all catalog entries as a list of dictionaries."""
        return [e.to_dict() for e in self._entries.values()]
