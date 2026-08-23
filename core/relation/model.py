"""
First-Class Relationship Model for DataOS (Rule #4, Rule #5).
Explicitly connects objects with confidence scores, provenance, and supporting evidence.
"""

from __future__ import annotations
import uuid
import datetime
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field, asdict
from .types import RelationType, RelationTypeRegistry


@dataclass
class Relationship:
    """
    First-class edge in the Universal Relationship Graph.
    
    Fields:
    - id: Unique edge identifier
    - source: ID of the source DataObject
    - target: ID of the target DataObject
    - relation_type: Type of the relationship (extensible)
    - metadata: Dynamic relationship metadata (e.g. matched columns, line numbers, weights)
    - confidence: Confidence score between 0.0 and 1.0
    - provenance: Traceability of how the relationship was formed (manual, structural, semantic, code AST, doc citation)
    - evidence: Supporting evidence payload (snippets, shared IDs, matched tokens)
    - created_at: Timestamp of establishment
    - updated_at: Timestamp of last update
    - deleted_at: Soft deletion marker
    """
    source: str
    target: str
    relation_type: str = RelationType.REFERENCES.value
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    metadata: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    provenance: Dict[str, Any] = field(default_factory=dict)
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    deleted_at: Optional[str] = None

    def __post_init__(self):
        if isinstance(self.relation_type, RelationType):
            self.relation_type = self.relation_type.value
        # Clamp confidence between 0.0 and 1.0
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
        if not self.provenance:
            self.provenance = {
                "established_by": "dataos",
                "method": "explicit",
                "timestamp": self.created_at
            }

    def add_evidence(self, signal_type: str, description: str, score: float, data: Optional[Dict[str, Any]] = None):
        """Add supporting evidence to relationship."""
        self.evidence.append({
            "signal": signal_type,
            "description": description,
            "score": score,
            "data": data or {},
            "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
        })
        self.updated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize relationship to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Relationship:
        """Construct relationship from dictionary."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
