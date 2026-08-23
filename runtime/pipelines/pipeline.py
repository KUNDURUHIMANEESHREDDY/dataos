"""
Transformation Pipeline Chains for DataOS (Rule #22).
Implements generic transformation chains:
- Document Pipeline: Document -> Structure -> Concepts -> Graph
- Dataset Pipeline: CSV -> Profiling -> Quality Gates -> Insights
- Code Pipeline: Code -> AST -> Symbols -> Dependency Graph
"""

from __future__ import annotations
import io
import datetime
import pandas as pd
from typing import Dict, Any, List, Optional
from core.object.model import DataObject, ObjectType
from core.relation.model import Relationship, RelationType
from infrastructure.storage.base import StorageBackend
from intelligence.document.doc_parser import DocumentParser
from intelligence.dataset.dataset_parser import DatasetParser
from intelligence.code.ast_analyzer import CodeASTAnalyzer
from engines.profiling.profiler import DataProfiler
from engines.quality.quality_engine import DataQualityEngine


class TransformationPipeline:
    """Executes multi-stage transformation chains producing linked DataObjects."""

    def __init__(self, storage: StorageBackend):
        self.storage = storage

    def run_document_pipeline(self, raw_text: str, filename: str) -> Dict[str, Any]:
        """Chain: Document -> Structure -> Sections & Concepts -> Graph."""
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Step 1: Base document object
        doc_meta = DocumentParser.parse_text_or_markdown(raw_text, filename)
        doc_obj = DataObject(
            type=ObjectType.DOCUMENT.value,
            schema="document.v1",
            properties={
                "filename": filename,
                "title": doc_meta["title"],
                "word_count": doc_meta["word_count"],
                "headings": doc_meta["headings"],
                "citations": doc_meta["citations"]
            },
            content=raw_text,
            source=f"file://{filename}"
        )
        self.storage.save_object(doc_obj)

        # Step 2: Create concept/section objects and link to doc
        concept_objects = []
        for sec in doc_meta["sections"][:5]:
            concept_obj = DataObject(
                type=ObjectType.CONCEPT.value,
                schema="concept.v1",
                properties={"title": sec["title"], "level": sec.get("level", 1)},
                content=sec.get("content", ""),
                source=f"derived://{doc_obj.id}"
            )
            self.storage.save_object(concept_obj)
            concept_objects.append(concept_obj)

            # Link doc -> contains -> concept
            rel = Relationship(
                source=doc_obj.id,
                target=concept_obj.id,
                relation_type=RelationType.CONTAINS.value,
                confidence=1.0,
                provenance={"pipeline": "document_transformation"}
            )
            self.storage.save_relationship(rel)

        return {
            "pipeline": "document_transformation",
            "document_object_id": doc_obj.id,
            "created_concepts_count": len(concept_objects),
            "executed_at": now
        }

    def run_dataset_pipeline(self, raw_csv_text: str, filename: str) -> Dict[str, Any]:
        """Chain: CSV -> Profiling -> Quality -> Insights."""
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        # 1. Parse dataset
        ds_meta = DatasetParser.parse_csv(raw_csv_text, filename)
        df = pd.read_csv(io.StringIO(raw_csv_text))

        dataset_obj = DataObject(
            type=ObjectType.DATASET.value,
            schema="dataset.v1",
            properties={
                "filename": filename,
                "row_count": ds_meta["row_count"],
                "column_count": ds_meta["column_count"],
                "columns": ds_meta["columns"],
                "sample_rows": ds_meta["sample_rows"]
            },
            content=ds_meta["sample_rows"],
            source=f"file://{filename}"
        )
        self.storage.save_object(dataset_obj)

        # 2. Compute profile
        profile_data = DataProfiler.profile_dataframe(df, dataset_name=filename)
        profile_obj = DataObject(
            type=ObjectType.METRIC.value,
            schema="dataset_profile.v1",
            properties={"target_dataset_id": dataset_obj.id, "summary": profile_data["summary"]},
            content=profile_data,
            source=f"dataos://profiler/{dataset_obj.id}"
        )
        self.storage.save_object(profile_obj)

        # Link dataset -> profiles -> profile_obj
        rel_prof = Relationship(
            source=dataset_obj.id,
            target=profile_obj.id,
            relation_type=RelationType.PROFILES.value,
            confidence=1.0
        )
        self.storage.save_relationship(rel_prof)

        # 3. Compute quality report
        quality_rules = [{"type": "row_count_min", "min_rows": 1}]
        for col_name in df.columns:
            quality_rules.append({"type": "not_null", "column": col_name, "max_null_ratio": 0.5})
        quality_obj = DataQualityEngine.evaluate_rules(df, quality_rules, target_object_id=dataset_obj.id)
        self.storage.save_object(quality_obj)

        # Link quality_obj -> evaluates -> dataset
        rel_qual = Relationship(
            source=quality_obj.id,
            target=dataset_obj.id,
            relation_type=RelationType.EVALUATES.value,
            confidence=1.0
        )
        self.storage.save_relationship(rel_qual)

        return {
            "pipeline": "dataset_transformation",
            "dataset_object_id": dataset_obj.id,
            "profile_object_id": profile_obj.id,
            "quality_object_id": quality_obj.id,
            "quality_score": quality_obj.properties.get("quality_score", 100.0),
            "executed_at": now
        }
