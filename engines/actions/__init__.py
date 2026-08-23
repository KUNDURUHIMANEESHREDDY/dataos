"""
Object actions engine exports (Rule #55).
"""

from .registry import ActionsRegistry, ObjectAction, ActionCategory, ActionResult, register_builtin_actions

__all__ = [
    "ActionsRegistry",
    "ObjectAction",
    "ActionCategory",
    "ActionResult",
    "register_builtin_actions",
]
