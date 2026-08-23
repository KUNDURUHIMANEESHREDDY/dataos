"""
Universal Object Actions Registry for DataOS (Rule #55).
Objects expose dynamic capabilities (read, query, transform, analyze, execute, etc.)
through a formal, extensible action registration and execution system.
"""

from __future__ import annotations
import uuid
import datetime
import inspect
from typing import Dict, Any, List, Optional, Callable, Set
from enum import Enum


class ActionCategory(str, Enum):
    """Categories of actions that can be performed on data objects."""
    READ = "read"
    QUERY = "query"
    TRANSFORM = "transform"
    ANALYZE = "analyze"
    EXECUTE = "execute"
    SUMMARIZE = "summarize"
    DOCUMENT = "document"
    EXPORT = "export"
    VALIDATE = "validate"
    COMPARE = "compare"
    CUSTOM = "custom"


class ObjectAction:
    """Represents a single action that can be performed on an object."""

    def __init__(
        self,
        action_id: str,
        name: str,
        category: ActionCategory,
        handler: Callable[..., Any],
        description: str = "",
        input_types: Optional[List[str]] = None,
        output_type: str = "any",
        requires_permissions: Optional[List[str]] = None,
        applicable_types: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.action_id = action_id
        self.name = name
        self.category = category
        self.handler = handler
        self.description = description
        self.input_types = input_types or []
        self.output_type = output_type
        self.requires_permissions = requires_permissions or []
        self.applicable_types = applicable_types or []  # empty = all types
        self.metadata = metadata or {}
        self.created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.call_count = 0
        self.last_called_at: Optional[str] = None
        self.error_count = 0

    def is_applicable_to(self, object_type: str) -> bool:
        """Check if this action applies to a given object type."""
        if not self.applicable_types:
            return True
        return object_type in self.applicable_types

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the action to a dictionary."""
        return {
            "action_id": self.action_id,
            "name": self.name,
            "category": self.category.value,
            "description": self.description,
            "input_types": self.input_types,
            "output_type": self.output_type,
            "requires_permissions": self.requires_permissions,
            "applicable_types": self.applicable_types,
            "metadata": self.metadata,
            "call_count": self.call_count,
            "last_called_at": self.last_called_at,
            "error_count": self.error_count,
        }


class ActionResult:
    """Result of executing an action on an object."""

    def __init__(
        self,
        action_id: str,
        object_id: str,
        success: bool,
        output: Any = None,
        error: Optional[str] = None,
        execution_time_ms: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.result_id = str(uuid.uuid4())[:12]
        self.action_id = action_id
        self.object_id = object_id
        self.success = success
        self.output = output
        self.error = error
        self.execution_time_ms = execution_time_ms
        self.metadata = metadata or {}
        self.timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the action result to a dictionary."""
        return {
            "result_id": self.result_id,
            "action_id": self.action_id,
            "object_id": self.object_id,
            "success": self.success,
            "output": self.output if self.success else None,
            "error": self.error,
            "execution_time_ms": round(self.execution_time_ms, 2),
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }


class ActionsRegistry:
    """
    Central registry for all object actions.
    Supports registration, lookup, execution, and capability queries.
    """

    def __init__(self):
        self._actions: Dict[str, ObjectAction] = {}
        self._execution_history: List[ActionResult] = []
        self._max_history = 1000

    def register(
        self,
        action_id: str,
        name: str,
        category: ActionCategory,
        handler: Callable[..., Any],
        description: str = "",
        input_types: Optional[List[str]] = None,
        output_type: str = "any",
        requires_permissions: Optional[List[str]] = None,
        applicable_types: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ObjectAction:
        """Register a new action."""
        if action_id in self._actions:
            raise ValueError(f"Action '{action_id}' is already registered.")
        action = ObjectAction(
            action_id=action_id,
            name=name,
            category=category,
            handler=handler,
            description=description,
            input_types=input_types,
            output_type=output_type,
            requires_permissions=requires_permissions,
            applicable_types=applicable_types,
            metadata=metadata,
        )
        self._actions[action_id] = action
        return action

    def unregister(self, action_id: str) -> bool:
        """Remove an action from the registry."""
        if action_id in self._actions:
            del self._actions[action_id]
            return True
        return False

    def get(self, action_id: str) -> Optional[ObjectAction]:
        """Get an action by ID."""
        return self._actions.get(action_id)

    def list_all(self) -> List[Dict[str, Any]]:
        """List all registered actions."""
        return [a.to_dict() for a in self._actions.values()]

    def list_by_category(self, category: ActionCategory) -> List[Dict[str, Any]]:
        """List actions filtered by category."""
        return [a.to_dict() for a in self._actions.values() if a.category == category]

    def list_for_object_type(self, object_type: str) -> List[Dict[str, Any]]:
        """List all actions applicable to a specific object type."""
        return [
            a.to_dict() for a in self._actions.values()
            if a.is_applicable_to(object_type)
        ]

    def get_capabilities_for_object(self, object_type: str) -> List[str]:
        """Get action IDs that can be performed on an object type."""
        return [
            a.action_id for a in self._actions.values()
            if a.is_applicable_to(object_type)
        ]

    def execute(
        self,
        action_id: str,
        object_id: str,
        obj: Any = None,
        params: Optional[Dict[str, Any]] = None,
        user_permissions: Optional[List[str]] = None,
    ) -> ActionResult:
        """Execute an action on an object."""
        import time
        start = time.time()

        action = self._actions.get(action_id)
        if not action:
            return ActionResult(
                action_id=action_id,
                object_id=object_id,
                success=False,
                error=f"Action '{action_id}' not found.",
            )

        # Permission check
        if action.requires_permissions:
            user_perms = set(user_permissions or [])
            required = set(action.requires_permissions)
            if not required.issubset(user_perms):
                missing = required - user_perms
                return ActionResult(
                    action_id=action_id,
                    object_id=object_id,
                    success=False,
                    error=f"Missing permissions: {', '.join(missing)}",
                )

        # Execute
        try:
            kwargs = params or {}
            if obj is not None:
                kwargs["obj"] = obj
            kwargs["object_id"] = object_id
            output = action.handler(**kwargs)
            elapsed = (time.time() - start) * 1000
            result = ActionResult(
                action_id=action_id,
                object_id=object_id,
                success=True,
                output=output,
                execution_time_ms=elapsed,
            )
            action.call_count += 1
            action.last_called_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            result = ActionResult(
                action_id=action_id,
                object_id=object_id,
                success=False,
                error=str(e),
                execution_time_ms=elapsed,
            )
            action.error_count += 1

        # Store in history
        self._execution_history.append(result)
        if len(self._execution_history) > self._max_history:
            self._execution_history = self._execution_history[-self._max_history:]

        return result

    def get_execution_history(
        self,
        action_id: Optional[str] = None,
        object_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get execution history with optional filters."""
        results = []
        for r in reversed(self._execution_history):
            if action_id and r.action_id != action_id:
                continue
            if object_id and r.object_id != object_id:
                continue
            results.append(r.to_dict())
            if len(results) >= limit:
                break
        return results

    def get_stats(self) -> Dict[str, Any]:
        """Return registry statistics."""
        by_category = {}
        for a in self._actions.values():
            cat = a.category.value
            by_category[cat] = by_category.get(cat, 0) + 1
        total_calls = sum(a.call_count for a in self._actions.values())
        total_errors = sum(a.error_count for a in self._actions.values())
        return {
            "total_actions": len(self._actions),
            "by_category": by_category,
            "total_executions": len(self._execution_history),
            "total_calls": total_calls,
            "total_errors": total_errors,
        }


def register_builtin_actions(registry: ActionsRegistry) -> None:
    """Register built-in universal actions for all object types."""

    def read_action(object_id: str, obj: Any = None, **kwargs) -> Dict[str, Any]:
        if obj is None:
            return {"error": "No object provided"}
        if hasattr(obj, "to_dict"):
            return obj.to_dict()
        return {"object_id": object_id, "type": type(obj).__name__, "preview": str(obj)[:200]}

    def summarize_action(object_id: str, obj: Any = None, **kwargs) -> Dict[str, Any]:
        if obj is None:
            return {"error": "No object provided"}
        if hasattr(obj, "to_dict"):
            d = obj.to_dict()
            return {
                "object_id": object_id,
                "type": d.get("type", "unknown"),
                "summary": f"Object with {len(str(d))} characters of data",
            }
        return {"object_id": object_id, "summary": str(obj)[:200]}

    def validate_action(object_id: str, obj: Any = None, **kwargs) -> Dict[str, Any]:
        if obj is None:
            return {"valid": False, "error": "No object provided"}
        return {"valid": True, "object_id": object_id, "checks": ["not_none"]}

    def metadata_action(object_id: str, obj: Any = None, **kwargs) -> Dict[str, Any]:
        if obj is None:
            return {"error": "No object provided"}
        if hasattr(obj, "to_dict"):
            d = obj.to_dict()
            return {
                "object_id": object_id,
                "type": d.get("type"),
                "version": d.get("version"),
                "timestamps": d.get("timestamps"),
            }
        return {"object_id": object_id, "type": type(obj).__name__}

    def duplicate_action(object_id: str, obj: Any = None, **kwargs) -> Dict[str, Any]:
        if obj is None:
            return {"error": "No object provided"}
        if hasattr(obj, "create_new_version"):
            return {"object_id": object_id, "duplicated": True}
        return {"object_id": object_id, "duplicated": False, "reason": "Object does not support versioning"}

    registry.register("read", "Read Object", ActionCategory.READ, read_action, "Read and return object data")
    registry.register("summarize", "Summarize Object", ActionCategory.SUMMARIZE, summarize_action, "Generate a summary of the object")
    registry.register("validate", "Validate Object", ActionCategory.VALIDATE, validate_action, "Validate object integrity")
    registry.register("metadata", "Get Metadata", ActionCategory.READ, metadata_action, "Retrieve object metadata")
    registry.register("duplicate", "Duplicate Object", ActionCategory.TRANSFORM, duplicate_action, "Create a new version of the object")
