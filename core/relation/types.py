"""
Extensible Relationship Types for the Universal Relationship Graph (Rule #4).
"""

from enum import Enum
from typing import Dict, Any, List, Optional


class RelationType(str, Enum):
    """Core domain-agnostic relationship types."""
    CONTAINS = "contains"
    CITES = "cites"
    READS_FROM = "reads_from"
    PRODUCES = "produces"
    DERIVED_FROM = "derived_from"
    SUPPORTED_BY = "supported_by"
    DEPENDS_ON = "depends_on"
    TRANSFORMS_TO = "transforms_to"
    REFERENCES = "references"
    AUTHORED_BY = "authored_by"
    EVALUATES = "evaluates"
    CONTRADICTS = "contradicts"
    CORRELATES_WITH = "correlates_with"
    HAS_PART = "has_part"
    IMPLEMENTS = "implements"
    CALLS = "calls"
    SIMILAR_TO = "similar_to"
    VERSION_OF = "version_of"
    CONTRACT_FOR = "contract_for"
    PROFILES = "profiles"
    CONFLICTS_WITH = "conflicts_with"
    SUPERSEDES = "supersedes"
    CUSTOM = "custom"


class RelationTypeRegistry:
    """Registry allowing user-defined custom relationship types."""
    _registered_types: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def register(
        cls,
        name: str,
        inverse_name: Optional[str] = None,
        description: str = "",
        is_directed: bool = True
    ):
        """Register a new custom relationship type."""
        clean_name = name.strip().lower()
        cls._registered_types[clean_name] = {
            "name": clean_name,
            "inverse_name": inverse_name,
            "description": description,
            "is_directed": is_directed
        }

    @classmethod
    def is_valid_type(cls, name: str) -> bool:
        """Check if a relationship type name is valid (built-in or registered)."""
        clean = name.strip().lower()
        if any(clean == r.value for r in RelationType):
            return True
        return clean in cls._registered_types

    @classmethod
    def list_types(cls) -> List[str]:
        """List all valid relationship type names."""
        types = [r.value for r in RelationType]
        types.extend(cls._registered_types.keys())
        return sorted(list(set(types)))
