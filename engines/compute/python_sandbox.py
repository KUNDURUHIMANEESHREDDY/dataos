"""
Deterministic, Hardened Python Sandbox for DataOS (Rule #14, Rule #50, Rule #63).
Executes Python code against real DataObjects with AST security analysis,
safe builtins isolation, stdout/stderr capture, execution telemetry, and complete provenance.
"""

from __future__ import annotations
import ast
import os
import sys
import json
import io
import time
import datetime
import traceback
import threading
from typing import Dict, Any, List, Optional, Set
import pandas as pd
import numpy as np
from core.object.model import DataObject
from infrastructure.storage.base import StorageBackend


class SecurityViolationError(Exception):
    """Raised when Python code violates sandboxing security policies."""
    pass


# Strictly whitelisted builtins for sandbox execution
SAFE_BUILTINS = {
    "abs": abs, "all": all, "any": any, "ascii": ascii, "bin": bin, "bool": bool,
    "bytearray": bytearray, "bytes": bytes, "chr": chr, "complex": complex,
    "dict": dict, "dir": dir, "divmod": divmod, "enumerate": enumerate,
    "filter": filter, "float": float, "format": format, "frozenset": frozenset,
    "hash": hash, "hex": hex, "int": int, "isinstance": isinstance,
    "issubclass": issubclass, "iter": iter, "len": len, "list": list,
    "map": map, "max": max, "min": min, "next": next, "oct": oct,
    "ord": ord, "pow": pow, "print": print, "range": range, "repr": repr,
    "reversed": reversed, "round": round, "set": set, "slice": slice,
    "sorted": sorted, "str": str, "sum": sum, "tuple": tuple, "type": type,
    "zip": zip, "None": None, "True": True, "False": False
}

DANGEROUS_ATTRIBUTES = {
    "__subclasses__", "__globals__", "__code__", "__class__", "__bases__",
    "__mro__", "__builtins__", "__import__", "__loader__", "__spec__",
    "__dict__", "gi_frame", "f_globals", "f_locals", "cr_frame"
}

DANGEROUS_BUILTIN_CALLS = {
    "eval", "exec", "open", "compile", "__import__", "breakpoint", "input",
    "globals", "locals", "getattr", "setattr", "delattr", "memoryview"
}

ALLOWED_IMPORT_MODULES = {"math", "statistics", "json", "re", "datetime", "time", "itertools", "collections", "numpy", "pandas"}


class SecurityASTValidator(ast.NodeVisitor):
    """Inspects Python code AST for unsafe operations before execution."""

    def __init__(self):
        self.violations: List[str] = []

    def visit_Import(self, node: ast.Import):
        """Check that import statements use only allowed modules."""
        for alias in node.names:
            base_mod = alias.name.split(".")[0]
            if base_mod not in ALLOWED_IMPORT_MODULES:
                self.violations.append(f"Import of unauthorized module '{alias.name}' is prohibited in sandbox.")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        """Check that from-import statements use only allowed modules."""
        if node.module:
            base_mod = node.module.split(".")[0]
            if base_mod not in ALLOWED_IMPORT_MODULES:
                self.violations.append(f"Import from unauthorized module '{node.module}' is prohibited in sandbox.")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        """Reject access to dangerous attributes like __globals__ or __code__."""
        if node.attr in DANGEROUS_ATTRIBUTES:
            self.violations.append(f"Access to dangerous attribute '{node.attr}' is prohibited in sandbox.")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        """Reject calls to prohibited builtins like eval, exec, or open."""
        if isinstance(node.func, ast.Name):
            if node.func.id in DANGEROUS_BUILTIN_CALLS:
                self.violations.append(f"Invocation of system builtin '{node.func.id}()' is prohibited in sandbox.")
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        """Reject async function definitions."""
        self.violations.append("Async function definitions are prohibited in sandbox.")
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor):
        """Reject async for loops."""
        self.violations.append("Async loops are prohibited in sandbox.")
        self.generic_visit(node)

    def visit_AsyncWith(self, node: ast.AsyncWith):
        """Reject async with statements."""
        self.violations.append("Async context managers are prohibited in sandbox.")
        self.generic_visit(node)


