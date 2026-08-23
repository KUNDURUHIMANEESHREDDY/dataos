"""
Jupyter Notebook DAG & Cell-Level Lineage Engine for DataOS (Rule #51).
Parses .ipynb notebooks cell-by-cell into a structured execution DAG with
cell inputs, outputs, variable dependencies, data file reads/writes, and lineage.
"""

from __future__ import annotations
import ast
import json
import re
from typing import Dict, Any, List, Optional, Set, Tuple
from core.object.model import DataObject, ObjectType
from core.relation.model import Relationship, RelationType
from infrastructure.storage.base import StorageBackend


class NotebookCell:
    """Represents a parsed Jupyter Notebook cell."""

    def __init__(
        self,
        cell_index: int,
        cell_type: str,
        source: str,
        execution_count: Optional[int] = None,
        outputs: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.cell_index = cell_index
        self.cell_type = cell_type  # "code", "markdown", "raw"
        self.source = source
        self.execution_count = execution_count
        self.outputs = outputs or []
        self.metadata = metadata or {}
        
        # AST analysis attributes (for code cells)
        self.assigned_vars: Set[str] = set()
        self.used_vars: Set[str] = set()
        self.imports: List[Dict[str, str]] = []
        self.data_files_read: Set[str] = set()
        self.data_files_written: Set[str] = set()
        self.sql_queries: List[str] = []
        self.dependencies: Set[int] = set()  # Indices of cells this cell depends on

        if self.cell_type == "code":
            self._analyze_code_ast()

    def _analyze_code_ast(self):
        """Analyze Python AST to find variable definitions, variable usages, and data files."""
        # Strip Jupyter IPython magics (e.g. %matplotlib, !pip, %%time)
        clean_lines = []
        for line in self.source.splitlines():
            stripped = line.strip()
            if stripped.startswith(("%", "!", "?")):
                # Check if magic loads a file e.g. %run script.py
                if stripped.startswith("%run "):
                    file_target = stripped.split("%run ", 1)[1].strip()
                    self.data_files_read.add(file_target)
                continue
            clean_lines.append(line)
        
        clean_code = "\n".join(clean_lines)
        if not clean_code.strip():
            return

        try:
            tree = ast.parse(clean_code)
            for node in ast.walk(tree):
                # Variable assignments
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            self.assigned_vars.add(target.id)
                        elif isinstance(target, (ast.Tuple, ast.List)):
                            for elt in target.elts:
                                if isinstance(elt, ast.Name):
                                    self.assigned_vars.add(elt.id)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self.assigned_vars.add(node.name)
                elif isinstance(node, ast.ClassDef):
                    self.assigned_vars.add(node.name)

                # Variable references (Load)
                elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                    self.used_vars.add(node.id)

                # Imports
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        self.imports.append({"module": alias.name, "alias": alias.asname or alias.name})
                        self.assigned_vars.add(alias.asname or alias.name)
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    for alias in node.names:
                        self.imports.append({"module": f"{mod}.{alias.name}", "alias": alias.asname or alias.name})
                        self.assigned_vars.add(alias.asname or alias.name)

                # Function / Method calls for data file reads and writes
                elif isinstance(node, ast.Call):
                    func_name = ""
                    if isinstance(node.func, ast.Name):
                        func_name = node.func.id
                    elif isinstance(node.func, ast.Attribute):
                        func_name = node.func.attr

                    # Check for read_csv, read_parquet, read_json, open(..., 'r')
                    if func_name.startswith("read_") or func_name == "open":
                        if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                            val = node.args[0].value
                            if re.search(r"\.(csv|parquet|json|xlsx|sqlite|db|txt|md)$", val, re.IGNORECASE):
                                self.data_files_read.add(val)
                    
                    # Check for to_csv, to_parquet, to_json, save
                    elif func_name.startswith("to_") or func_name in ("save", "dump"):
                        if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                            val = node.args[0].value
                            if re.search(r"\.(csv|parquet|json|xlsx|sqlite|db|txt|png|jpg|pdf)$", val, re.IGNORECASE):
                                self.data_files_written.add(val)

                # String constants that look like SQL
                elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                    val = node.value.strip()
                    if re.match(r"^(SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|WITH)\s", val, re.IGNORECASE):
                        self.sql_queries.append(val)

        except SyntaxError:
            # Fallback regex search if syntax is invalid/incomplete
            for match in re.finditer(r"['\"]([^'\"]+\.(?:csv|parquet|json|xlsx|pdf))['\"]", self.source, re.IGNORECASE):
                self.data_files_read.add(match.group(1))

    def to_dict(self) -> Dict[str, Any]:
        """Return a dictionary representation of the cell."""
        return {
            "cell_index": self.cell_index,
            "cell_type": self.cell_type,
            "execution_count": self.execution_count,
            "source": self.source,
            "assigned_vars": sorted(list(self.assigned_vars)),
            "used_vars": sorted(list(self.used_vars)),
            "imports": self.imports,
            "data_files_read": sorted(list(self.data_files_read)),
            "data_files_written": sorted(list(self.data_files_written)),
            "sql_queries": self.sql_queries,
            "dependencies": sorted(list(self.dependencies)),
            "output_count": len(self.outputs)
        }


class JupyterNotebookParser:
    """Parses .ipynb files and constructs an execution DAG with cell-level lineage."""

    @classmethod
    def parse_notebook_content(cls, notebook_json_str: str, filename: str = "analysis.ipynb") -> Dict[str, Any]:
        """Parse raw .ipynb JSON text into structured cells and execution DAG."""
        data = json.loads(notebook_json_str)
        raw_cells = data.get("cells", [])
        
        cells: List[NotebookCell] = []
        var_producers: Dict[str, int] = {}  # var_name -> cell_index where defined

        # 1. Parse each cell
        for idx, cell_data in enumerate(raw_cells):
            src = cell_data.get("source", "")
            if isinstance(src, list):
                src = "".join(src)
            
            cell = NotebookCell(
                cell_index=idx,
                cell_type=cell_data.get("cell_type", "code"),
                source=src,
                execution_count=cell_data.get("execution_count"),
                outputs=cell_data.get("outputs", []),
                metadata=cell_data.get("metadata", {})
            )
            cells.append(cell)

        # 2. Build DAG dependencies based on variable definitions & usages
        for cell in cells:
            if cell.cell_type != "code":
                continue

            # Find cell dependencies: which previous cell produced the variables this cell uses?
            for var in cell.used_vars:
                if var in var_producers:
                    producer_idx = var_producers[var]
                    if producer_idx != cell.cell_index:
                        cell.dependencies.add(producer_idx)

            # Record variables produced by this cell
            for var in cell.assigned_vars:
                var_producers[var] = cell.cell_index

        # Aggregate notebook-level data
        all_files_read: Set[str] = set()
        all_files_written: Set[str] = set()
        all_imports: List[Dict[str, str]] = []
        all_sql: List[str] = []

        dag_edges: List[Dict[str, Any]] = []
        for cell in cells:
            all_files_read.update(cell.data_files_read)
            all_files_written.update(cell.data_files_written)
            all_imports.extend(cell.imports)
            all_sql.extend(cell.sql_queries)

            for dep_idx in cell.dependencies:
                dag_edges.append({
                    "from_cell": dep_idx,
                    "to_cell": cell.cell_index,
                    "relation": "produces_variables_for"
                })

        return {
            "format": "jupyter_notebook",
            "filename": filename,
            "total_cells": len(cells),
            "code_cells_count": sum(1 for c in cells if c.cell_type == "code"),
            "markdown_cells_count": sum(1 for c in cells if c.cell_type == "markdown"),
            "cells": [c.to_dict() for c in cells],
            "dag_edges": dag_edges,
            "data_dependencies": sorted(list(all_files_read)),
            "data_outputs": sorted(list(all_files_written)),
            "imports": all_imports,
            "sql_queries": all_sql
        }

    @classmethod
    def ingest_notebook_to_graph(
        cls,
        notebook_json_str: str,
        filename: str,
        storage: StorageBackend
    ) -> Dict[str, Any]:
        """
        Ingest notebook into DataOS:
        Creates parent Notebook DataObject, child CodeCell DataObjects,
        and connects them via CONTAINS and DEPENDS_ON relationships.
        """
        parsed = cls.parse_notebook_content(notebook_json_str, filename)

        # 1. Create parent Notebook DataObject
        notebook_obj = DataObject(
            type=ObjectType.NOTEBOOK.value,
            schema="notebook.v1",
            properties={
                "filename": filename,
                "total_cells": parsed["total_cells"],
                "code_cells_count": parsed["code_cells_count"],
                "data_dependencies": parsed["data_dependencies"],
                "data_outputs": parsed["data_outputs"]
            },
            content=notebook_json_str,
            source=f"file://{filename}"
        )
        storage.save_object(notebook_obj)

        # 2. Create child cell DataObjects
        cell_obj_map: Dict[int, DataObject] = {}
        for cell_dict in parsed["cells"]:
            c_idx = cell_dict["cell_index"]
            cell_obj = DataObject(
                type="code_cell" if cell_dict["cell_type"] == "code" else "markdown_cell",
                schema="notebook_cell.v1",
                properties={
                    "notebook_id": notebook_obj.id,
                    "cell_index": c_idx,
                    "cell_type": cell_dict["cell_type"],
                    "assigned_vars": cell_dict["assigned_vars"],
                    "used_vars": cell_dict["used_vars"],
                    "data_files_read": cell_dict["data_files_read"]
                },
                content=cell_dict["source"],
                source=f"derived://{notebook_obj.id}/cell/{c_idx}"
            )
            storage.save_object(cell_obj)
            cell_obj_map[c_idx] = cell_obj

            # Link notebook -> contains -> cell
            storage.save_relationship(Relationship(
                source=notebook_obj.id,
                target=cell_obj.id,
                relation_type=RelationType.CONTAINS.value,
                confidence=1.0
            ))

        # 3. Create cell-to-cell dependency edges in the graph
        for edge in parsed["dag_edges"]:
            src_cell_obj = cell_obj_map.get(edge["from_cell"])
            tgt_cell_obj = cell_obj_map.get(edge["to_cell"])
            if src_cell_obj and tgt_cell_obj:
                storage.save_relationship(Relationship(
                    source=src_cell_obj.id,
                    target=tgt_cell_obj.id,
                    relation_type=RelationType.DEPENDS_ON.value,
                    confidence=1.0,
                    metadata={"reason": "variable_dependency"}
                ))

        return {
            "notebook_id": notebook_obj.id,
            "filename": filename,
            "cells_created": len(cell_obj_map),
            "dag_edges_created": len(parsed["dag_edges"]),
            "data_dependencies": parsed["data_dependencies"]
        }
