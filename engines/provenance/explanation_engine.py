"""
Explanation & Impact Analysis Engine for DataOS (Why? & Impact APIs).
Explains exactly where any object came from, what produced it, which transformations
happened, and computes the downstream blast radius if modified or deleted.
"""

from __future__ import annotations
from typing import Dict, Any, List, Optional, Set
from core.object.model import DataObject
from core.relation.model import Relationship, RelationType
from infrastructure.storage.base import StorageBackend
from engines.graph.engine import GraphEngine
from core.provenance.lineage_engine import LineageEngine


class ExplanationEngine:
    """Answers 'Why does this exist?' and 'What breaks if I change this?' with verifiable graph evidence."""

    def __init__(self, storage: StorageBackend):
        self.storage = storage
        self.graph = GraphEngine(storage)
        self.lineage = LineageEngine(storage)

    def explain_why(self, object_id: str) -> Dict[str, Any]:
        """
        Explain the exact origin, lineage, and rationale for an object:
        - What produced it?
        - What data/files were used?
        - Which transformations happened?
        - Which author or AI model was involved?
        """
        obj = self.storage.get_object(object_id)
        if not obj:
            return {"error": f"Object '{object_id}' not found in DataOS."}

        obj_name = obj.properties.get("filename") or obj.properties.get("title") or obj.properties.get("name") or obj.id[:8]

        # 1. Inspect direct object provenance
        prov = obj.provenance or {}
        created_by = prov.get("created_by") or prov.get("created_by_agent") or "system"
        input_sources = prov.get("input_sources", [])
        transformations = prov.get("transformations", [])
        zero_fab = prov.get("zero_fabrication_checked", False)

        # 2. Multi-hop upstream lineage
        lineage_tree = self.lineage.trace_upstream_lineage(object_id, max_depth=5)
        ancestor_ids = [
            node["object_id"] for node in lineage_tree.get("lineage_nodes", [])
            if node.get("object_id") != object_id
        ]
        
        # 3. Categorize contributing upstream entities
        contributing_datasets = []
        contributing_code = []
        contributing_documents = []
        contributing_files = list(input_sources)

        for anc_id in ancestor_ids:
            anc_obj = self.storage.get_object(anc_id)
            if not anc_obj:
                continue
            anc_name = anc_obj.properties.get("filename") or anc_obj.properties.get("title") or anc_id[:8]
            if anc_obj.source and anc_obj.source not in contributing_files:
                contributing_files.append(anc_obj.source)

            if anc_obj.type in ("dataset", "table"):
                contributing_datasets.append({"id": anc_id, "name": anc_name, "type": anc_obj.type})
            elif anc_obj.type == "code":
                contributing_code.append({"id": anc_id, "name": anc_name, "type": anc_obj.type})
            elif anc_obj.type == "document":
                contributing_documents.append({"id": anc_id, "name": anc_name, "type": anc_obj.type})

        # 4. Generate structured summary explanation
        summary_parts = [
            f"Object '{obj_name}' (type: {obj.type}, version: {obj.version}) was produced by {created_by}."
        ]
        if contributing_datasets:
            d_names = [d["name"] for d in contributing_datasets]
            summary_parts.append(f"It directly utilizes data from: {', '.join(d_names)}.")
        if contributing_code:
            c_names = [c["name"] for c in contributing_code]
            summary_parts.append(f"It was computed via script(s): {', '.join(c_names)}.")
        if transformations:
            summary_parts.append(f"Underwent {len(transformations)} verifiable transformation step(s).")
        if zero_fab:
            summary_parts.append("Grounding validation: zero fabricated claims verified.")

        return {
            "object_id": object_id,
            "object_name": obj_name,
            "object_type": obj.type,
            "version": obj.version,
            "schema": obj.schema,
            "created_at": obj.timestamps.created_at,
            "author_or_agent": created_by,
            "summary": " ".join(summary_parts),
            "contributing_files": contributing_files,
            "contributing_datasets": contributing_datasets,
            "contributing_code": contributing_code,
            "contributing_documents": contributing_documents,
            "transformations": transformations,
            "zero_fabrication_verified": zero_fab,
            "upstream_lineage": lineage_tree
        }

    def explain_impact(self, object_id: str) -> Dict[str, Any]:
        """
        Explain the downstream blast radius if this object is modified or deleted:
        - What breaks?
        - Which reports, datasets, and models depend on it?
        - What is the breaking risk level?
        """
        obj = self.storage.get_object(object_id)
        if not obj:
            return {"error": f"Object '{object_id}' not found in DataOS."}

        obj_name = obj.properties.get("filename") or obj.properties.get("title") or obj.properties.get("name") or obj.id[:8]

        # Traversal of downstream impact (outgoing derivation chain)
        impact_tree = self.lineage.trace_downstream_impact(object_id, max_depth=10)
        impacted_ids = set(
            node["object_id"] for node in impact_tree.get("impacted_nodes", [])
        )

        # Also collect direct reverse-dependency edges (things that DEPEND_ON / READS_FROM this object)
        incoming_rels = self.storage.list_relationships(target_id=object_id)
        reverse_dep_rel_types = {
            "depends_on", "reads_from", "derived_from", "transforms_to"
        }
        for rel in incoming_rels:
            if rel.relation_type.lower() in reverse_dep_rel_types:
                impacted_ids.add(rel.source)

        impacted_ids.discard(object_id)  # never include self

        affected_reports = []
        affected_models = []
        affected_datasets = []
        affected_code = []

        for imp_id in impacted_ids:
            imp_obj = self.storage.get_object(imp_id)
            if not imp_obj:
                continue
            imp_name = imp_obj.properties.get("filename") or imp_obj.properties.get("title") or imp_id[:8]
            entry = {"id": imp_id, "name": imp_name, "type": imp_obj.type}

            if imp_obj.type in ("report", "document"):
                affected_reports.append(entry)
            elif imp_obj.type == "model":
                affected_models.append(entry)
            elif imp_obj.type in ("dataset", "table"):
                affected_datasets.append(entry)
            elif imp_obj.type == "code":
                affected_code.append(entry)

        total_affected = len(impacted_ids)
        if total_affected == 0:
            risk = "low"
            advice = "Safe to modify or delete; no downstream dependencies detected."
        elif total_affected <= 2:
            risk = "medium"
            advice = f"Modifying this object will require re-evaluating {total_affected} downstream dependent object(s)."
        elif total_affected <= 5:
            risk = "high"
            advice = f"High blast radius: {total_affected} downstream assets (including reports/models) depend on this object."
        else:
            risk = "critical"
            advice = f"Critical dependency hub: {total_affected} downstream assets will be impacted. Create a new version rather than mutating."

        return {
            "object_id": object_id,
            "object_name": obj_name,
            "object_type": obj.type,
            "total_downstream_affected": total_affected,
            "breaking_risk_level": risk,
            "recommended_action": advice,
            "affected_reports": affected_reports,
            "affected_models": affected_models,
            "affected_datasets": affected_datasets,
            "affected_code": affected_code,
            "downstream_impact_tree": impact_tree
        }
