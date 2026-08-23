"""
Registry for user-defined and built-in object types.
Enables extending DataOS object types without core modifications (Rule #2).
"""

from typing import Dict, Any, Optional, List
from .model import ObjectType


class ObjectTypeRegistry:
    """Registry allowing dynamic registration of custom object types."""
    _types: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def initialize_defaults(cls):
        """Register built-in domain-agnostic types."""
        for obj_type in ObjectType:
            cls.register_type(
                type_name=obj_type.value,
                description=f"Built-in {obj_type.value} object type",
                is_system=True
            )

    @classmethod
    def register_type(
        cls,
        type_name: str,
        description: str = "",
        schema_ref: Optional[str] = None,
        is_system: bool = False,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Register a new object type dynamically."""
        type_clean = type_name.strip().lower()
        type_def = {
            "name": type_clean,
            "description": description,
            "schema_ref": schema_ref or f"{type_clean}.v1",
            "is_system": is_system,
            "metadata": metadata or {}
        }
        cls._types[type_clean] = type_def
        return type_def

    @classmethod
    def get_type(cls, type_name: str) -> Optional[Dict[str, Any]]:
        """Get type definition by name, or None if not found."""
        return cls._types.get(type_name.strip().lower())

    @classmethod
    def list_types(cls) -> List[Dict[str, Any]]:
        """List all registered type definitions."""
        if not cls._types:
            cls.initialize_defaults()
        return list(cls._types.values())

    @classmethod
    def is_registered(cls, type_name: str) -> bool:
        """Check if a type name is registered."""
        if not cls._types:
            cls.initialize_defaults()
        return type_name.strip().lower() in cls._types


# Auto-initialize
ObjectTypeRegistry.initialize_defaults()
