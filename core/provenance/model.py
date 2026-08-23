"""
Provenance & Traceability Models for DataOS (Rule #6, Rule #7).
Every derived result must be fully traceable to its inputs, transformations, and execution context.
Supports OpenLineage standard representations.
"""

from __future__ import annotations
import uuid
import datetime
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field, asdict
from enum import Enum


class ProvenanceEventType(str, Enum):
    INGESTION = "ingestion"
    TRANSFORMATION = "transformation"
    QUERY_EXECUTION = "query_execution"
    AI_INFERENCE = "ai_inference"
    STATISTICAL_COMPUTE = "statistical_compute"
    RELATIONSHIP_DISCOVERED = "relationship_discovered"
    SCHEMA_MIGRATION = "schema_migration"
    QUALITY_CHECK = "quality_check"
    WORKFLOW_STEP = "workflow_step"
    MANUAL_EDIT = "manual_edit"


@dataclass
class ProvenanceRecord:
    """Complete provenance envelope for an object, calculation, or query."""
    inputs: List[Dict[str, Any]] = field(default_factory=list)  # [{object_id, version, content_hash, role}]
    transformations: List[Dict[str, Any]] = field(default_factory=list)  # [{operation, code, steps, engine}]
    execution_context: Dict[str, Any] = field(default_factory=dict)  # {runtime, env, timestamp, agent/user, host}
    tools_used: List[Dict[str, Any]] = field(default_factory=list)  # [{name, version, parameters}]
    parameters: Dict[str, Any] = field(default_factory=dict)
    timestamps: Dict[str, str] = field(default_factory=dict)
    versions: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize record to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ProvenanceRecord:
        """Construct record from dictionary."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ProvenanceEvent:
    """Individual auditable provenance event logged to the system."""
    target_object_id: str
    event_type: str = ProvenanceEventType.TRANSFORMATION.value
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    description: str = ""
    inputs: List[Dict[str, Any]] = field(default_factory=list)
    outputs: List[Dict[str, Any]] = field(default_factory=list)
    tools_used: List[Dict[str, Any]] = field(default_factory=list)
    parameters: Dict[str, Any] = field(default_factory=dict)
    execution_context: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())

    def __post_init__(self):
        if isinstance(self.event_type, ProvenanceEventType):
            self.event_type = self.event_type.value

    def to_openlineage_run_event(self) -> Dict[str, Any]:
        """Convert provenance event to OpenLineage compatible RunEvent JSON."""
        return {
            "eventType": "COMPLETE",
            "eventTime": self.created_at,
            "run": {
                "runId": self.id,
                "facets": {
                    "nominalTime": {"nominalStartTime": self.created_at},
                    "environment": self.execution_context,
                    "parameters": self.parameters
                }
            },
            "job": {
                "namespace": "dataos",
                "name": f"{self.event_type}_{self.target_object_id}"
            },
            "inputs": [
                {
                    "namespace": "dataos",
                    "name": inp.get("object_id", "unknown"),
                    "facets": {"version": inp.get("version", 1)}
                }
                for inp in self.inputs
            ],
            "outputs": [
                {
                    "namespace": "dataos",
                    "name": self.target_object_id,
                    "facets": {"type": self.event_type}
                }
            ],
            "producer": "https://github.com/dataos-universal"
        }

    def to_dict(self) -> Dict[str, Any]:
        """Serialize event to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ProvenanceEvent:
        """Construct event from dictionary."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
