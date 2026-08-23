"""
Universal Ingestion & Import Engine for DataOS (Rule #31, Rule #70, Rule #72).
Ingests files (PDF, CSV, JSON, Markdown, Code, Media), preserves raw immutable blobs,
extracts structured metadata, builds universal objects, and discovers initial relationships.
"""

from __future__ import annotations
import os
import datetime
from typing import Dict, Any, List, Optional
from core.object.model import DataObject, ObjectType
from infrastructure.storage.base import StorageBackend
from infrastructure.storage.blob_store import FileBlobStorage
from intelligence.document.doc_parser import DocumentParser
from intelligence.dataset.dataset_parser import DatasetParser
from intelligence.code.ast_analyzer import CodeASTAnalyzer
from intelligence.media import MediaProcessor as MediaParser
from intelligence.discovery.engine import RelationshipDiscoveryEngine


class IngestionEngine:
    """Universal ingestion pipeline transforming files into structured DataOS objects."""

    def __init__(self, storage: StorageBackend, blob_store: Optional[FileBlobStorage] = None):
        self.storage = storage
        self.blob_store = blob_store or FileBlobStorage()
        self.discovery_engine = RelationshipDiscoveryEngine(storage)

    def ingest_file(
        self,
        file_path: str,
        discover_relations: bool = True,
        agent_or_user: str = "system"
    ) -> Dict[str, Any]:
        """Ingest a physical file into DataOS."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        filename = os.path.basename(file_path)
        _, ext = os.path.splitext(filename)
        ext = ext.lower()

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        # Determine object type & parse content
        properties: Dict[str, Any] = {"filename": filename, "extension": ext}
        content: Any = {}
        obj_type = ObjectType.FILE.value
        schema_ref = "file.v1"

        if ext in (".csv", ".tsv"):
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                raw_text = f.read()
            parsed = DatasetParser.parse_csv(raw_text, filename)
            obj_type = ObjectType.DATASET.value
            schema_ref = "dataset.v1"
            properties.update(parsed)
            properties["raw_csv"] = raw_text[:50000]
            content = parsed["sample_rows"]

        elif ext in (".json",):
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                raw_text = f.read()
            parsed = DatasetParser.parse_json(raw_text, filename)
            obj_type = ObjectType.DATASET.value
            schema_ref = "dataset.v1"
            properties.update(parsed)
            content = parsed.get("sample_rows", {})

        elif ext in (".md", ".markdown", ".txt"):
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                raw_text = f.read()
            parsed = DocumentParser.parse_text_or_markdown(raw_text, filename)
            obj_type = ObjectType.DOCUMENT.value
            schema_ref = "document.v1"
            properties.update(parsed)
            content = raw_text

        elif ext in (".py", ".js", ".sql", ".sh"):
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                raw_text = f.read()
            parsed = CodeASTAnalyzer.analyze_python_code(raw_text, filename) if ext == ".py" else {"filename": filename}
            obj_type = ObjectType.CODE.value
            schema_ref = "code.v1"
            properties.update(parsed)
            content = raw_text

        elif ext in (".pdf",):
            with open(file_path, "rb") as f:
                file_bytes = f.read()
            parsed = DocumentParser.parse_pdf_fallback(file_bytes, filename)
            obj_type = ObjectType.DOCUMENT.value
            schema_ref = "document.v1"
            properties.update(parsed)
            content = parsed["preview"]

        elif ext in (".mp4", ".mp3", ".wav", ".vtt", ".srt"):
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                raw_text = f.read() if ext in (".vtt", ".srt") else f"Binary media file {filename}"
            parsed = MediaParser.parse_transcript(raw_text, filename)
            obj_type = ObjectType.MEDIA.value
            schema_ref = "media.v1"
            properties.update(parsed)
            content = parsed.get("segments", [])

        # Create DataObject
        data_obj = DataObject(
            type=obj_type,
            schema=schema_ref,
            properties=properties,
            content=content,
            source=f"file://{os.path.abspath(file_path)}",
            provenance={
                "ingested_by": agent_or_user,
                "ingested_at": now,
                "original_path": os.path.abspath(file_path)
            }
        )

        # Store immutable blob
        blob_meta = self.blob_store.store_file(file_path, data_obj.id)
        data_obj.metadata["blob"] = blob_meta
        data_obj.metadata["content_hash"] = blob_meta["sha256"]

        # Persist object
        saved_obj = self.storage.save_object(data_obj)

        # Automatic relationship discovery
        discovered_rels = []
        if discover_relations:
            discovered_rels = self.discovery_engine.discover_relationships_for_object(saved_obj, auto_persist=True)

        return {
            "object_id": saved_obj.id,
            "object": saved_obj.to_dict(),
            "blob_metadata": blob_meta,
            "relationships_discovered_count": len(discovered_rels),
            "discovered_relationships": [r.to_dict() for r in discovered_rels]
        }
