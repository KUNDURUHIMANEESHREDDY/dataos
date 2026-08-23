"""
Dynamic Schema System for DataOS.
Supports primitive types, nested structures, references, constraints,
versioning, backward compatibility, and migrations (Rule #3, Rule #12).
"""

from __future__ import annotations
import uuid
import datetime
from typing import Dict, Any, Optional, List, Union
from dataclasses import dataclass, field, asdict
from enum import Enum


class DataType(str, Enum):
    """Supported primitive and complex data types."""
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    DURATION = "duration"
    URL = "url"
    BINARY = "binary"
    JSON = "json"
    ARRAY = "array"
    OBJECT = "object"
    REFERENCE = "reference"
    ANY = "any"


@dataclass
class FieldConstraint:
    """Validation constraints for a schema field."""
    required: bool = False
    nullable: bool = True
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    regex_pattern: Optional[str] = None
    enum_values: Optional[List[Any]] = None
    unique: bool = False
    reference_type: Optional[str] = None  # Expected target ObjectType if DataType.REFERENCE

    def to_dict(self) -> Dict[str, Any]:
        """Serialize constraints to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> FieldConstraint:
        """Construct constraints from dictionary."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class FieldDefinition:
    """Definition of a single field in a schema."""
    name: str
    data_type: str = DataType.STRING.value
    description: str = ""
    default_value: Optional[Any] = None
    constraints: FieldConstraint = field(default_factory=FieldConstraint)
    item_type: Optional[str] = None  # If data_type == 'array'
    nested_fields: Optional[List[FieldDefinition]] = None  # If data_type == 'object'
    computed_expression: Optional[str] = None

    def __post_init__(self):
        if isinstance(self.data_type, DataType):
            self.data_type = self.data_type.value
        if isinstance(self.constraints, dict):
            self.constraints = FieldConstraint.from_dict(self.constraints)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize field definition to dictionary."""
        d = {
            "name": self.name,
            "data_type": self.data_type,
            "description": self.description,
            "default_value": self.default_value,
            "constraints": self.constraints.to_dict(),
            "item_type": self.item_type,
            "computed_expression": self.computed_expression,
        }
        if self.nested_fields:
            d["nested_fields"] = [f.to_dict() for f in self.nested_fields]
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> FieldDefinition:
        """Construct field definition from dictionary."""
        d = dict(data)
        if "nested_fields" in d and d["nested_fields"]:
            d["nested_fields"] = [FieldDefinition.from_dict(f) for f in d["nested_fields"]]
        if "constraints" in d and isinstance(d["constraints"], dict):
            d["constraints"] = FieldConstraint.from_dict(d["constraints"])
        return cls(**d)


@dataclass
class Schema:
    """Dynamic schema definition for DataOS objects."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "generic_schema"
    version: int = 1
    description: str = ""
    target_object_type: str = "document"
    fields: Dict[str, FieldDefinition] = field(default_factory=dict)
    strict: bool = False  # If True, unknown fields are rejected
    parent_schema_id: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_field(self, field_def: FieldDefinition) -> Schema:
        """Add a field definition to the schema."""
        self.fields[field_def.name] = field_def
        return self

    def check_backward_compatibility(self, old_schema: Schema) -> Dict[str, Any]:
        """
        Check backward compatibility between old_schema and self (Rule #3, #12).
        Breaking changes:
        - Removing a required field
        - Changing field data type to incompatible type
        - Adding a new required field with no default value
        """
        breaking_changes = []
        non_breaking_changes = []

        # Check removed fields
        for old_fname, old_fdef in old_schema.fields.items():
            if old_fname not in self.fields:
                if old_fdef.constraints.required:
                    breaking_changes.append(f"Required field '{old_fname}' was removed.")
                else:
                    non_breaking_changes.append(f"Optional field '{old_fname}' was removed.")
            else:
                new_fdef = self.fields[old_fname]
                if new_fdef.data_type != old_fdef.data_type and old_fdef.data_type != DataType.ANY.value:
                    breaking_changes.append(
                        f"Field '{old_fname}' type changed from {old_fdef.data_type} to {new_fdef.data_type}."
                    )

        # Check added fields
        for new_fname, new_fdef in self.fields.items():
            if new_fname not in old_schema.fields:
                if new_fdef.constraints.required and new_fdef.default_value is None:
                    breaking_changes.append(f"New required field '{new_fname}' added without default value.")
                else:
                    non_breaking_changes.append(f"New field '{new_fname}' added.")

        is_compatible = len(breaking_changes) == 0
        return {
            "compatible": is_compatible,
            "breaking_changes": breaking_changes,
            "non_breaking_changes": non_breaking_changes,
            "compatibility_mode": "full" if is_compatible else "breaking"
        }

    def to_dict(self) -> Dict[str, Any]:
        """Serialize schema to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "target_object_type": self.target_object_type,
            "fields": {k: v.to_dict() for k, v in self.fields.items()},
            "strict": self.strict,
            "parent_schema_id": self.parent_schema_id,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Schema:
        """Construct schema from dictionary."""
        d = dict(data)
        if "fields" in d and isinstance(d["fields"], dict):
            d["fields"] = {k: FieldDefinition.from_dict(v) for k, v in d["fields"].items()}
        return cls(**d)
