"""
Universal DataOS Kernel (DataOSSystem).
The single central orchestration layer unifying all DataOS engines, storage backends,
intelligence parsers, query interfaces, governance, time-travel, and agents.

Architecture:
- Data is the canonical source of truth.
- Persistent SQL storage (PostgreSQL / SQLite) -> Objects & Relations -> Graph Engine -> Compute / Search.
- Strict Zero-Data-Fabrication Grounding on all AI completions.
- Continuous Provenance and Time-Travel across all operations.
"""

from __future__ import annotations
import os
from typing import Dict, Any, List, Optional, Union

# Core Models
from core.object.model import DataObject, ObjectType
from core.relation.model import Relationship, RelationType
from core.permissions.policy import PermissionPolicy, Capability
from core.permissions.sharing_tokens import SubgraphTokenManager
from core.governance.resource_governor import ResourceGovernor, ResourceQuota
from core.versioning.time_travel import TimeTravelEngine

# Infrastructure
from infrastructure.storage.base import StorageBackend
from infrastructure.storage.sqlite_store import SQLiteStorage
from infrastructure.storage.postgres_store import PostgresStorage
from infrastructure.storage.blob_store import FileBlobStorage
from infrastructure.sync.sync_engine import DistributedSyncEngine
from infrastructure.federation.federation_engine import DataOSFederationEngine
from infrastructure.io.universal_ingest import UniversalIngestionPipeline
from infrastructure.io.export_engine import DataOSExporter

# Engines
from engines.graph.engine import GraphEngine
from engines.graph.algorithms import GraphAnalyticsEngine
from engines.graph.recommendations import GraphRecommendationEngine
from engines.search.search_engine import HybridSearchEngine
from engines.search.vector_index import PersistentVectorIndex
from engines.compute.sql_engine import SQLExecutionEngine
from engines.compute.python_sandbox import PythonSandbox
from engines.compute.stats_engine import StatisticalEngine
from engines.profiling.profiler import DataProfiler
from engines.quality.quality_engine import DataQualityEngine
from engines.provenance.explanation_engine import ExplanationEngine
from engines.query.ask_dataos import AskDataOSEngine

# Runtime & Intelligence
from intelligence.discovery.engine import RelationshipDiscoveryEngine
from core.provenance.lineage_engine import LineageEngine
from runtime.grounding.grounder import GroundingEngine
from runtime.agents.orchestrator import MultiAgentPipeline
from runtime.agents.agent import AgentHarness

# New Modules (Session additions)
from intelligence.document.office_parser import DocxParser, PptxParser, XlsxParser, parse_office_document
from infrastructure.storage.cloud_store import S3Storage, GCSStorage, AzureBlobStorage
from infrastructure.io.ingestion_adapters import IngestionAdapterManager
from infrastructure.io.format_export import DataFormatExporter, CSVExporter, ParquetExporter
from engines.search.vector_index import SentenceTransformerEmbeddingModel
from intelligence.semantic.embeddings_api import EmbeddingEngine, EmbeddingRegistry, HashEmbeddingProvider, ContentClassifier
from infrastructure.services.remaining_features import (
    AutoDiscoveryEngine, PrivacyEngine, MetricsSystem, RateLimiter, DashboardCapture,
)


class ObjectNamespace:
    """Namespace for DataObject CRUD and version lifecycle."""
    def __init__(self, storage: StorageBackend):
        self._storage = storage

    def get(self, object_id: str) -> Optional[DataObject]:
        return self._storage.get_object(object_id)

    def save(self, obj: DataObject) -> DataObject:
        return self._storage.save_object(obj)

    def delete(self, object_id: str) -> bool:
        return self._storage.delete_object(object_id)

    def list(self, object_type: Optional[str] = None, limit: int = 100, offset: int = 0) -> List[DataObject]:
        return self._storage.list_objects(object_type=object_type, limit=limit, offset=offset)

    def history(self, object_id: str) -> List[Dict[str, Any]]:
        return self._storage.get_version_history(object_id)


