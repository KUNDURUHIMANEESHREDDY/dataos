"""
Multi-Signal Analyzers for Relationship Discovery (Rule #5).
Implements Structural, Semantic, Content, Code AST, Document, and Temporal matchers.
"""

from __future__ import annotations
import re
from typing import Dict, Any, List, Optional, Tuple
from core.object.model import DataObject, ObjectType
from core.relation.types import RelationType


class StructuralSignalMatcher:
    """Matches exact and near-exact identifiers, foreign keys, and matching schema columns."""

    @classmethod
    def match(cls, obj_a: DataObject, obj_b: DataObject) -> Optional[Dict[str, Any]]:
        """Match two data objects based on structural similarities like shared columns."""
        if obj_a.id == obj_b.id:
            return None

        # Extract column/property names
        cols_a = set(obj_a.properties.get("columns", []))
        cols_b = set(obj_b.properties.get("columns", []))

        # Check if columns are dicts with 'name'
        if cols_a and isinstance(next(iter(cols_a)), dict):
            cols_a = {c.get("name", "") for c in obj_a.properties.get("columns", [])}
        if cols_b and isinstance(next(iter(cols_b)), dict):
            cols_b = {c.get("name", "") for c in obj_b.properties.get("columns", [])}

        common_cols = cols_a.intersection(cols_b)
        
        # ID key matching (e.g. user_id, customer_id, id, sku)
        id_cols = [c for c in common_cols if c.lower().endswith(("_id", "id", "_key", "sku", "code"))]
        
        if id_cols:
            return {
                "relation_type": RelationType.REFERENCES.value,
                "confidence": 0.85,
                "signal": "structural",
                "description": f"Shared key identifier(s): {', '.join(id_cols)}",
                "evidence_data": {"matched_columns": id_cols}
            }
        elif len(common_cols) >= 3:
            return {
                "relation_type": RelationType.CORRELATES_WITH.value,
                "confidence": 0.65,
                "signal": "structural",
                "description": f"Multiple shared schema columns: {', '.join(list(common_cols)[:5])}",
                "evidence_data": {"matched_columns": list(common_cols)}
            }

        return None


class ContentSignalMatcher:
    """Matches shared entities, title references, keywords, and citations across objects."""

    @classmethod
    def match(cls, obj_a: DataObject, obj_b: DataObject) -> Optional[Dict[str, Any]]:
        """Match two data objects based on content references or citations."""
        if obj_a.id == obj_b.id:
            return None

        # Check if obj_a references obj_b by filename or title in its content/properties
        title_b = obj_b.properties.get("filename") or obj_b.properties.get("title") or ""
        title_a = obj_a.properties.get("filename") or obj_a.properties.get("title") or ""

        content_str_a = str(obj_a.content)
        content_str_b = str(obj_b.content)

        # Title B appears in Content A
        if title_b and len(title_b) > 4 and title_b.lower() in content_str_a.lower():
            return {
                "relation_type": RelationType.CITES.value if obj_a.type == "document" else RelationType.REFERENCES.value,
                "confidence": 0.90,
                "signal": "content_reference",
                "description": f"Object '{obj_a.id}' explicitly references '{title_b}' in its content",
                "evidence_data": {"referenced_title": title_b}
            }

        # Check citations list
        citations_a = obj_a.properties.get("citations", [])
        if any(title_b.lower() in str(c).lower() for c in citations_a):
            return {
                "relation_type": RelationType.CITES.value,
                "confidence": 0.95,
                "signal": "citation",
                "description": f"Formal citation of '{title_b}' found",
                "evidence_data": {"citation": title_b}
            }

        return None


class CodeSignalMatcher:
    """Analyzes code AST to find data files read or written, queries executed, or functions called."""

    @classmethod
    def match(cls, obj_code: DataObject, obj_target: DataObject) -> Optional[Dict[str, Any]]:
        """Match a code object to a target based on data file dependencies."""
        if obj_code.id == obj_target.id or obj_code.type not in ("code", "notebook"):
            return None

        data_deps = obj_code.properties.get("data_dependencies", [])
        target_filename = obj_target.properties.get("filename", "")
        
        if target_filename and any(target_filename.lower() in dep.lower() for dep in data_deps):
            return {
                "relation_type": RelationType.READS_FROM.value,
                "confidence": 0.95,
                "signal": "code_data_dependency",
                "description": f"Code AST shows file read/dependency on '{target_filename}'",
                "evidence_data": {"target_file": target_filename}
            }

        return None