class PythonSandbox:
    """Deterministic, hardened Python execution against real DataOS objects."""

    def __init__(
        self,
        storage: StorageBackend,
        default_timeout_seconds: float = 10.0,
        max_output_payload_bytes: int = 10 * 1024 * 1024  # 10 MB
    ):
        self.storage = storage
        self.default_timeout_seconds = default_timeout_seconds
        self.max_output_payload_bytes = max_output_payload_bytes

    def validate_code_security(self, code_str: str) -> None:
        """Parses AST and rejects dangerous constructs."""
        try:
            tree = ast.parse(code_str)
        except SyntaxError as e:
            raise SecurityViolationError(f"Syntax error in Python script: {e}")

        validator = SecurityASTValidator()
        validator.visit(tree)
        if validator.violations:
            raise SecurityViolationError("; ".join(validator.violations))

    def execute_code(
        self,
        code_str: str,
        input_object_ids: Optional[List[str]] = None,
        agent_or_user: str = "system",
        timeout_seconds: Optional[float] = None
    ) -> Dict[str, Any]:
        """Execute Python code in a sandboxed environment with input objects loaded."""
        start_time = time.time()
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        timeout = timeout_seconds or self.default_timeout_seconds

        # 1. Security validation
        try:
            self.validate_code_security(code_str)
        except SecurityViolationError as sve:
            return {
                "success": False,
                "error": str(sve),
                "stdout": "",
                "stderr": str(sve),
                "output": {},
                "results": {},
                "duration_ms": round((time.time() - start_time) * 1000.0, 2),
                "timestamp": now,
                "security_violation": True,
                "timeout_exceeded": False
            }

        # 2. Build context dictionary with loaded dataframes/objects
        context_data: Dict[str, Any] = {
            "pd": pd,
            "np": np,
            "dataos_objects": {},
            "dataos_dfs": {},
            "results": {}
        }

        loaded_ids = []
        if input_object_ids:
            for obj_id in input_object_ids:
                obj = self.storage.get_object(obj_id)
                if obj:
                    loaded_ids.append(obj.id)
                    filename_raw = obj.properties.get("filename") or obj.id[:8]
                    clean_name = "".join(c if c.isalnum() or c == "_" else "_" for c in filename_raw)
                    base_name, _ = os.path.splitext(filename_raw) if "." in filename_raw else (filename_raw, "")
                    clean_base = "".join(c if c.isalnum() or c == "_" else "_" for c in base_name)
                    table_prop = obj.properties.get("table_name")

                    # Register object aliases
                    for key in {clean_name, clean_base, table_prop, obj.id, obj.id[:8]}:
                        if key:
                            context_data["dataos_objects"][key] = obj

                    # Create DF if tabular
                    df = None
                    if isinstance(obj.content, list) and all(isinstance(r, dict) for r in obj.content):
                        df = pd.DataFrame(obj.content)
                    elif isinstance(obj.properties.get("sample_rows"), list):
                        df = pd.DataFrame(obj.properties["sample_rows"])
                    elif isinstance(obj.properties.get("raw_csv"), str):
                        df = pd.read_csv(io.StringIO(obj.properties["raw_csv"]))

                    if df is not None:
                        for key in {clean_name, clean_base, table_prop, obj.id, obj.id[:8]}:
                            if key:
                                context_data["dataos_dfs"][key] = df

        # Capture stdout & stderr
        redirected_stdout = io.StringIO()
        redirected_stderr = io.StringIO()

        def _sandbox_import(name, *args, **kwargs):
            base = name.split(".")[0]
            if base in ALLOWED_IMPORT_MODULES:
                return __import__(name, *args, **kwargs)
            raise ImportError(f"Import of '{name}' is not allowed in the DataOS sandbox.")

        exec_globals = {
            "__builtins__": {**dict(SAFE_BUILTINS), "__import__": _sandbox_import},
            "pd": pd,
            "np": np,
            "dfs": context_data["dataos_dfs"],
            "objects": context_data["dataos_objects"],
            "results": context_data["results"]
        }

        success = True
        error_msg = None
        timeout_exceeded = False

        # 3. Threaded Execution with Hard Timeout
        def _exec_target():
            nonlocal success, error_msg
            old_stdout = sys.stdout
            old_stderr = sys.stderr
            try:
                sys.stdout = redirected_stdout
                sys.stderr = redirected_stderr
                exec(code_str, exec_globals)
            except Exception as e:
                success = False
                error_msg = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
            finally:
                sys.stdout = old_stdout
                sys.stderr = old_stderr

        worker = threading.Thread(target=_exec_target, daemon=True)
        worker.start()
        worker.join(timeout=timeout)

        if worker.is_alive():
            success = False
            timeout_exceeded = True
            error_msg = f"ExecutionTimeoutError: Sandbox computation exceeded hard timeout of {timeout} seconds."

        stdout_content = redirected_stdout.getvalue()
        stderr_content = redirected_stderr.getvalue()
        duration_ms = (time.time() - start_time) * 1000.0

        # 4. Extract serializable variables and verify payload caps
        safe_output = {}
        if success:
            for k, v in exec_globals.get("results", {}).items():
                if isinstance(v, (pd.DataFrame, pd.Series)):
                    safe_output[k] = v.to_dict()
                elif isinstance(v, np.ndarray):
                    safe_output[k] = v.tolist()
                elif isinstance(v, (int, float, str, bool, list, dict, type(None))):
                    safe_output[k] = v
                else:
                    safe_output[k] = str(v)

            # Payload size limit enforcement
            try:
                payload_json = json.dumps(safe_output)
                if len(payload_json.encode("utf-8")) > self.max_output_payload_bytes:
                    success = False
                    error_msg = f"MemoryPayloadExceeded: Output payload size exceeded {self.max_output_payload_bytes} bytes limit."
                    safe_output = {}
            except Exception:
                pass

        return {
            "success": success,
            "stdout": stdout_content,
            "stderr": stderr_content or error_msg,
            "error": error_msg,
            "output": safe_output,
            "results": safe_output,  # alias kept for backward compatibility
            "input_objects_loaded": loaded_ids,
            "duration_ms": round(duration_ms, 2),
            "timestamp": now,
            "agent_or_user": agent_or_user,
            "security_violation": False,
            "timeout_exceeded": timeout_exceeded
        }
