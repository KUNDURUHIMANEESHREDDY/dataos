"""
Abstract Storage Interface for DataOS (Rule #30).
Pluggable backend for persistent state and blob storage.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Dict, Any, List, Optional

if TYPE_CHECKING:
    from core.object.model import DataObject
    from core.relation.model import Relationship
    from core.schema.model import Schema
    from core.provenance.model import ProvenanceEvent


class StorageBackend(ABC):
    """Abstract interface for DataOS persistent metadata and relational store."""

    @abstractmethod
    def save_object(self, obj: DataObject) -> DataObject:
        """Save or update a DataObject."""
        pass

    @abstractmethod
    def get_object(self, object_id: str) -> Optional[DataObject]:
        """Retrieve a DataObject by ID."""
        pass

    @abstractmethod
    def list_objects(
        self,
        object_type: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[DataObject]:
        """List objects with optional filtering."""
        pass

    def count_objects(
        self,
        object_type: Optional[str] = None,
        source: Optional[str] = None,
    ) -> int:
        """Count matching objects. Database backends should override with COUNT(*).

        The paginated fallback keeps third-party StorageBackend implementations
        compatible while avoiding an unbounded single list request.
        """
        total = 0
        offset = 0
        page_size = 500
        while True:
            page = self.list_objects(
                object_type=object_type,
                source=source,
                limit=page_size,
                offset=offset,
            )
            total += len(page)
            if len(page) < page_size:
                return total
            offset += len(page)

    @abstractmethod
    def delete_object(self, object_id: str, soft: bool = True) -> bool:
        """Delete an object (soft by default to preserve provenance)."""
        pass

    @abstractmethod
    def save_relationship(self, rel: Relationship) -> Relationship:
        """Save or update a Relationship."""
        pass

    @abstractmethod
    def get_relationship(self, relation_id: str) -> Optional[Relationship]:
        """Get relationship by ID."""
        pass

    @abstractmethod
    def list_relationships(
        self,
        source_id: Optional[str] = None,
        target_id: Optional[str] = None,
        relation_type: Optional[str] = None,
        min_confidence: float = 0.0,
        limit: int = 1000,
        offset: int = 0
    ) -> List[Relationship]:
        """List relationships matching criteria."""
        pass

    def count_relationships(
        self,
        source_id: Optional[str] = None,
        target_id: Optional[str] = None,
        relation_type: Optional[str] = None,
        min_confidence: float = 0.0,
    ) -> int:
        """Count active matching relationships using bounded pages by default.

        Storage backends should override this with COUNT(*) for efficient exact
        totals. The fallback requires list_relationships to support offset.
        """
        total = 0
        offset = 0
        page_size = 500
        while True:
            page = self.list_relationships(
                source_id=source_id,
                target_id=target_id,
                relation_type=relation_type,
                min_confidence=min_confidence,
                limit=page_size,
                offset=offset,
            )
            total += len(page)
            if len(page) < page_size:
                return total
            offset += len(page)

    @abstractmethod
    def delete_relationship(self, relation_id: str, soft: bool = True) -> bool:
        """Delete a relationship."""
        pass

    @abstractmethod
    def save_schema(self, schema: Schema) -> Schema:
        """Save a Schema definition."""
        pass

    @abstractmethod
    def get_schema(self, schema_id_or_name: str) -> Optional[Schema]:
        """Get a Schema by ID or name."""
        pass

    @abstractmethod
    def list_schemas(self) -> List[Schema]:
        """List all registered schemas."""
        pass

    @abstractmethod
    def record_provenance_event(self, event: ProvenanceEvent) -> ProvenanceEvent:
        """Record an immutable provenance event."""
        pass

    @abstractmethod
    def get_provenance_events(self, target_object_id: str, limit: int = 100) -> List[ProvenanceEvent]:
        """Get provenance events for an object."""
        pass

    @abstractmethod
    def get_version_history(self, object_id: str) -> List[Dict[str, Any]]:
        """Get complete version history snapshots for an entity."""
        pass
