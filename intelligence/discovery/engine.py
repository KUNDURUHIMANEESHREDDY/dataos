"""
Automatic Relationship Discovery Engine for DataOS (Rule #5, Rule #9).
Scans objects across multi-signal matchers, computes confidence scores,
and establishes traceable relationships backed by concrete evidence.
"""

from __future__ import annotations
import datetime
from typing import Dict, Any, List, Optional
from core.object.model import DataObject
from core.relation.model import Relationship, RelationType
from infrastructure.storage.base import StorageBackend
from .signals import StructuralSignalMatcher, ContentSignalMatcher, CodeSignalMatcher


class RelationshipDiscoveryEngine:
    """Discovers relationships across DataOS objects using multi-signal analysis."""

    def __init__(self, storage: StorageBackend):
        self.storage = storage

    def discover_relationships_for_object(
        self,
        target_obj: DataObject,
        all_objects: Optional[List[DataObject]] = None,
        auto_persist: bool = True
    ) -> List[Relationship]:
        """Discover and optionally persist relationships for a specific object against the system."""
        if all_objects is None:
            all_objects = self.storage.list_objects(limit=1000)

        discovered: List[Relationship] = []

        for other_obj in all_objects:
            if other_obj.id == target_obj.id:
                continue

            # Run matchers
            match = (
                CodeSignalMatcher.match(target_obj, other_obj) or
                CodeSignalMatcher.match(other_obj, target_obj) or
                ContentSignalMatcher.match(target_obj, other_obj) or
                ContentSignalMatcher.match(other_obj, target_obj) or
                StructuralSignalMatcher.match(target_obj, other_obj)
            )

            if match:
                rel = Relationship(
                    source=target_obj.id,
                    target=other_obj.id,
                    relation_type=match["relation_type"],
                    confidence=match["confidence"],
                    metadata={"discovered_by": "multi_signal_engine"},
                    provenance={
                        "discovery_method": match["signal"],
                        "discovered_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
                    }
                )
                rel.add_evidence(
                    signal_type=match["signal"],
                    description=match["description"],
                    score=match["confidence"],
                    data=match.get("evidence_data", {})
                )

                if auto_persist:
                    self.storage.save_relationship(rel)
                discovered.append(rel)

        return discovered

    def discover_all(self, auto_persist: bool = True) -> List[Relationship]:
        """Run full cross-discovery pass across all objects in storage."""
        all_objects = self.storage.list_objects(limit=5000)
        total_discovered = []
        
        for idx, obj_a in enumerate(all_objects):
            for obj_b in all_objects[idx + 1:]:
                # Check A -> B or B -> A
                match_ab = (
                    CodeSignalMatcher.match(obj_a, obj_b) or
                    ContentSignalMatcher.match(obj_a, obj_b) or
                    StructuralSignalMatcher.match(obj_a, obj_b)
                )
                if match_ab:
                    rel = Relationship(
                        source=obj_a.id,
                        target=obj_b.id,
                        relation_type=match_ab["relation_type"],
                        confidence=match_ab["confidence"],
                        metadata={"discovered_by": "multi_signal_engine"},
                        provenance={
                            "discovery_method": match_ab["signal"],
                            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
                        }
                    )
                    rel.add_evidence(
                        signal_type=match_ab["signal"],
                        description=match_ab["description"],
                        score=match_ab["confidence"],
                        data=match_ab.get("evidence_data", {})
                    )
                    if auto_persist:
                        self.storage.save_relationship(rel)
                    total_discovered.append(rel)

        return total_discovered
