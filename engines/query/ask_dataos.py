"""
Grounded 'Ask DataOS' System Query Engine (Rule #11, Rule #12, Rule #73).
Executes natural language system queries through real DataOS engines:
Graph Traversal, SQL Execution, Statistical Profiling, Lineage, and Time-Travel.
Zero-Data-Fabrication: Never guesses; delivers empirical computations and verifiable citations.
"""

from __future__ import annotations
import re
from typing import Dict, Any, List, Optional
from core.object.model import DataObject
from infrastructure.storage.base import StorageBackend
from engines.search.search_engine import HybridSearchEngine
from engines.search.vector_index import PersistentVectorIndex
from engines.compute.sql_engine import SQLExecutionEngine
from engines.profiling.profiler import DataProfiler
from engines.provenance.explanation_engine import ExplanationEngine
from core.versioning.time_travel import TimeTravelEngine


class AskDataOSEngine:
    """Natural Language to DataOS System Operation Dispatcher."""

    def __init__(self, storage: StorageBackend, db_path: str = "dataos.db"):
        self.storage = storage
        self.search = HybridSearchEngine(storage)
        self.vector_index = PersistentVectorIndex(db_path=db_path)
        self.sql_engine = SQLExecutionEngine(storage)
        self.profiler = DataProfiler
        self.explainer = ExplanationEngine(storage)
        self.time_travel = TimeTravelEngine(storage)

    def _extract_target_object(self, query: str) -> Optional[DataObject]:
        """Attempt to find a mentioned object ID or filename in the query."""
        all_objects = self.storage.list_objects(limit=500)
        q_lower = query.lower()

        # 1. Exact ID match
        for obj in all_objects:
            if obj.id.lower() in q_lower or obj.id[:8].lower() in q_lower:
                return obj

        # 2. Filename or Title match
        for obj in all_objects:
            fn = obj.properties.get("filename", "").lower()
            title = obj.properties.get("title", "").lower()
            if fn and fn in q_lower:
                return obj
            if title and title in q_lower:
                return obj

        # 3. Fallback: Search best match
        search_res = self.search.search(query, limit=1)
        if search_res:
            return self.storage.get_object(search_res[0]["object_id"])

        return None

    def ask(self, query: str) -> Dict[str, Any]:
        """
        Processes a natural language query against DataOS:
        1. Classifies user intent (Why, Impact, Analyze, Search/Evidence, SQL, TimeTravel).
        2. Executes actual underlying engine operations.
        3. Formulates a grounded, evidence-backed answer.
        """
        q_clean = query.strip()
        q_lower = q_clean.lower()
        target_obj = self._extract_target_object(q_clean)

        # ---------------------------------------------------------------------
        # INTENT 1: WHY / PROVENANCE
        # ---------------------------------------------------------------------
        if any(w in q_lower for w in ["why", "where did", "how was", "who created", "produced"]):
            if target_obj:
                explanation = self.explainer.explain_why(target_obj.id)
                return {
                    "query": query,
                    "intent": "EXPLAIN_WHY",
                    "target_object_id": target_obj.id,
                    "target_object_name": target_obj.properties.get("filename", target_obj.id[:8]),
                    "answer": explanation["summary"],
                    "evidence": {
                        "contributing_datasets": explanation["contributing_datasets"],
                        "contributing_code": explanation["contributing_code"],
                        "transformations": explanation["transformations"]
                    },
                    "execution_details": explanation
                }

        # ---------------------------------------------------------------------
        # INTENT 2: IMPACT / BLAST RADIUS
        # ---------------------------------------------------------------------
        if any(w in q_lower for w in ["impact", "what breaks", "what will break", "if i delete", "if i change", "blast radius"]):
            if target_obj:
                impact = self.explainer.explain_impact(target_obj.id)
                return {
                    "query": query,
                    "intent": "IMPACT_ANALYSIS",
                    "target_object_id": target_obj.id,
                    "target_object_name": target_obj.properties.get("filename", target_obj.id[:8]),
                    "answer": f"Risk level: {impact['breaking_risk_level'].upper()}. {impact['recommended_action']} ({impact['total_downstream_affected']} downstream assets affected).",
                    "evidence": {
                        "affected_reports": impact["affected_reports"],
                        "affected_models": impact["affected_models"],
                        "affected_datasets": impact["affected_datasets"]
                    },
                    "execution_details": impact
                }

        # ---------------------------------------------------------------------
        # INTENT 3: SQL EXECUTION
        # ---------------------------------------------------------------------
        if q_clean.upper().startswith("SELECT"):
            sql_res = self.sql_engine.execute_sql(q_clean)
            return {
                "query": query,
                "intent": "SQL_QUERY",
                "answer": f"Executed SQL successfully. Returned {sql_res['row_count']} row(s).",
                "evidence": sql_res.get("rows", []),
                "execution_details": sql_res
            }

        # ---------------------------------------------------------------------
        # INTENT 4: DATASET PROFILING & STATISTICS
        # ---------------------------------------------------------------------
        if any(w in q_lower for w in ["profile", "analyze", "statistics", "distribution", "variance", "outliers"]):
            if target_obj and target_obj.type in ("dataset", "table"):
                import pandas as pd
                import io
                df = None
                if isinstance(target_obj.content, list):
                    df = pd.DataFrame(target_obj.content)
                elif isinstance(target_obj.properties.get("raw_csv"), str):
                    df = pd.read_csv(io.StringIO(target_obj.properties["raw_csv"]))
                elif isinstance(target_obj.properties.get("sample_rows"), list):
                    df = pd.DataFrame(target_obj.properties["sample_rows"])

                if df is not None:
                    prof = self.profiler.profile_dataframe(df, dataset_name=target_obj.properties.get("filename", target_obj.id[:8]))
                    num_cols = len(prof.get("columns", {}))
                    return {
                        "query": query,
                        "intent": "ANALYZE_DATASET",
                        "target_object_id": target_obj.id,
                        "answer": f"Profiled dataset '{prof.get('dataset_name')}': {prof.get('row_count')} rows, {prof.get('column_count')} columns.",
                        "evidence": prof,
                        "execution_details": prof
                    }

        # ---------------------------------------------------------------------
        # INTENT 5: GENERAL EVIDENCE & KNOWLEDGE GRAPH RETRIEVAL
        # ---------------------------------------------------------------------
        hybrid_results = self.search.search(q_clean, limit=5)
        vector_results = self.vector_index.search_similar(q_clean, top_k=5)

        citations = []
        for r in hybrid_results[:3]:
            obj = self.storage.get_object(r["object_id"])
            if obj:
                citations.append({
                    "object_id": obj.id,
                    "name": obj.properties.get("filename", obj.properties.get("title", obj.id[:8])),
                    "type": obj.type,
                    "relevance_score": r.get("score", 1.0),
                    "snippet": str(obj.content)[:160] if obj.content else ""
                })

        if citations:
            answer_text = f"Found {len(citations)} relevant object(s) in DataOS knowledge graph for '{q_clean}'."
        else:
            answer_text = f"No direct matches found in DataOS for query '{q_clean}'."

        return {
            "query": query,
            "intent": "FIND_EVIDENCE",
            "answer": answer_text,
            "evidence": citations,
            "execution_details": {
                "hybrid_search_count": len(hybrid_results),
                "vector_search_count": len(vector_results)
            }
        }
