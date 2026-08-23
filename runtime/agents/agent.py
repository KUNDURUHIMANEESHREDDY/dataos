"""
Agent Capability Execution & Permission Enforcement for DataOS (Rule #17, Rule #18).
Controls access strictly through DataOS APIs.
"""

from __future__ import annotations
import time
import datetime
from typing import Dict, Any, List, Optional
from core.permissions.policy import PermissionPolicy, Capability
from core.object.model import DataObject, ObjectType
from core.relation.model import Relationship
from infrastructure.storage.base import StorageBackend
from engines.compute.sql_engine import SQLExecutionEngine
from engines.compute.python_sandbox import PythonSandbox
from engines.search.search_engine import HybridSearchEngine
from engines.graph.engine import GraphEngine
from .traces import AgentExecutionTrace, AgentStepTrace


class AgentHarness:
    """Harness executing capabilities on behalf of an AI Agent with strict permission enforcement."""

    def __init__(self, agent_id: str, policy: PermissionPolicy, storage: StorageBackend):
        self.agent_id = agent_id
        self.policy = policy
        self.storage = storage
        self.sql_engine = SQLExecutionEngine(storage)
        self.python_sandbox = PythonSandbox(storage)
        self.search_engine = HybridSearchEngine(storage)
        self.graph_engine = GraphEngine(storage)

    def execute_capability(
        self,
        capability: Capability,
        params: Dict[str, Any],
        trace: Optional[AgentExecutionTrace] = None
    ) -> Dict[str, Any]:
        """Execute a capability if authorized, recording steps into the execution trace."""
        start_time = time.time()
        cap_val = capability.value if isinstance(capability, Capability) else capability

        # 1. Permission check
        if not self.policy.has_capability(cap_val):
            error_msg = f"Permission denied: Agent '{self.agent_id}' does not have capability '{cap_val}'"
            if trace:
                trace.add_step(AgentStepTrace(
                    step_number=len(trace.steps) + 1,
                    capability=cap_val,
                    inputs=params,
                    error=error_msg,
                    duration_ms=(time.time() - start_time) * 1000.0
                ))
            raise PermissionError(error_msg)

        step_output = None
        error_msg = None

        try:
            # 2. Dispatch capability
            if cap_val == Capability.SEARCH.value:
                query = params.get("query", "")
                step_output = self.search_engine.search(query, limit=params.get("limit", 10))

            elif cap_val == Capability.READ_OBJECT.value:
                obj_id = params.get("object_id")
                obj = self.storage.get_object(obj_id)
                if obj and not self.policy.can_access_object(obj.id, obj.type, Capability.READ_OBJECT):
                    raise PermissionError(f"Access denied to object '{obj_id}'")
                step_output = obj.to_dict() if obj else None
                if trace and obj_id:
                    trace.objects_accessed.append(obj_id)

            elif cap_val == Capability.CREATE_OBJECT.value:
                obj = DataObject.from_dict(params.get("object_data", {}))
                obj.provenance["created_by_agent"] = self.agent_id
                saved_obj = self.storage.save_object(obj)
                step_output = saved_obj.to_dict()
                if trace:
                    trace.objects_modified.append(saved_obj.id)

            elif cap_val == Capability.CREATE_RELATION.value:
                rel = self.graph_engine.create_relation(
                    source_id=params["source_id"],
                    target_id=params["target_id"],
                    relation_type=params["relation_type"],
                    confidence=params.get("confidence", 1.0),
                    provenance={"created_by_agent": self.agent_id}
                )
                step_output = rel.to_dict()

            elif cap_val == Capability.QUERY_SQL.value:
                step_output = self.sql_engine.execute_sql(params["query"], agent_or_user=f"agent:{self.agent_id}")

            elif cap_val == Capability.COMPUTE_PYTHON.value:
                step_output = self.python_sandbox.execute_code(
                    params["code"],
                    input_object_ids=params.get("input_object_ids", []),
                    agent_or_user=f"agent:{self.agent_id}"
                )

            else:
                raise ValueError(f"Unsupported capability: {cap_val}")

            return {
                "success": True,
                "capability": cap_val,
                "output": step_output,
                "duration_ms": round((time.time() - start_time) * 1000.0, 2)
            }

        except Exception as e:
            error_msg = str(e)
            return {
                "success": False,
                "capability": cap_val,
                "error": error_msg,
                "duration_ms": round((time.time() - start_time) * 1000.0, 2)
            }
        finally:
            if trace:
                trace.add_step(AgentStepTrace(
                    step_number=len(trace.steps) + 1,
                    capability=cap_val,
                    inputs=params,
                    output=step_output if isinstance(step_output, dict) else ({"count": len(step_output)} if isinstance(step_output, list) else None),
                    error=error_msg,
                    duration_ms=round((time.time() - start_time) * 1000.0, 2)
                ))
