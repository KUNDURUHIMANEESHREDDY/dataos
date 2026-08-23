"""
Permissions and Access Control for DataOS (Rule #18, Rule #42).
Fine-grained capability gating for users and AI agents.
"""

from enum import Enum
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass, field


class AccessLevel(str, Enum):
    NONE = "none"
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"


class Capability(str, Enum):
    """Allowed runtime operations for AI Agents and users."""
    SEARCH = "search"
    READ_OBJECT = "read_object"
    CREATE_OBJECT = "create_object"
    UPDATE_OBJECT = "update_object"
    DELETE_OBJECT = "delete_object"
    CREATE_RELATION = "create_relation"
    DELETE_RELATION = "delete_relation"
    QUERY_SQL = "query_sql"
    COMPUTE_PYTHON = "compute_python"
    TRANSFORM_DATA = "transform_data"
    EXTRACT_KNOWLEDGE = "extract_knowledge"
    EXECUTE_WORKFLOW = "execute_workflow"
    CALL_CONNECTOR = "call_connector"
    EXPORT_DATA = "export_data"


@dataclass
class PermissionPolicy:
    """Access policy attached to an agent, user role, or object."""
    principal_id: str
    role: str = "operator"
    allowed_capabilities: Set[str] = field(default_factory=lambda: {
        Capability.SEARCH.value,
        Capability.READ_OBJECT.value,
        Capability.CREATE_RELATION.value,
        Capability.QUERY_SQL.value,
        Capability.COMPUTE_PYTHON.value
    })
    object_whitelist: Optional[List[str]] = None  # Specific object IDs allowed
    type_whitelist: Optional[List[str]] = None    # Specific object types allowed
    time_bound_until: Optional[str] = None         # ISO timestamp for lease expiration
    requires_approval_for: Set[str] = field(default_factory=lambda: {
        Capability.DELETE_OBJECT.value,
        Capability.DELETE_RELATION.value
    })

    def has_capability(self, capability: Union[Capability, str]) -> bool:
        """Check if principal has the given capability."""
        cap_val = capability.value if isinstance(capability, Capability) else capability
        return cap_val in self.allowed_capabilities

    def can_access_object(self, object_id: str, object_type: str, operation: Union[Capability, str]) -> bool:
        """Check if principal has permission to perform operation on a specific object."""
        if not self.has_capability(operation):
            return False

        if self.object_whitelist is not None and object_id not in self.object_whitelist:
            return False

        if self.type_whitelist is not None and object_type not in self.type_whitelist:
            return False

        return True

    def to_dict(self) -> Dict[str, Any]:
        """Serialize policy to dictionary."""
        return {
            "principal_id": self.principal_id,
            "role": self.role,
            "allowed_capabilities": list(self.allowed_capabilities),
            "object_whitelist": self.object_whitelist,
            "type_whitelist": self.type_whitelist,
            "time_bound_until": self.time_bound_until,
            "requires_approval_for": list(self.requires_approval_for)
        }
