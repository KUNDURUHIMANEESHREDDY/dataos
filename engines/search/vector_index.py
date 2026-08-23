"""
Persistent Vector Indexing & Embedding Abstraction for DataOS (Rule #45).
Embeddings are: replaceable, versioned, and recomputable. They are NOT the source of truth.
Provides persistent vector storage in SQLite, fast cosine similarity, and model swapping.
"""

from __future__ import annotations
import sqlite3
import json
import math
import time
import datetime
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Tuple
import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer
from core.object.model import DataObject
from infrastructure.storage.base import StorageBackend


class BaseEmbeddingModel(ABC):
    """Abstract embedding provider interface."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        pass

    @property
    @abstractmethod
    def model_version(self) -> str:
        pass

    @property
    @abstractmethod
    def dimension(self) -> int:
        pass

    @abstractmethod
    def encode(self, texts: List[str]) -> np.ndarray:
        """Encode list of text strings into (N, dimension) numpy float array."""
        pass


class TFIDFVectorEmbeddingModel(BaseEmbeddingModel):
    """Deterministic, fast statistical vector embedding model using MurmurHash3 feature hashing."""

    def __init__(self, dimension: int = 256):
        self._dim = dimension
        self._vectorizer = HashingVectorizer(
            n_features=dimension,
            stop_words="english",
            norm="l2",
            alternate_sign=False
        )

    @property
    def model_name(self) -> str:
        return "tfidf_statistical"

    @property
    def model_version(self) -> str:
        return "v1.0"

    @property
    def dimension(self) -> int:
        return self._dim

    def encode(self, texts: List[str]) -> np.ndarray:
        """Encode texts into L2-normalized feature-hashed vectors."""
        if not texts:
            return np.empty((0, self._dim))

        sparse_matrix = self._vectorizer.transform(texts)
        dense = sparse_matrix.toarray()
        
        # Ensure L2 normalized
        norms = np.linalg.norm(dense, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return dense / norms


class SentenceTransformerEmbeddingModel(BaseEmbeddingModel):
    """Neural embedding model using Sentence Transformers for semantic search."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self._model_name = model_name
        self._model = None
        self._dim = 384  # Default for MiniLM

    def _load_model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(self._model_name)
                self._dim = self._model.get_sentence_embedding_dimension()
            except ImportError:
                raise ImportError(
                    "sentence-transformers is required for neural embeddings: "
                    "pip install sentence-transformers"
                )

    @property
    def model_name(self) -> str:
        return f"sentence_transformer_{self._model_name}"

    @property
    def model_version(self) -> str:
        return "v1.0"

    @property
    def dimension(self) -> int:
        self._load_model()
        return self._dim

    def encode(self, texts: List[str]) -> np.ndarray:
        """Encode texts into L2-normalized sentence transformer embeddings."""
        if not texts:
            self._load_model()
            return np.empty((0, self._dim))
        self._load_model()
        embeddings = self._model.encode(texts, show_progress_bar=False, convert_to_numpy=True)
        # L2 normalize
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return embeddings / norms