class GraphNamespace:
    """Namespace for graph topology, traversals, algorithms, and recommendations."""
    def __init__(self, storage: StorageBackend):
        self._storage = storage
        self.engine = GraphEngine(storage)
        self.analytics_engine = GraphAnalyticsEngine(storage)
        self.recommendations_engine = GraphRecommendationEngine(storage)

    def create_relation(
        self,
        source_id: str,
        target_id: str,
        relation_type: str = RelationType.REFERENCES.value,
        confidence: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Relationship:
        return self.engine.create_relation(
            source_id=source_id,
            target_id=target_id,
            relation_type=relation_type,
            confidence=confidence,
            metadata=metadata
        )

    def neighbors(self, object_id: str, direction: str = "both") -> List[Dict[str, Any]]:
        return self.engine.get_neighbors(object_id, direction=direction)

    def paths(self, source_id: str, target_id: str, max_depth: int = 5) -> List[List[str]]:
        return self.engine.find_paths(source_id, target_id, max_depth=max_depth)

    def analytics(self) -> Dict[str, Any]:
        return self.analytics_engine.compute_all_metrics()

    def recommendations(self, object_id: str, top_k: int = 10) -> List[Dict[str, Any]]:
        return self.recommendations_engine.recommend_connections(object_id, top_k=top_k)


class DataOS:
    """
    Universal Data Operating System Central Runtime Kernel.
    Exposes clean, intuitive, domain-neutral namespaces.
    """

    def __init__(
        self,
        db_path: str = "dataos.db",
        db_url: Optional[str] = None,
        blob_dir: str = ".dataos_blobs",
        storage_backend: Optional[StorageBackend] = None
    ):
        self.db_path = db_path
        self.db_url = db_url
        self.blob_dir = blob_dir

        # 1. Storage Layer (Postgres / SQLite)
        if storage_backend:
            self.storage = storage_backend
        elif db_url and (db_url.startswith("postgresql://") or db_url.startswith("postgres://")):
            from infrastructure.storage.postgres_store import PostgresStorage
            self.storage = PostgresStorage(connection_string=db_url)
        else:
            self.storage = SQLiteStorage(db_path=self.db_path)

        self.blob_store = FileBlobStorage(root_dir=self.blob_dir)

        # 2. Namespaces
        self.objects = ObjectNamespace(self.storage)
        self.graph = GraphNamespace(self.storage)

        # 3. Engines
        self.sql_engine = SQLExecutionEngine(self.storage)
        self.python_sandbox = PythonSandbox(self.storage)
        self.stats = StatisticalEngine
        self.profiler = DataProfiler
        self.quality = DataQualityEngine
        self.search_engine = HybridSearchEngine(self.storage)
        self.vector_index = PersistentVectorIndex(db_path=self.db_path)
        self.lineage = LineageEngine(self.storage)
        self.grounding = GroundingEngine(self.storage)
        self.time_travel = TimeTravelEngine(self.storage)
        self.sync = DistributedSyncEngine(self.storage)
        self.governor = ResourceGovernor()
        self.tokens = SubgraphTokenManager()
        self.federation = DataOSFederationEngine(self.storage)
        self.multi_agent = MultiAgentPipeline(self.storage)
        self.discovery = RelationshipDiscoveryEngine(self.storage)
        self.explainer = ExplanationEngine(self.storage)
        self.ask_engine = AskDataOSEngine(self.storage, db_path=self.db_path)
        self.ingestion_pipeline = UniversalIngestionPipeline(self.storage, self.blob_store, db_path=self.db_path)
        self.exporter = DataOSExporter(self.storage)

        # New subsystems
        self.embedding_engine = EmbeddingEngine(HashEmbeddingProvider(dimension=128))
        self.classifier = ContentClassifier()
        self.ingestion_adapters = IngestionAdapterManager()
        self.format_exporter = DataFormatExporter
        self.privacy = PrivacyEngine()
        self.metrics = MetricsSystem()
        self.rate_limiter = RateLimiter()
        self.dashboard = DashboardCapture()
        self.discovery_engine = AutoDiscoveryEngine()

    @classmethod
    def from_url(cls, db_url: str, blob_dir: str = ".dataos_blobs") -> DataOS:
        """Factory method to initialize DataOS directly from a database connection URL."""
        return cls(db_url=db_url, blob_dir=blob_dir)

    # -------------------------------------------------------------------------
    # TOP-LEVEL CONVENIENCE SYSTEM APIS
    # -------------------------------------------------------------------------

    def ingest(self, file_path_or_content: Any, filename: Optional[str] = None, discover_relations: bool = True) -> Dict[str, Any]:
        """Ingest any file format (Markdown, PDF, CSV, Notebook, Code, Audio/Video) in one call."""
        return self.ingestion_pipeline.ingest(file_path_or_content, filename=filename, discover_relations=discover_relations)

    def why(self, object_id: str) -> Dict[str, Any]:
        """Explain the complete origin, lineage, and rationale of any object."""
        return self.explainer.explain_why(object_id)

    def impact(self, object_id: str) -> Dict[str, Any]:
        """Explain the downstream breaking impact and blast radius if an object is changed or deleted."""
        return self.explainer.explain_impact(object_id)

    def ask(self, natural_language_query: str) -> Dict[str, Any]:
        """Ask DataOS a system question in natural language with verified zero-fabrication evidence."""
        return self.ask_engine.ask(natural_language_query)

    def sql(self, query: str) -> Dict[str, Any]:
        """Execute real SQL query against registered datasets."""
        return self.sql_engine.execute_sql(query)

    def python(self, code_str: str, input_object_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """Execute safe, sandboxed Python computation against loaded DataObjects."""
        return self.python_sandbox.execute_code(code_str, input_object_ids=input_object_ids)

    def search(self, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
        """Hybrid BM25 + TF-IDF search across objects."""
        return self.search_engine.search(query, limit=top_k)

    def search_vector(self, query_text: str, top_k: int = 10) -> List[Dict[str, Any]]:
        """Persistent cosine similarity vector search."""
        return self.vector_index.search_similar(query_text, top_k=top_k)

    def profile(self, object_id: str) -> Dict[str, Any]:
        """Compute statistical distributions, null ratios, and outliers for a dataset object."""
        obj = self.objects.get(object_id)
        if not obj:
            raise ValueError(f"Object '{object_id}' not found.")
        import pandas as pd
        import io
        df = None
        if isinstance(obj.content, list):
            df = pd.DataFrame(obj.content)
        elif isinstance(obj.properties.get("raw_csv"), str):
            df = pd.read_csv(io.StringIO(obj.properties["raw_csv"]))
        elif isinstance(obj.properties.get("sample_rows"), list):
            df = pd.DataFrame(obj.properties["sample_rows"])

        if df is None:
            raise ValueError(f"Object '{object_id}' is not tabular.")
        return self.profiler.profile_dataframe(df, dataset_name=obj.properties.get("filename", obj.id[:8]))

    # -------------------------------------------------------------------------
    # NEW SUBSYSTEM APIS
    # -------------------------------------------------------------------------

    def embed(self, text: str) -> List[float]:
        """Compute vector embedding for text."""
        return self.embedding_engine.embed(text)

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Compute vector embeddings for multiple texts."""
        return self.embedding_engine.embed_batch(texts)

    def classify(self, filename: str = "", content: str = "") -> Dict[str, Any]:
        """Classify content type by filename and/or content analysis."""
        return self.classifier.classify(filename=filename, content=content)

    def ingest_source(self, source_type: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """Ingest data from an external source (archive, database, API, git)."""
        return self.ingestion_adapters.ingest(source_type, config)

    def export_data(self, data: List[Dict[str, Any]], format: str = "csv", filename: str = "") -> Dict[str, Any]:
        """Export data to CSV or Parquet format."""
        return self.format_exporter.export(data, format, filename)

    def mask(self, value: str) -> str:
        """Apply privacy masking to a string value."""
        return self.privacy.apply_masking(value)

    def check_rate_limit(self, api_key: str) -> Dict[str, Any]:
        """Check API rate limit for a given key."""
        return self.rate_limiter.allow(api_key)

    def close(self):
        """Release all resources (storage connections, vector index)."""
        if hasattr(self, 'storage') and hasattr(self.storage, 'close'):
            self.storage.close()
        if hasattr(self, 'vector_index') and hasattr(self.vector_index, 'close'):
            self.vector_index.close()

    def __del__(self):
        self.close()


# System Alias
DataOSSystem = DataOS
