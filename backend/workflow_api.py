"""Safe API boundary for executing bounded, built-in DataOS workflows.

The runtime engine supports custom handlers internally. The HTTP API deliberately
exposes only deterministic built-in actions and validates resource bounds before
execution so an API caller cannot register code or request unbounded retries.
"""
from __future__ import annotations

import json
import re
from typing import Any

_ALLOWED_ACTIONS = {"noop", "set_variable", "log"}
_ALLOWED_CONDITIONS = {"==", "!=", "exists", "not_exists", "in"}
_NODE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_MAX_NODES = 25
_MAX_PAYLOAD_BYTES = 128 * 1024
_MAX_RETRIES = 3
_MAX_RETRY_DELAY_SECONDS = 0.25


class WorkflowRequestError(ValueError):
    """A workflow request is invalid or exceeds the API execution budget."""


def execute_safe_workflow(engine: Any, definition: Any, context: Any) -> dict[str, Any]:
    """Validate and execute a small DAG using only built-in, non-code actions."""
    if not isinstance(definition, dict):
        raise WorkflowRequestError("definition must be an object")
    if set(definition) - {"name", "nodes", "trigger", "context", "description"}:
        raise WorkflowRequestError("definition contains unsupported top-level fields")

    name = definition.get("name", "unnamed")
    if not isinstance(name, str) or not name.strip() or len(name) > 128:
        raise WorkflowRequestError("workflow name must be a non-empty string up to 128 characters")
    description = definition.get("description", "")
    if not isinstance(description, str) or len(description) > 500:
        raise WorkflowRequestError("workflow description must be a string up to 500 characters")

    trigger = definition.get("trigger", {"type": "manual"})
    if not isinstance(trigger, dict) or trigger.get("type", "manual") != "manual":
        raise WorkflowRequestError("only manual workflow execution is supported by this endpoint")

    nodes = definition.get("nodes")
    if not isinstance(nodes, dict) or not 1 <= len(nodes) <= _MAX_NODES:
        raise WorkflowRequestError(f"nodes must be an object containing 1 to {_MAX_NODES} nodes")

    definition_context = definition.get("context", {})
    if not isinstance(definition_context, dict) or not isinstance(context, dict):
        raise WorkflowRequestError("workflow context must be an object")
    merged_context = {**definition_context, **context}

    try:
        payload_size = len(json.dumps(
            {"definition": definition, "context": merged_context},
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise WorkflowRequestError("workflow definition and context must contain JSON values only") from exc
    if payload_size > _MAX_PAYLOAD_BYTES:
        raise WorkflowRequestError(f"workflow request exceeds the {_MAX_PAYLOAD_BYTES}-byte limit")

    for node_id, node in nodes.items():
        if not isinstance(node_id, str) or not _NODE_ID.fullmatch(node_id):
            raise WorkflowRequestError("node IDs must be 1-64 safe ASCII letters, digits, dots, underscores, or hyphens")
        if not isinstance(node, dict):
            raise WorkflowRequestError(f"node {node_id!r} must be an object")
        if set(node) - {"action_type", "parameters", "depends_on", "retry", "condition", "timeout_seconds"}:
            raise WorkflowRequestError(f"node {node_id!r} contains unsupported fields")
        if node.get("timeout_seconds") is not None:
            raise WorkflowRequestError("per-node timeouts are not supported until runtime enforcement is available")

        action = node.get("action_type")
        if not isinstance(action, str) or action not in _ALLOWED_ACTIONS:
            raise WorkflowRequestError(
                f"node {node_id!r} action_type must be one of: {', '.join(sorted(_ALLOWED_ACTIONS))}"
            )

        parameters = node.get("parameters", {})
        if not isinstance(parameters, dict):
            raise WorkflowRequestError(f"node {node_id!r} parameters must be an object")
        if action == "set_variable":
            variable_name = parameters.get("name")
            if (
                not isinstance(variable_name, str)
                or not variable_name
                or len(variable_name) > 128
                or variable_name == "execution_id"
            ):
                raise WorkflowRequestError(f"node {node_id!r} set_variable requires a name up to 128 characters")
        if action == "log":
            message = parameters.get("message", "")
            if not isinstance(message, str) or len(message) > 1000:
                raise WorkflowRequestError(f"node {node_id!r} log message must be a string up to 1000 characters")

        dependencies = node.get("depends_on", [])
        if (
            not isinstance(dependencies, list)
            or len(dependencies) > _MAX_NODES
            or any(not isinstance(dep, str) for dep in dependencies)
            or len(set(dependencies)) != len(dependencies)
        ):
            raise WorkflowRequestError(f"node {node_id!r} depends_on must be a unique list of node IDs")

        retry = node.get("retry", {})
        if not isinstance(retry, dict) or set(retry) - {"max_attempts", "delay_seconds"}:
            raise WorkflowRequestError(f"node {node_id!r} retry must contain only max_attempts and delay_seconds")
        attempts = retry.get("max_attempts", 1)
        delay = retry.get("delay_seconds", 0)
        if type(attempts) is not int or not 1 <= attempts <= _MAX_RETRIES:
            raise WorkflowRequestError(f"node {node_id!r} max_attempts must be between 1 and {_MAX_RETRIES}")
        if type(delay) not in (int, float) or not 0 <= delay <= _MAX_RETRY_DELAY_SECONDS:
            raise WorkflowRequestError(
                f"node {node_id!r} delay_seconds must be between 0 and {_MAX_RETRY_DELAY_SECONDS}"
            )

        condition = node.get("condition")
        if condition is not None:
            if not isinstance(condition, dict) or set(condition) - {"field", "operator", "value"}:
                raise WorkflowRequestError(f"node {node_id!r} condition is invalid")
            field = condition.get("field", "")
            operator = condition.get("operator", "==")
            if not isinstance(field, str) or not field or len(field) > 128:
                raise WorkflowRequestError(f"node {node_id!r} condition field must be a non-empty string")
            if not isinstance(operator, str) or operator not in _ALLOWED_CONDITIONS:
                raise WorkflowRequestError(f"node {node_id!r} condition operator is unsupported")
            if operator == "in" and not isinstance(condition.get("value"), list):
                raise WorkflowRequestError(f"node {node_id!r} 'in' condition requires a list value")

    errors = engine.validate(definition)
    if errors:
        raise WorkflowRequestError("; ".join(errors))
    return engine.execute(definition, context=merged_context)
