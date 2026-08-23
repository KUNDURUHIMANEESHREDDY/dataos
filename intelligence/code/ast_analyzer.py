"""
Code Intelligence & AST Analyzer for DataOS (Rule #52).
Analyzes Python scripts and notebooks, extracting imports, dependencies,
functions, classes, SQL queries, and DataFrame transformations.
"""

from __future__ import annotations
import ast
import re
from typing import Dict, Any, List, Optional, Set


class CodeASTAnalyzer:
    """Analyzes Python code to extract symbols, dependencies, and execution flow."""

    @classmethod
    def analyze_python_code(cls, code_text: str, filename: str = "script.py") -> Dict[str, Any]:
        """Analyze Python code and extract imports, functions, classes, and data dependencies."""
        imports: List[Dict[str, str]] = []
        functions: List[Dict[str, Any]] = []
        classes: List[Dict[str, Any]] = []
        function_calls: List[str] = []
        sql_queries: List[str] = []
        data_dependencies: Set[str] = set()

        try:
            tree = ast.parse(code_text)
            for node in ast.walk(tree):
                # Imports
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append({"module": alias.name, "alias": alias.asname or alias.name, "line": node.lineno})
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    for alias in node.names:
                        imports.append({"module": f"{mod}.{alias.name}", "alias": alias.asname or alias.name, "line": node.lineno})

                # Function definitions
                elif isinstance(node, ast.FunctionDef):
                    args = [a.arg for a in node.args.args]
                    functions.append({
                        "name": node.name,
                        "args": args,
                        "line": node.lineno,
                        "docstring": ast.get_docstring(node) or ""
                    })

                # Class definitions
                elif isinstance(node, ast.ClassDef):
                    bases = [b.id for b in node.bases if isinstance(b, ast.Name)]
                    classes.append({
                        "name": node.name,
                        "bases": bases,
                        "line": node.lineno,
                        "docstring": ast.get_docstring(node) or ""
                    })

                # Function calls
                elif isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        function_calls.append(node.func.id)
                    elif isinstance(node.func, ast.Attribute):
                        function_calls.append(node.func.attr)

                # String constants that look like SQL or file paths
                elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                    val = node.value.strip()
                    if re.match(r"^(SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|WITH)\s", val, re.IGNORECASE):
                        sql_queries.append(val)
                    if re.search(r"\.(csv|parquet|json|xlsx|sqlite|db)$", val, re.IGNORECASE):
                        data_dependencies.add(val)

        except SyntaxError as e:
            return {
                "filename": filename,
                "error": f"Syntax error: {e.msg} at line {e.lineno}",
                "imports": [],
                "functions": [],
                "classes": [],
                "function_calls": [],
                "sql_queries": [],
                "data_dependencies": []
            }

        return {
            "filename": filename,
            "total_lines": len(code_text.splitlines()),
            "imports": imports,
            "functions": functions,
            "classes": classes,
            "function_calls": list(set(function_calls)),
            "sql_queries": sql_queries,
            "data_dependencies": list(data_dependencies)
        }
