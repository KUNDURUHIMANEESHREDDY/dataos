"""
Transformation Pipeline Engine for DataOS (Rule #22).
Chains data transformations into executable pipelines with step-level control,
error handling, and lineage tracking.
"""

from __future__ import annotations
import uuid
import datetime
import copy
from typing import Dict, Any, List, Optional, Callable
from enum import Enum


class StepStatus(str, Enum):
    """Status of an individual transformation step."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class PipelineStatus(str, Enum):
    """Status of a transformation pipeline."""
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


class TransformStep:
    """A single transformation step in a pipeline."""

    def __init__(
        self,
        step_id: str,
        transform_type: str,
        parameters: Optional[Dict[str, Any]] = None,
        name: str = "",
    ):
        self.step_id = step_id
        self.transform_type = transform_type
        self.parameters = parameters or {}
        self.name = name or step_id
        self.status: StepStatus = StepStatus.PENDING
        self.result: Any = None
        self.error: Optional[str] = None
        self.started_at: Optional[str] = None
        self.completed_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the transform step to a dictionary."""
        return {
            "step_id": self.step_id,
            "transform_type": self.transform_type,
            "name": self.name,
            "status": self.status.value,
            "error": self.error,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


class TransformationPipeline:
    """A chain of transformation steps."""

    def __init__(
        self,
        pipeline_id: str,
        name: str,
        description: str = "",
    ):
        self.pipeline_id = pipeline_id or str(uuid.uuid4())[:12]
        self.name = name
        self.description = description
        self.steps: List[TransformStep] = []
        self.status: PipelineStatus = PipelineStatus.CREATED
        self.created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.result: Any = None

    def add_step(self, step: TransformStep) -> None:
        """Append a transformation step to the pipeline."""
        self.steps.append(step)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the pipeline to a dictionary."""
        return {
            "pipeline_id": self.pipeline_id,
            "name": self.name,
            "description": self.description,
            "status": self.status.value,
            "steps": [s.to_dict() for s in self.steps],
            "created_at": self.created_at,
        }


class TransformationEngine:
    """Executes transformation pipelines."""

    def __init__(self):
        self._handlers: Dict[str, Callable[[Any, Dict[str, Any]], Any]] = {}
        self._pipelines: Dict[str, TransformationPipeline] = {}
        self._execution_history: List[Dict[str, Any]] = []
        self._register_builtins()

    def _register_builtins(self) -> None:
        self._handlers["filter"] = self._handle_filter
        self._handlers["map"] = self._handle_map
        self._handlers["sort"] = self._handle_sort
        self._handlers["deduplicate"] = self._handle_deduplicate
        self._handlers["aggregate"] = self._handle_aggregate
        self._handlers["rename_column"] = self._handle_rename_column
        self._handlers["add_column"] = self._handle_add_column
        self._handlers["drop_column"] = self._handle_drop_column
        self._handlers["cast"] = self._handle_cast
        self._handlers["limit"] = self._handle_limit
        self._handlers["flatten"] = self._handle_flatten
        self._handlers["pivot"] = self._handle_pivot
        self._handlers["unpivot"] = self._handle_unpivot
        self._handlers["merge"] = self._handle_merge
        self._handlers["split"] = self._handle_split
        self._handlers["custom"] = self._handle_custom

    def register_handler(self, transform_type: str, handler: Callable[[Any, Dict[str, Any]], Any]) -> None:
        """Register a handler for a custom transform type."""
        self._handlers[transform_type] = handler

    def create_pipeline(self, name: str, description: str = "") -> TransformationPipeline:
        """Create and register a new transformation pipeline."""
        pipeline = TransformationPipeline(str(uuid.uuid4())[:12], name, description)
        self._pipelines[pipeline.pipeline_id] = pipeline
        return pipeline

    def add_step(self, pipeline_id: str, transform_type: str, parameters: Optional[Dict[str, Any]] = None, name: str = "") -> Optional[TransformStep]:
        """Add a step to an existing pipeline."""
        pipeline = self._pipelines.get(pipeline_id)
        if not pipeline:
            return None
        step = TransformStep(str(uuid.uuid4())[:8], transform_type, parameters, name)
        pipeline.add_step(step)
        return step

    def execute(self, pipeline_id: str, data: Any, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute all steps in a pipeline sequentially."""
        pipeline = self._pipelines.get(pipeline_id)
        if not pipeline:
            return {"error": f"Pipeline '{pipeline_id}' not found"}

        pipeline.status = PipelineStatus.RUNNING
        ctx = context or {}
        current_data = copy.deepcopy(data)
        completed = 0
        failed = 0

        for step in pipeline.steps:
            step.status = StepStatus.RUNNING
            step.started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
            handler = self._handlers.get(step.transform_type)

            if not handler:
                step.status = StepStatus.FAILED
                step.error = f"No handler for transform type '{step.transform_type}'"
                step.completed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
                failed += 1
                pipeline.status = PipelineStatus.FAILED
                break

            try:
                result = handler(current_data, step.parameters)
                if isinstance(result, dict) and "data" in result:
                    current_data = result["data"]
                    step.result = result
                else:
                    current_data = result
                    step.result = {"output_preview": str(result)[:200]}
                step.status = StepStatus.COMPLETED
                completed += 1
            except Exception as e:
                step.status = StepStatus.FAILED
                step.error = str(e)
                step.completed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
                failed += 1
                pipeline.status = PipelineStatus.FAILED
                break
            step.completed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

        if failed == 0:
            pipeline.status = PipelineStatus.COMPLETED
        elif completed > 0:
            pipeline.status = PipelineStatus.PARTIAL

        pipeline.result = current_data

        report = {
            "pipeline_id": pipeline_id,
            "pipeline_name": pipeline.name,
            "status": pipeline.status.value,
            "total_steps": len(pipeline.steps),
            "completed": completed,
            "failed": failed,
            "result": current_data,
            "steps": [s.to_dict() for s in pipeline.steps],
        }
        self._execution_history.append(report)
        return report

    def get_pipeline(self, pipeline_id: str) -> Optional[TransformationPipeline]:
        """Retrieve a pipeline by its ID."""
        return self._pipelines.get(pipeline_id)

    def get_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Return recent pipeline execution history."""
        return self._execution_history[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        """Return pipeline execution statistics."""
        by_status = {}
        for p in self._pipelines.values():
            s = p.status.value
            by_status[s] = by_status.get(s, 0) + 1
        return {
            "total_pipelines": len(self._pipelines),
            "total_executions": len(self._execution_history),
            "by_status": by_status,
        }

    # ---- Built-in handlers ----

    def _handle_filter(self, data: Any, params: Dict[str, Any]) -> Any:
        if not isinstance(data, list):
            return data
        column = params.get("column")
        op = params.get("operator", "eq")
        value = params.get("value")
        if column is None:
            return data
        def match(row):
            v = row.get(column)
            if op == "eq": return v == value
            if op == "neq": return v != value
            if op == "gt": return v > value
            if op == "gte": return v >= value
            if op == "lt": return v < value
            if op == "lte": return v <= value
            if op == "contains": return value in str(v) if v else False
            if op == "in": return v in value if isinstance(value, list) else False
            return False
        return [r for r in data if match(r)]

    def _handle_map(self, data: Any, params: Dict[str, Any]) -> Any:
        if not isinstance(data, list):
            return data
        mapping = params.get("mapping", {})
        result = []
        for row in data:
            new_row = row.copy()
            for old_key, new_key in mapping.items():
                if old_key in new_row:
                    new_row[new_key] = new_row.pop(old_key)
            result.append(new_row)
        return result

    def _handle_sort(self, data: Any, params: Dict[str, Any]) -> Any:
        if not isinstance(data, list):
            return data
        column = params.get("column", "")
        descending = params.get("descending", False)
        return sorted(data, key=lambda r: r.get(column, 0), reverse=descending)

    def _handle_deduplicate(self, data: Any, params: Dict[str, Any]) -> Any:
        if not isinstance(data, list):
            return data
        columns = params.get("columns", [])
        seen = set()
        result = []
        for row in data:
            key = tuple(row.get(c) for c in columns) if columns else tuple(row.values())
            if key not in seen:
                seen.add(key)
                result.append(row)
        return result

    def _handle_aggregate(self, data: Any, params: Dict[str, Any]) -> Any:
        if not isinstance(data, list):
            return {"count": 0}
        group_by = params.get("group_by", [])
        agg_func = params.get("function", "count")
        agg_column = params.get("column", "")
        if group_by:
            groups: Dict[tuple, list] = {}
            for row in data:
                key = tuple(row.get(c) for c in group_by)
                groups.setdefault(key, []).append(row)
            result = []
            for key, rows in groups.items():
                out = dict(zip(group_by, key))
                vals = [r.get(agg_column, 0) for r in rows if r.get(agg_column) is not None]
                if agg_func == "count": out["agg"] = len(rows)
                elif agg_func == "sum": out["agg"] = sum(vals)
                elif agg_func == "avg": out["agg"] = sum(vals) / len(vals) if vals else 0
                elif agg_func == "min": out["agg"] = min(vals) if vals else 0
                elif agg_func == "max": out["agg"] = max(vals) if vals else 0
                result.append(out)
            return result
        vals = [r.get(agg_column, 0) for r in data if r.get(agg_column) is not None]
        if agg_func == "count": return {"count": len(data)}
        if agg_func == "sum": return {"sum": sum(vals)}
        if agg_func == "avg": return {"avg": sum(vals) / len(vals) if vals else 0}
        return {"count": len(data)}

    def _handle_rename_column(self, data: Any, params: Dict[str, Any]) -> Any:
        if not isinstance(data, list):
            return data
        old_name = params.get("old_name", "")
        new_name = params.get("new_name", "")
        return [{new_name: r.pop(old_name, None) if old_name in r else None, **r} for r in data]

    def _handle_add_column(self, data: Any, params: Dict[str, Any]) -> Any:
        if not isinstance(data, list):
            return data
        col_name = params.get("name", "")
        default = params.get("default")
        expression = params.get("expression")
        result = []
        for row in data:
            new_row = row.copy()
            if expression:
                try:
                    new_row[col_name] = eval(expression, {"__builtins__": {}}, {"row": row})
                except Exception:
                    new_row[col_name] = default
            else:
                new_row[col_name] = default
            result.append(new_row)
        return result

    def _handle_drop_column(self, data: Any, params: Dict[str, Any]) -> Any:
        if not isinstance(data, list):
            return data
        columns = params.get("columns", [])
        return [{k: v for k, v in row.items() if k not in columns} for row in data]

    def _handle_cast(self, data: Any, params: Dict[str, Any]) -> Any:
        if not isinstance(data, list):
            return data
        column = params.get("column", "")
        target_type = params.get("type", "string")
        for row in data:
            if column in row:
                try:
                    if target_type == "int": row[column] = int(row[column])
                    elif target_type == "float": row[column] = float(row[column])
                    elif target_type == "string": row[column] = str(row[column])
                    elif target_type == "bool": row[column] = bool(row[column])
                except (ValueError, TypeError):
                    pass
        return data

    def _handle_limit(self, data: Any, params: Dict[str, Any]) -> Any:
        if not isinstance(data, list):
            return data
        n = params.get("n", 10)
        return data[:n]

    def _handle_flatten(self, data: Any, params: Dict[str, Any]) -> Any:
        if not isinstance(data, list):
            return data
        column = params.get("column", "")
        result = []
        for row in data:
            val = row.get(column)
            if isinstance(val, list):
                for item in val:
                    new_row = row.copy()
                    new_row[column] = item
                    result.append(new_row)
            else:
                result.append(row)
        return result

    def _handle_pivot(self, data: Any, params: Dict[str, Any]) -> Any:
        if not isinstance(data, list):
            return data
        index_col = params.get("index", "")
        pivot_col = params.get("pivot_column", "")
        value_col = params.get("value_column", "")
        result = {}
        for row in data:
            idx = row.get(index_col, "")
            pv = row.get(pivot_col, "")
            vl = row.get(value_col, 0)
            if idx not in result:
                result[idx] = {index_col: idx}
            result[idx][str(pv)] = vl
        return list(result.values())

    def _handle_unpivot(self, data: Any, params: Dict[str, Any]) -> Any:
        if not isinstance(data, list):
            return data
        id_cols = params.get("id_columns", [])
        value_name = params.get("value_name", "value")
        var_name = params.get("var_name", "variable")
        result = []
        for row in data:
            ids = {c: row[c] for c in id_cols if c in row}
            for k, v in row.items():
                if k not in id_cols:
                    new_row = ids.copy()
                    new_row[var_name] = k
                    new_row[value_name] = v
                    result.append(new_row)
        return result

    def _handle_merge(self, data: Any, params: Dict[str, Any]) -> Any:
        if not isinstance(data, list):
            return data
        columns = params.get("columns", [])
        separator = params.get("separator", " ")
        new_name = params.get("new_name", "merged")
        result = []
        for row in data:
            new_row = row.copy()
            parts = [str(row.get(c, "")) for c in columns]
            new_row[new_name] = separator.join(parts)
            result.append(new_row)
        return result

    def _handle_split(self, data: Any, params: Dict[str, Any]) -> Any:
        if not isinstance(data, list):
            return data
        column = params.get("column", "")
        separator = params.get("separator", " ")
        new_names = params.get("new_names", [])
        result = []
        for row in data:
            new_row = row.copy()
            val = str(row.get(column, ""))
            parts = val.split(separator)
            for i, name in enumerate(new_names):
                new_row[name] = parts[i] if i < len(parts) else ""
            result.append(new_row)
        return result

    def _handle_custom(self, data: Any, params: Dict[str, Any]) -> Any:
        func_name = params.get("function_name", "")
        func_params = params.get("parameters", {})
        handler = self._handlers.get(f"custom_{func_name}")
        if handler:
            return handler(data, func_params)
        raise ValueError(f"Custom function '{func_name}' not registered")
