"""
Universal Object Model for DataOS.
Conforms to the 11-field core specification with immutability,
version tracking, provenance tracing, and serialization support.
"""

from __future__ import annotations
import uuid
import datetime
import json
import hashlib
from typing import Dict, Any, Optional, List, Union
from dataclasses import dataclass, field, asdict
from enum import Enum


class ObjectType(str, Enum):
    """Domain-agnostic foundational object types."""
    FILE = "file"
    DOCUMENT = "document"
    DATASET = "dataset"
    TABLE = "table"
    COLUMN = "column"
    ROW = "row"
    QUERY = "query"
    NOTEBOOK = "notebook"
    CODE = "code"
    MEDIA = "media"
    CONCEPT = "concept"
    CLAIM = "claim"
    EVIDENCE = "evidence"
    MODEL = "model"
    AGENT = "agent"
    WORKFLOW = "workflow"
    METRIC = "metric"
    REPORT = "report"
    QUALITY_REPORT = "quality_report"
    SCHEMA = "schema"
    CONTRACT = "contract"
    CUSTOM = "custom"


@dataclass
class Timestamps:
    """Temporal markers for creation, update, deletion, and validity windows."""
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    deleted_at: Optional[str] = None
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Timestamps:
        """Construct from dictionary."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class DataObject:
    """
    Universal DataOS Object.
    
    11 core fields:
    - id: Unique persistent identifier (UUID or deterministic URN)
    - type: Domain-neutral categorization
    - schema: Schema reference or definition identifier
    - properties: Structured key-value properties
    - content: Primary content/payload (raw text, structured table data, AST, or binary ref)
    - relations: Local relationship indices and references
    - provenance: Origin and lineage metadata
    - permissions: Access control configuration
    - timestamps: Temporal markers (created, updated, deleted, validity)
    - version: Monotonically increasing version number
    - source: Origin source identifier
    - metadata: Extensible system and user metadata
    - indexes: Inverted index tags and search tokens
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: str = ObjectType.DOCUMENT.value
    schema: str = "generic.v1"
    properties: Dict[str, Any] = field(default_factory=dict)
    content: Any = field(default_factory=dict)
    relations: Dict[str, Any] = field(default_factory=dict)
    provenance: Dict[str, Any] = field(default_factory=dict)
    permissions: Dict[str, Any] = field(default_factory=lambda: {"owner": "system", "read": ["*"], "write": ["owner"]})
    timestamps: Timestamps = field(default_factory=Timestamps)
    version: int = 1
    source: str = "dataos://internal"
    metadata: Dict[str, Any] = field(default_factory=dict)
    indexes: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if isinstance(self.timestamps, dict):
            self.timestamps = Timestamps.from_dict(self.timestamps)
        if isinstance(self.type, ObjectType):
            self.type = self.type.value
        # Ensure default provenance exists
        if not self.provenance:
            self.provenance = {
                "created_by": "dataos",
                "creation_timestamp": self.timestamps.created_at,
                "input_sources": [self.source] if self.source else [],
                "transformations": []
            }
        # Compute content hash if applicable
        if "content_hash" not in self.metadata:
            self.metadata["content_hash"] = self.compute_hash()

    def compute_hash(self) -> str:
        """Compute deterministic SHA-256 hash of object content and properties."""
        payload = {
            "type": self.type,
            "schema": self.schema,
            "properties": self.properties,
            "content": self.content,
            "source": self.source,
            "version": self.version
        }
        serialized = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def create_new_version(
        self,
        new_properties: Optional[Dict[str, Any]] = None,
        new_content: Optional[Any] = None,
        transformation_desc: str = "Updated",
        agent_or_user: str = "system"
    ) -> DataObject:
        """Create a new version of this object while preserving provenance."""
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        merged_properties = dict(self.properties)
        if new_properties is not None:
            merged_properties.update(new_properties)
            
        merged_content = new_content if new_content is not None else self.content
        
        # Build updated provenance chain
        new_provenance = dict(self.provenance)
        transformations = list(new_provenance.get("transformations", []))
        transformations.append({
            "step": len(transformations) + 1,
            "previous_version": self.version,
            "action": transformation_desc,
            "executor": agent_or_user,
            "timestamp": now
        })
        new_provenance["transformations"] = transformations
        new_provenance["last_modified_by"] = agent_or_user
        new_provenance["last_modified_at"] = now

        new_timestamps = Timestamps(
            created_at=self.timestamps.created_at,
            updated_at=now,
            deleted_at=self.timestamps.deleted_at,
            valid_from=self.timestamps.valid_from,
            valid_to=self.timestamps.valid_to
        )

        return DataObject(
            id=self.id,
            type=self.type,
            schema=self.schema,
            properties=merged_properties,
            content=merged_content,
            relations=dict(self.relations),
            provenance=new_provenance,
            permissions=dict(self.permissions),
            timestamps=new_timestamps,
            version=self.version + 1,
            source=self.source,
            metadata=dict(self.metadata),
            indexes=dict(self.indexes)
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize object to dictionary."""
        return {
            "id": self.id,
            "type": self.type,
            "schema": self.schema,
            "properties": self.properties,
            "content": self.content,
            "relations": self.relations,
            "provenance": self.provenance,
            "permissions": self.permissions,
            "timestamps": self.timestamps.to_dict(),
            "version": self.version,
            "source": self.source,
            "metadata": self.metadata,
            "indexes": self.indexes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DataObject:
        """Construct object from dictionary."""
        d = dict(data)
        if "timestamps" in d and isinstance(d["timestamps"], dict):
            d["timestamps"] = Timestamps.from_dict(d["timestamps"])
        return cls(**d)