class PersistentVectorIndex:
    """Persistent vector index stored in SQLite with version tracking and recomputability."""

    def __init__(
        self,
        db_path: str = "dataos.db",
        embedding_model: Optional[BaseEmbeddingModel] = None
    ):
        self.db_path = db_path
        self.model = embedding_model or TFIDFVectorEmbeddingModel(dimension=128)
        self._mem_conn: Optional[sqlite3.Connection] = None
        if self.db_path == ":memory:":
            self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._mem_conn.row_factory = sqlite3.Row
        self._init_vector_table()

    def _get_connection(self) -> sqlite3.Connection:
        if self.db_path == ":memory:" and self._mem_conn:
            return self._mem_conn
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _close(self, conn: sqlite3.Connection):
        if self.db_path != ":memory:":
            conn.close()

    def close(self):
        """Close the in-memory database connection if open."""
        if self._mem_conn:
            try:
                self._mem_conn.close()
            except Exception:
                pass
            self._mem_conn = None

    def __del__(self):
        self.close()

    def _init_vector_table(self):
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS vector_embeddings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                object_id TEXT NOT NULL,
                model_name TEXT NOT NULL,
                model_version TEXT NOT NULL,
                dimension INTEGER NOT NULL,
                vector_json JSON NOT NULL,
                content_hash TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(object_id, model_name, model_version)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_vec_obj ON vector_embeddings(object_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_vec_model ON vector_embeddings(model_name, model_version)")
        conn.commit()
        self._close(conn)

    def index_object(self, obj: DataObject) -> Dict[str, Any]:
        """Compute and persist vector embedding for a DataObject."""
        text_repr = self._extract_object_text(obj)
        vec = self.model.encode([text_repr])[0]
        content_hash = obj.metadata.get("content_hash", obj.compute_hash())
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO vector_embeddings (
                object_id, model_name, model_version, dimension, vector_json, content_hash, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(object_id, model_name, model_version) DO UPDATE SET
                vector_json = excluded.vector_json,
                dimension = excluded.dimension,
                content_hash = excluded.content_hash,
                updated_at = excluded.updated_at
        """, (
            obj.id,
            self.model.model_name,
            self.model.model_version,
            self.model.dimension,
            json.dumps(vec.tolist()),
            content_hash,
            now
        ))
        conn.commit()
        self._close(conn)

        return {
            "object_id": obj.id,
            "model": self.model.model_name,
            "version": self.model.model_version,
            "dimension": self.model.dimension,
            "indexed_at": now
        }

    def search_similar(
        self,
        query_text: str,
        top_k: int = 10,
        min_similarity: float = 0.05,
        object_type: Optional[str] = None,
        source: Optional[str] = None,
        object_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Search objects by vector cosine similarity with optional filters."""
        query_vec = self.model.encode([query_text])[0]
        
        conn = self._get_connection()
        cursor = conn.cursor()
        query_sql = """
            SELECT object_id, vector_json, model_name, model_version
            FROM vector_embeddings
            WHERE model_name = ? AND model_version = ?
        """
        params: list = [self.model.model_name, self.model.model_version]
        if object_ids:
            placeholders = ",".join("?" * len(object_ids))
            query_sql += f" AND object_id IN ({placeholders})"
            params.extend(object_ids)
        cursor.execute(query_sql, params)
        rows = cursor.fetchall()
        self._close(conn)

        if not rows:
            return []

        results: List[Dict[str, Any]] = []
        for r in rows:
            obj_vec = np.array(json.loads(r["vector_json"]))
            dot = float(np.dot(query_vec, obj_vec))
            if dot >= min_similarity:
                results.append({
                    "object_id": r["object_id"],
                    "similarity": round(dot, 4),
                    "model": r["model_name"]
                })

        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:top_k]

    def index_batch(self, objects: List[DataObject]) -> Dict[str, Any]:
        """Batch-index multiple objects at once for better performance."""
        if not objects:
            return {"indexed": 0}

        corpus = [self._extract_object_text(obj) for obj in objects]
        vectors = self.model.encode(corpus)
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        conn = self._get_connection()
        cursor = conn.cursor()
        count = 0
        for idx, obj in enumerate(objects):
            vec = vectors[idx]
            content_hash = obj.metadata.get("content_hash", obj.compute_hash())
            cursor.execute("""
                INSERT INTO vector_embeddings (
                    object_id, model_name, model_version, dimension, vector_json, content_hash, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(object_id, model_name, model_version) DO UPDATE SET
                    vector_json = excluded.vector_json,
                    dimension = excluded.dimension,
                    content_hash = excluded.content_hash,
                    updated_at = excluded.updated_at
            """, (
                obj.id,
                self.model.model_name,
                self.model.model_version,
                self.model.dimension,
                json.dumps(vec.tolist()),
                content_hash,
                now
            ))
            count += 1

        conn.commit()
        self._close(conn)
        return {"indexed": count, "model": self.model.model_name}

    def delete_embedding(self, object_id: str) -> bool:
        """Remove embedding for a specific object."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM vector_embeddings WHERE object_id = ?", (object_id,))
        conn.commit()
        deleted = cursor.rowcount > 0
        self._close(conn)
        return deleted

    def get_index_stats(self) -> Dict[str, Any]:
        """Get statistics about the vector index."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as total FROM vector_embeddings")
        total = cursor.fetchone()["total"]
        cursor.execute(
            "SELECT model_name, model_version, COUNT(*) as cnt FROM vector_embeddings GROUP BY model_name, model_version"
        )
        by_model = [{"model": r["model_name"], "version": r["model_version"], "count": r["cnt"]} for r in cursor.fetchall()]
        self._close(conn)
        return {"total_embeddings": total, "by_model": by_model}

    def recompute_all(self, storage: StorageBackend) -> Dict[str, Any]:
        """Recompute all embeddings across all objects (Rule #45 Recomputability)."""
        objects = storage.list_objects(limit=10000)
        start_time = time.time()

        # Build corpus & fit model
        corpus = [self._extract_object_text(obj) for obj in objects]
        vectors = self.model.encode(corpus)

        conn = self._get_connection()
        cursor = conn.cursor()
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        for idx, obj in enumerate(objects):
            vec = vectors[idx]
            content_hash = obj.metadata.get("content_hash", obj.compute_hash())
            cursor.execute("""
                INSERT INTO vector_embeddings (
                    object_id, model_name, model_version, dimension, vector_json, content_hash, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(object_id, model_name, model_version) DO UPDATE SET
                    vector_json = excluded.vector_json,
                    content_hash = excluded.content_hash,
                    updated_at = excluded.updated_at
            """, (
                obj.id,
                self.model.model_name,
                self.model.model_version,
                self.model.dimension,
                json.dumps(vec.tolist()),
                content_hash,
                now
            ))

        conn.commit()
        self._close(conn)

        duration_ms = round((time.time() - start_time) * 1000.0, 2)
        return {
            "model": self.model.model_name,
            "version": self.model.model_version,
            "total_recomputed": len(objects),
            "duration_ms": duration_ms
        }

    def _extract_object_text(self, obj: DataObject) -> str:
        parts = [
            obj.type,
            obj.schema,
            str(obj.properties.get("filename", "")),
            str(obj.properties.get("title", "")),
            str(obj.content)[:1500]
        ]
        return " ".join(parts)
