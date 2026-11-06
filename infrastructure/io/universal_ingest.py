"""
Universal Ingestion Pipeline for DataOS (Rule #7, Rule #51, Rule #54).
Ingests heterogeneous files across all supported formats through a single,
consistent lifecycle: Identification -> Parsing -> Object Creation ->
Concept/Table Extraction -> Graph Relational Inference -> Vector Indexing -> Storage.
"""

from __future__ import annotations
import os
import json
from typing import Dict, Any, List, Optional
from pathlib import Path
from core.object.model import DataObject, ObjectType
from infrastructure.storage.base import StorageBackend
from infrastructure.storage.blob_store import FileBlobStorage
from intelligence.document.rich_doc_parser import RichDocumentExtractor
from intelligence.code.notebook_parser import JupyterNotebookParser
from intelligence.discovery.engine import RelationshipDiscoveryEngine
from engines.search.vector_index import PersistentVectorIndex
from intelligence.code.ast_analyzer import CodeASTAnalyzer
from intelligence.media import MediaProcessor as MediaTranscriptParser


class UniversalIngestionPipeline:
    """Universal multi-format data ingestion pipeline."""

    def __init__(
        self,
        storage: StorageBackend,
        blob_store: Optional[FileBlobStorage] = None,
        db_path: str = "dataos.db",
        allowed_file_root: Optional[str] = None,
    ):
        self.storage = storage
        self.blob_store = blob_store or FileBlobStorage()
        self.discovery = RelationshipDiscoveryEngine(storage)
        self.vector_index = PersistentVectorIndex(db_path=db_path)
        root_value = allowed_file_root or os.environ.get("DATAOS_INGEST_ROOT")
        self.allowed_file_root = Path(root_value).expanduser().resolve() if root_value else None
        if self.allowed_file_root is not None and not self.allowed_file_root.is_dir():
            raise ValueError("DATAOS_INGEST_ROOT must point to an existing directory.")

    def ingest(
        self,
        file_path_or_content: Any,
        filename: Optional[str] = None,
        discover_relations: bool = True
    ) -> Dict[str, Any]:
        """
        Ingest text/bytes content or an explicitly scoped local file.

        Strings are always treated as content, never as filesystem paths.
        PathLike inputs must be a basename inside DATAOS_INGEST_ROOT (or the
        explicit allowed_file_root constructor argument).
        """
        if isinstance(file_path_or_content, os.PathLike):
            if self.allowed_file_root is None:
                raise ValueError(
                    "Path-based ingestion is disabled; configure DATAOS_INGEST_ROOT "
                    "or pass file contents with filename."
                )
            raw_path = os.fspath(file_path_or_content)
            if not isinstance(raw_path, str) or not raw_path or raw_path != os.path.basename(raw_path):
                raise ValueError("Local ingestion accepts only a filename within DATAOS_INGEST_ROOT.")
            resolved_path = (self.allowed_file_root / raw_path).resolve(strict=True)
            if resolved_path.parent != self.allowed_file_root or not resolved_path.is_file():
                raise ValueError("Local ingestion path must resolve to a regular file directly under DATAOS_INGEST_ROOT.")
            fn = filename or resolved_path.name
            raw_content = resolved_path.read_bytes()
        else:
            fn = filename or "unnamed_artifact"
            raw_content = file_path_or_content if isinstance(file_path_or_content, bytes) else str(file_path_or_content)

        if isinstance(raw_content, bytes):
            try:
                content_str = raw_content.decode("utf-8")
            except UnicodeDecodeError:
                content_str = raw_content.decode("latin-1")
        else:
            content_str = raw_content

        ext = os.path.splitext(fn)[1].lower()
        extracted_tables = []
        created_objects: List[DataObject] = []
        primary_object: Optional[DataObject] = None

        # ---------------------------------------------------------------------
        # 1. FORMAT-SPECIFIC DISPATCH & PARSING
        # ---------------------------------------------------------------------
        if ext == ".ipynb":
            # Jupyter Notebook DAG Engine
            res = JupyterNotebookParser.ingest_notebook_to_graph(content_str, fn, self.storage)
            notebook_obj = self.storage.get_object(res["notebook_id"])
            primary_object = notebook_obj
            created_objects.append(notebook_obj)

        elif ext in (".md", ".txt", ".docx", ".pdf"):
            # Rich Document Extraction (Tables, Figures, Citations)
            res = RichDocumentExtractor.ingest_rich_document_to_graph(content_str, fn, self.storage)
            doc_obj = self.storage.get_object(res["document_id"])
            primary_object = doc_obj
            created_objects.append(doc_obj)
            extracted_tables = res.get("table_object_ids", [])

        elif ext in (".csv", ".tsv"):
            import pandas as pd
            import io
            df = pd.read_csv(io.StringIO(content_str))
            dataset_obj = DataObject(
                type=ObjectType.DATASET.value,
                schema="dataset.v1",
                properties={
                    "filename": fn,
                    "table_name": os.path.splitext(fn)[0],
                    "total_rows": len(df),
                    "columns": list(df.columns),
                    "raw_csv": content_str[:50000]
                },
                content=df.head(100).to_dict(orient="records"),
                source=f"file://{fn}"
            )
            saved = self.storage.save_object(dataset_obj)
            primary_object = saved
            created_objects.append(saved)

        elif ext in (".json",):
            try:
                parsed_json = json.loads(content_str)
            except Exception:
                parsed_json = {"raw": content_str}

            json_obj = DataObject(
                type=ObjectType.DATASET.value if isinstance(parsed_json, list) else ObjectType.DOCUMENT.value,
                schema="json.v1",
                properties={"filename": fn},
                content=parsed_json,
                source=f"file://{fn}"
            )
            saved = self.storage.save_object(json_obj)
            primary_object = saved
            created_objects.append(saved)

        elif ext in (".py",):
            analysis = CodeASTAnalyzer.analyze_python_code(content_str, fn)
            code_obj = DataObject(
                type=ObjectType.CODE.value if hasattr(ObjectType, "CODE") else "code",
                schema="code.v1",
                properties={
                    "filename": fn,
                    "imports": analysis.get("imports", []),
                    "functions": analysis.get("functions", []),
                    "classes": analysis.get("classes", []),
                    "data_dependencies": analysis.get("data_dependencies", []),
                    "total_lines": analysis.get("total_lines", 0)
                },
                content=content_str,
                source=f"file://{fn}"
            )
            saved = self.storage.save_object(code_obj)
            primary_object = saved
            created_objects.append(saved)

        elif ext in (".vtt", ".srt"):
            media_result = MediaTranscriptParser.parse_transcript(content_str, fn)
            media_obj = DataObject(
                type=ObjectType.MEDIA.value if hasattr(ObjectType, "MEDIA") else "media",
                schema="media_transcript.v1",
                properties={
                    "filename": fn,
                    "segment_count": media_result.get("segment_count", 0),
                    "total_words": media_result.get("total_words", 0),
                    "preview": media_result.get("preview", "")
                },
                content=media_result.get("segments", []),
                source=f"file://{fn}"
            )
            saved = self.storage.save_object(media_obj)
            primary_object = saved
            created_objects.append(saved)

        else:
            # Generic Text Object
            generic_obj = DataObject(
                type=ObjectType.DOCUMENT.value,
                properties={"filename": fn},
                content=content_str,
                source=f"file://{fn}"
            )
            saved = self.storage.save_object(generic_obj)
            primary_object = saved
            created_objects.append(saved)

        # ---------------------------------------------------------------------
        # 2. PERSISTENT VECTOR INDEXING
        # ---------------------------------------------------------------------
        if primary_object:
            self.vector_index.index_object(primary_object)

        # ---------------------------------------------------------------------
        # 3. AUTOMATIC RELATIONSHIP DISCOVERY ACROSS THE GRAPH
        # ---------------------------------------------------------------------
        discovered_relations_count = 0
        if discover_relations and primary_object:
            discovered = self.discovery.discover_relationships_for_object(primary_object)
            discovered_relations_count = len(discovered)

        return {
            "status": "ingested",
            "filename": fn,
            "format": ext or "raw",
            "primary_object_id": primary_object.id if primary_object else None,
            "primary_object_type": primary_object.type if primary_object else None,
            "created_objects_count": len(created_objects),
            "extracted_tables_count": len(extracted_tables),
            "discovered_relations_count": discovered_relations_count
        }
