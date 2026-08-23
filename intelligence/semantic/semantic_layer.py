"""
Semantic Abstraction Layer for DataOS (Rule #13).
User-defined domain-agnostic semantic dictionary, synonyms, formulas, and metric mappings.
"""

from __future__ import annotations
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field


@dataclass
class SemanticTerm:
    """A semantic term with synonyms, definition, and optional formula."""
    name: str
    synonyms: List[str] = field(default_factory=list)
    definition: str = ""
    unit: Optional[str] = None
    formula: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def matches(self, term: str) -> bool:
        """Check if a term matches this semantic term or its synonyms."""
        clean = term.strip().lower().replace("_", " ")
        name_clean = self.name.strip().lower().replace("_", " ")
        if clean == name_clean:
            return True
        for syn in self.synonyms:
            if clean == syn.strip().lower().replace("_", " "):
                return True
        return False


class SemanticLayer:
    """Manages business definitions, synonyms, and metric calculations."""

    def __init__(self):
        self.terms: Dict[str, SemanticTerm] = {}

    def register_term(
        self,
        name: str,
        synonyms: Optional[List[str]] = None,
        definition: str = "",
        unit: Optional[str] = None,
        formula: Optional[str] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> SemanticTerm:
        """Register a new semantic term."""
        term = SemanticTerm(
            name=name,
            synonyms=synonyms or [],
            definition=definition,
            unit=unit,
            formula=formula,
            tags=tags or [],
            metadata=metadata or {}
        )
        self.terms[name.strip().lower()] = term
        return term

    def resolve_term(self, candidate_name: str) -> Optional[SemanticTerm]:
        """Resolve a column/entity name against registered semantic definitions."""
        for term in self.terms.values():
            if term.matches(candidate_name):
                return term
        return None

    def list_terms(self) -> List[Dict[str, Any]]:
        """List all registered semantic terms."""
        return [
            {
                "name": t.name,
                "synonyms": t.synonyms,
                "definition": t.definition,
                "unit": t.unit,
                "formula": t.formula,
                "tags": t.tags
            }
            for t in self.terms.values()
        ]
