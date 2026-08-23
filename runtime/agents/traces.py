"""
Auditable Execution Traces for AI Agents (Rule #19).
Logs all inputs, goals, tools used, queries executed, objects modified, outputs, and errors.
"""

from __future__ import annotations
import uuid
import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict


@dataclass
class AgentStepTrace:
    """Single step within an agent execution trace."""
    step_number: int
    capability: str
    inputs: Dict[str, Any]
    output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    duration_ms: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """Serialize step trace to a dictionary."""
        return asdict(self)


@dataclass
class AgentExecutionTrace:
    """Complete execution trace for an agent run."""
    agent_id: str
    goal: str
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    started_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    completed_at: Optional[str] = None
    status: str = "RUNNING"  # "SUCCESS", "FAILED", "RUNNING"
    steps: List[AgentStepTrace] = field(default_factory=list)
    objects_accessed: List[str] = field(default_factory=list)
    objects_modified: List[str] = field(default_factory=list)
    error_message: Optional[str] = None

    def add_step(self, step: AgentStepTrace):
        """Append a step to the execution trace."""
        self.steps.append(step)

    def complete(self, status: str = "SUCCESS", error: Optional[str] = None):
        """Mark trace as completed with final status."""
        self.completed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.status = status
        self.error_message = error

    def to_dict(self) -> Dict[str, Any]:
        """Serialize execution trace to a dictionary."""
        d = asdict(self)
        d["steps"] = [s.to_dict() if isinstance(s, AgentStepTrace) else s for s in self.steps]
        return d
