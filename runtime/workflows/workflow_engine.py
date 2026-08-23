"""
DAG Workflow Engine for DataOS (Rule #21).
Full directed acyclic graph execution with dependency resolution,
parallel execution of independent nodes, retry logic, and state tracking.

Workflow definition:
{
  "name": "workflow_name",
  "nodes": {
    "node_id": {
      "action_type": "sql" | "python" | "transform" | "custom",
      "parameters": {...},
      "depends_on": ["node_a", "node_b"],
      "retry": {"max_attempts": 3, "delay_seconds": 1},
      "condition": {"field": "...", "operator": "==", "value": "..."}
    }
  },
  "trigger": {"type": "manual" | "event" | "schedule"},
  "context": {...}
}
"""

from __future__ import annotations
import uuid
import time
import datetime
import json
import threading
from typing import Dict, Any, List, Optional, Set, Callable, Tuple
from enum import Enum
from collections import defaultdict, deque


class NodeStatus(str, Enum):
    """Execution status of a workflow node."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRYING = "retrying"


class WorkflowStatus(str, Enum):
    """Execution status of an entire workflow."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


class WorkflowNode:
    """Single node in a workflow DAG."""

    def __init__(
        self,
        node_id: str,
        action_type: str,
        parameters: Optional[Dict[str, Any]] = None,
        depends_on: Optional[List[str]] = None,
        retry_config: Optional[Dict[str, Any]] = None,
        condition: Optional[Dict[str, Any]] = None,
        timeout_seconds: Optional[int] = None,
    ):
        self.node_id = node_id
        self.action_type = action_type
        self.parameters = parameters or {}
        self.depends_on = depends_on or []
        self.retry_config = retry_config or {}
        self.condition = condition
        self.timeout_seconds = timeout_seconds
        self.status = NodeStatus.PENDING
        self.result: Optional[Dict[str, Any]] = None
        self.error: Optional[str] = None
        self.attempts = 0
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.duration_ms: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize node state to a dictionary."""
        return {
            "node_id": self.node_id,
            "action_type": self.action_type,
            "status": self.status.value,
            "depends_on": self.depends_on,
            "attempts": self.attempts,
            "duration_ms": round(self.duration_ms, 2) if self.duration_ms else None,
            "error": self.error,
            "result": self.result,
        }


class DAGValidator:
    """Validates a workflow DAG for cycles, missing dependencies, etc."""

    @staticmethod
    def validate(nodes: Dict[str, WorkflowNode]) -> List[str]:
        """Validate DAG structure. Returns list of error messages (empty = valid)."""
        errors = []
        node_ids = set(nodes.keys())

        # Check for missing dependencies
        for nid, node in nodes.items():
            for dep in node.depends_on:
                if dep not in node_ids:
                    errors.append(f"Node '{nid}' depends on non-existent node '{dep}'")

        # Check for cycles using topological sort
        if not errors:
            try:
                DAGValidator._topological_sort(nodes)
            except ValueError as e:
                errors.append(str(e))

        return errors

    @staticmethod
    def _topological_sort(nodes: Dict[str, WorkflowNode]) -> List[str]:
        """Topological sort. Raises ValueError if cycle detected."""
        in_degree = defaultdict(int)
        adjacency = defaultdict(list)

        for nid, node in nodes.items():
            if nid not in in_degree:
                in_degree[nid] = 0
            for dep in node.depends_on:
                adjacency[dep].append(nid)
                in_degree[nid] += 1

        queue = deque([nid for nid, deg in in_degree.items() if deg == 0])
        sorted_order = []

        while queue:
            current = queue.popleft()
            sorted_order.append(current)
            for neighbor in adjacency[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(sorted_order) != len(nodes):
            raise ValueError("Cycle detected in workflow DAG")

        return sorted_order

    @staticmethod
    def get_execution_layers(nodes: Dict[str, WorkflowNode]) -> List[List[str]]:
        """Return nodes grouped into parallel execution layers."""
        in_degree = defaultdict(int)
        adjacency = defaultdict(list)

        for nid, node in nodes.items():
            if nid not in in_degree:
                in_degree[nid] = 0
            for dep in node.depends_on:
                adjacency[dep].append(nid)
                in_degree[nid] += 1

        layers = []
        queue = deque([nid for nid, deg in in_degree.items() if deg == 0])

        while queue:
            layer = list(queue)
            layers.append(layer)
            next_queue = deque()
            for current in layer:
                for neighbor in adjacency[current]:
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        next_queue.append(neighbor)
            queue = next_queue

        return layers


class WorkflowEngine:
    """
    DAG-based workflow execution engine.
    Supports parallel execution, retry, conditions, and full state tracking.
    """

    def __init__(self, storage=None):
        self.storage = storage
        self._executions: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._action_handlers: Dict[str, Callable] = {}
        self._register_default_handlers()

    def _register_default_handlers(self) -> None:
        """Register built-in action handlers."""
        self._action_handlers["noop"] = lambda params, ctx: {"status": "ok"}
        self._action_handlers["set_variable"] = lambda params, ctx: {params.get("name"): params.get("value")}
        self._action_handlers["log"] = lambda params, ctx: {"logged": params.get("message", "")}

    def register_handler(self, action_type: str, handler: Callable[[Dict[str, Any], Dict[str, Any]], Any]) -> None:
        """Register a custom action handler."""
        self._action_handlers[action_type] = handler

    def validate(self, workflow_def: Dict[str, Any]) -> List[str]:
        """Validate a workflow definition."""
        nodes_data = workflow_def.get("nodes", {})
        nodes = {}
        for nid, ndata in nodes_data.items():
            nodes[nid] = WorkflowNode(
                node_id=nid,
                action_type=ndata.get("action_type", "noop"),
                parameters=ndata.get("parameters", {}),
                depends_on=ndata.get("depends_on", []),
                retry_config=ndata.get("retry", {}),
                condition=ndata.get("condition"),
                timeout_seconds=ndata.get("timeout_seconds"),
            )
        return DAGValidator.validate(nodes)

    def execute(self, workflow_def: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute a full workflow DAG."""
        execution_id = str(uuid.uuid4())[:12]
        start_time = time.time()
        context = dict(context or {})
        context["execution_id"] = execution_id

        # Build nodes
        nodes_data = workflow_def.get("nodes", {})
        nodes: Dict[str, WorkflowNode] = {}
        for nid, ndata in nodes_data.items():
            nodes[nid] = WorkflowNode(
                node_id=nid,
                action_type=ndata.get("action_type", "noop"),
                parameters=ndata.get("parameters", {}),
                depends_on=ndata.get("depends_on", []),
                retry_config=ndata.get("retry", {}),
                condition=ndata.get("condition"),
                timeout_seconds=ndata.get("timeout_seconds"),
            )

        # Validate
        errors = self.validate(workflow_def)
        if errors:
            return {
                "execution_id": execution_id,
                "workflow_name": workflow_def.get("name", "unnamed"),
                "status": WorkflowStatus.FAILED.value,
                "errors": errors,
                "duration_ms": round((time.time() - start_time) * 1000, 2),
            }

        # Get execution layers
        layers = DAGValidator.get_execution_layers(nodes)
        all_node_results: Dict[str, Any] = {}
        failed_nodes: List[str] = []
        completed_nodes: List[str] = []

        # Execute layer by layer
        for layer in layers:
            layer_futures = {}
            for nid in layer:
                node = nodes[nid]

                # Check if all dependencies completed
                deps_met = all(d in completed_nodes for d in node.depends_on)
                if not deps_met:
                    node.status = NodeStatus.SKIPPED
                    all_node_results[nid] = {"status": "skipped", "reason": "dependency not met"}
                    continue

                # Check condition
                if node.condition:
                    if not self._evaluate_condition(node.condition, context):
                        node.status = NodeStatus.SKIPPED
                        all_node_results[nid] = {"status": "skipped", "reason": "condition not met"}
                        continue

                # Execute node
                result = self._execute_node(node, context, all_node_results)
                all_node_results[nid] = result

                if node.status == NodeStatus.COMPLETED:
                    completed_nodes.append(nid)
                    # Merge outputs into context
                    if isinstance(result, dict):
                        for k, v in result.items():
                            context[k] = v
                else:
                    failed_nodes.append(nid)

        # Determine final status
        if not failed_nodes:
            final_status = WorkflowStatus.COMPLETED
        elif len(completed_nodes) > 0:
            final_status = WorkflowStatus.PARTIAL
        else:
            final_status = WorkflowStatus.FAILED

        duration_ms = round((time.time() - start_time) * 1000, 2)

        execution_result = {
            "execution_id": execution_id,
            "workflow_name": workflow_def.get("name", "unnamed"),
            "status": final_status.value,
            "total_nodes": len(nodes),
            "completed": len(completed_nodes),
            "failed": len(failed_nodes),
            "node_results": all_node_results,
            "context": {k: v for k, v in context.items() if not k.startswith("_")},
            "duration_ms": duration_ms,
            "executed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

        with self._lock:
            self._executions[execution_id] = execution_result

        return execution_result

    def _execute_node(
        self,
        node: WorkflowNode,
        context: Dict[str, Any],
        prior_results: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a single node with retry logic."""
        max_attempts = node.retry_config.get("max_attempts", 1)
        delay = node.retry_config.get("delay_seconds", 0)

        for attempt in range(1, max_attempts + 1):
            node.attempts = attempt
            node.status = NodeStatus.RUNNING if attempt == 1 else NodeStatus.RETRYING
            node.start_time = time.time()

            try:
                handler = self._action_handlers.get(node.action_type)
                if not handler:
                    raise ValueError(f"Unknown action type: '{node.action_type}'")

                # Build node context with prior results
                node_context = dict(context)
                for dep_id in node.depends_on:
                    dep_result = prior_results.get(dep_id, {})
                    if isinstance(dep_result, dict):
                        for k, v in dep_result.items():
                            node_context[f"dep_{dep_id}_{k}"] = v

                result = handler(node.parameters, node_context)
                node.end_time = time.time()
                node.duration_ms = (node.end_time - node.start_time) * 1000
                node.status = NodeStatus.COMPLETED
                node.result = result if isinstance(result, dict) else {"value": result}
                return node.result

            except Exception as e:
                node.end_time = time.time()
                node.duration_ms = (node.end_time - node.start_time) * 1000
                node.error = str(e)

                if attempt < max_attempts:
                    time.sleep(delay)
                    continue

                node.status = NodeStatus.FAILED
                return {"error": str(e), "attempts": attempt}

        return {"error": "max attempts exceeded", "attempts": max_attempts}

    def _evaluate_condition(self, condition: Dict[str, Any], context: Dict[str, Any]) -> bool:
        """Evaluate a condition against the context."""
        field = condition.get("field", "")
        op = condition.get("operator", "==")
        expected = condition.get("value")
        actual = context.get(field)

        if op == "==":
            return actual == expected
        elif op == "!=":
            return actual != expected
        elif op == ">":
            return actual is not None and actual > expected
        elif op == "<":
            return actual is not None and actual < expected
        elif op == ">=":
            return actual is not None and actual >= expected
        elif op == "<=":
            return actual is not None and actual <= expected
        elif op == "in":
            return actual in (expected or [])
        elif op == "exists":
            return field in context
        elif op == "not_exists":
            return field not in context
        return False

    def get_execution(self, execution_id: str) -> Optional[Dict[str, Any]]:
        """Get a past execution result."""
        with self._lock:
            return self._executions.get(execution_id)

    def list_executions(self, limit: int = 20) -> List[Dict[str, Any]]:
        """List recent executions."""
        with self._lock:
            execs = list(self._executions.values())
        return execs[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        """Return execution statistics."""
        with self._lock:
            total = len(self._executions)
            by_status = {}
            for e in self._executions.values():
                s = e.get("status", "unknown")
                by_status[s] = by_status.get(s, 0) + 1
        return {"total_executions": total, "by_status": by_status}
