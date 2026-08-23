"""
Schema Validator for DataOS Objects.
Validates properties, content, types, and constraints against defined Schemas.
"""

from __future__ import annotations
import re
import datetime
from typing import Dict, Any, List, Tuple, Optional
from .model import Schema, FieldDefinition, DataType, FieldConstraint


class ValidationResult:
    """Result of schema validation containing validity status, errors, and warnings."""

    def __init__(self, is_valid: bool, errors: Optional[List[str]] = None, warnings: Optional[List[str]] = None):
        self.is_valid = is_valid
        self.errors = errors or []
        self.warnings = warnings or []

    def to_dict(self) -> Dict[str, Any]:
        """Serialize validation result to dictionary."""
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
        }


class SchemaValidator:
    """Validates DataObjects or raw property dictionaries against Schemas."""

    @classmethod
    def validate(cls, schema: Schema, data: Dict[str, Any]) -> ValidationResult:
        errors: List[str] = []
        warnings: List[str] = []

        # Check required fields
        for field_name, field_def in schema.fields.items():
            val = data.get(field_name)
            
            # Check required & nullability
            if val is None:
                if field_def.constraints.required:
                    errors.append(f"Missing required field: '{field_name}'")
                elif not field_def.constraints.nullable and field_name in data:
                    errors.append(f"Field '{field_name}' cannot be null")
                continue

            # Validate type and constraints
            cls._validate_field_value(field_name, field_def, val, errors, warnings)

        # Check strict mode for unknown fields
        if schema.strict:
            for key in data.keys():
                if key not in schema.fields:
                    errors.append(f"Unknown field '{key}' not permitted under strict schema '{schema.name}'")

        return ValidationResult(is_valid=len(errors) == 0, errors=errors, warnings=warnings)

    @classmethod
    def _validate_field_value(
        cls,
        field_name: str,
        field_def: FieldDefinition,
        val: Any,
        errors: List[str],
        warnings: List[str]
    ):
        dt = field_def.data_type
        c = field_def.constraints

        # Type checks
        if dt == DataType.STRING.value:
            if not isinstance(val, str):
                errors.append(f"Field '{field_name}' expected string, got {type(val).__name__}")
                return
            if c.min_length is not None and len(val) < c.min_length:
                errors.append(f"Field '{field_name}' length {len(val)} < min_length {c.min_length}")
            if c.max_length is not None and len(val) > c.max_length:
                errors.append(f"Field '{field_name}' length {len(val)} > max_length {c.max_length}")
            if c.regex_pattern:
                if not re.match(c.regex_pattern, val):
                    errors.append(f"Field '{field_name}' does not match regex pattern '{c.regex_pattern}'")
            if c.enum_values is not None and val not in c.enum_values:
                errors.append(f"Field '{field_name}' value '{val}' not in allowed enum values: {c.enum_values}")

        elif dt == DataType.INTEGER.value:
            if not isinstance(val, int) or isinstance(val, bool):
                errors.append(f"Field '{field_name}' expected integer, got {type(val).__name__}")
                return
            if c.min_value is not None and val < c.min_value:
                errors.append(f"Field '{field_name}' value {val} < min_value {c.min_value}")
            if c.max_value is not None and val > c.max_value:
                errors.append(f"Field '{field_name}' value {val} > max_value {c.max_value}")

        elif dt == DataType.FLOAT.value:
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                errors.append(f"Field '{field_name}' expected float/numeric, got {type(val).__name__}")
                return
            if c.min_value is not None and val < c.min_value:
                errors.append(f"Field '{field_name}' value {val} < min_value {c.min_value}")
            if c.max_value is not None and val > c.max_value:
                errors.append(f"Field '{field_name}' value {val} > max_value {c.max_value}")

        elif dt == DataType.BOOLEAN.value:
            if not isinstance(val, bool):
                errors.append(f"Field '{field_name}' expected boolean, got {type(val).__name__}")

        elif dt == DataType.ARRAY.value:
            if not isinstance(val, list):
                errors.append(f"Field '{field_name}' expected array/list, got {type(val).__name__}")
            elif field_def.item_type:
                # Validate item types if specified
                for idx, item in enumerate(val):
                    if field_def.item_type == DataType.STRING.value and not isinstance(item, str):
                        errors.append(f"Field '{field_name}[{idx}]' expected string item")
                    elif field_def.item_type in (DataType.INTEGER.value, DataType.FLOAT.value) and not isinstance(item, (int, float)):
                        errors.append(f"Field '{field_name}[{idx}]' expected numeric item")

        elif dt == DataType.OBJECT.value or dt == DataType.JSON.value:
            if not isinstance(val, (dict, list)):
                errors.append(f"Field '{field_name}' expected object/json, got {type(val).__name__}")

        elif dt == DataType.DATE.value or dt == DataType.DATETIME.value:
            if isinstance(val, str):
                try:
                    datetime.datetime.fromisoformat(val.replace("Z", "+00:00"))
                except ValueError:
                    errors.append(f"Field '{field_name}' expected valid ISO date/datetime string, got '{val}'")
            elif not isinstance(val, (datetime.date, datetime.datetime)):
                errors.append(f"Field '{field_name}' expected date/datetime object or string")
