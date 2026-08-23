"""
Embeddings API and AI Classification for DataOS (Rules #47, #49).
Provides embedding model registry, batch processing, and content classification.
"""

from __future__ import annotations
import re
import math
from typing import Dict, Any, List, Optional, Callable
from enum import Enum
from abc import ABC, abstractmethod


# ---- Embeddings Registry ----

class EmbeddingProvider(ABC):
    """Abstract interface for embedding providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the provider name."""
        pass

    @abstractmethod
    def embed(self, texts: List[str]) -> List[List[float]]:
        """Embed a list of texts into vectors."""
        pass

    @abstractmethod
    def dimension(self) -> int:
        """Return the embedding dimension."""
        pass

    @property
    def is_available(self) -> bool:
        return True


class HashEmbeddingProvider(EmbeddingProvider):
    """Lightweight hash-based embedding provider (no external dependencies)."""

    def __init__(self, dimension: int = 128):
        self._dim = dimension

    @property
    def name(self) -> str:
        """Return the provider name."""
        return "hash_v1"

    def dimension(self) -> int:
        """Return the embedding dimension."""
        return self._dim

    def embed(self, texts: List[str]) -> List[List[float]]:
        """Embed texts using hash-based vectors."""
        import hashlib
        results = []
        for text in texts:
            vec = [0.0] * self._dim
            for i in range(self._dim):
                h = hashlib.sha256(f"{text}_{i}".encode()).digest()
                byte_val = h[0]
                vec[i] = (byte_val / 128.0) - 1.0
            norm = math.sqrt(sum(v * v for v in vec))
            if norm > 0:
                vec = [v / norm for v in vec]
            results.append(vec)
        return results


class SentenceTransformerProvider(EmbeddingProvider):
    """Neural embedding provider using sentence-transformers."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self._model_name = model_name
        self._model = None
        self._dim = 384

    @property
    def name(self) -> str:
        """Return the provider name."""
        return f"sentence_transformer_{self._model_name}"

    def dimension(self) -> int:
        """Return the embedding dimension."""
        self._ensure_loaded()
        return self._dim

    @property
    def is_available(self) -> bool:
        """Check if sentence-transformers is installed."""
        try:
            import sentence_transformers
            return True
        except ImportError:
            return False

    def _ensure_loaded(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name)
            self._dim = self._model.get_sentence_embedding_dimension()

    def embed(self, texts: List[str]) -> List[List[float]]:
        """Embed texts using sentence-transformers."""
        self._ensure_loaded()
        embeddings = self._model.encode(texts, show_progress_bar=False)
        return [e.tolist() for e in embeddings]


class EmbeddingRegistry:
    """Registry of available embedding providers."""

    def __init__(self):
        self._providers: Dict[str, EmbeddingProvider] = {}
        self._default: Optional[str] = None

    def register(self, provider: EmbeddingProvider, default: bool = False) -> None:
        """Register an embedding provider."""
        self._providers[provider.name] = provider
        if default or self._default is None:
            self._default = provider.name

    def get(self, name: Optional[str] = None) -> Optional[EmbeddingProvider]:
        """Get a provider by name or the default."""
        return self._providers.get(name or self._default)

    def list_providers(self) -> List[Dict[str, Any]]:
        """List all registered providers with their info."""
        return [
            {"name": p.name, "dimension": p.dimension(), "available": p.is_available}
            for p in self._providers.values()
        ]

    def set_default(self, name: str) -> bool:
        """Set the default provider by name."""
        if name in self._providers:
            self._default = name
            return True
        return False


class EmbeddingEngine:
    """High-level embedding engine with caching and batch processing."""

    def __init__(self, provider: Optional[EmbeddingProvider] = None):
        self._provider = provider or HashEmbeddingProvider(dimension=128)
        self._cache: Dict[str, List[float]] = {}
        self._cache_max = 10000

    @property
    def provider(self) -> EmbeddingProvider:
        """Return the current embedding provider."""
        return self._provider

    def set_provider(self, provider: EmbeddingProvider) -> None:
        """Set a new embedding provider and clear cache."""
        self._provider = provider
        self._cache.clear()

    def embed(self, text: str) -> List[float]:
        """Embed a single text with caching."""
        if text in self._cache:
            return self._cache[text]
        vec = self._provider.embed([text])[0]
        if len(self._cache) < self._cache_max:
            self._cache[text] = vec
        return vec

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed multiple texts with caching."""
        uncached = [t for t in texts if t not in self._cache]
        if uncached:
            new_vecs = self._provider.embed(uncached)
            for t, v in zip(uncached, new_vecs):
                if len(self._cache) < self._cache_max:
                    self._cache[t] = v
        return [self._cache[t] for t in texts]

    def similarity(self, text_a: str, text_b: str) -> float:
        """Compute cosine similarity between two texts."""
        vec_a = self.embed(text_a)
        vec_b = self.embed(text_b)
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        return round(dot, 4)

    def find_nearest(self, query: str, candidates: List[str], top_k: int = 5) -> List[Dict[str, Any]]:
        """Find nearest candidates to a query text."""
        query_vec = self.embed(query)
        candidate_vecs = self.embed_batch(candidates)
        scored = []
        for cand, cvec in zip(candidates, candidate_vecs):
            dot = sum(q * c for q, c in zip(query_vec, cvec))
            scored.append({"text": cand, "score": round(dot, 4)})
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def get_stats(self) -> Dict[str, Any]:
        """Get engine statistics."""
        return {
            "provider": self._provider.name,
            "dimension": self._provider.dimension(),
            "cache_size": len(self._cache),
        }


# ---- AI Classification ----

class ContentType(str, Enum):
    DOCUMENT = "document"
    CODE = "code"
    DATA = "data"
    MEDIA = "media"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class ClassificationRule:
    """A rule for content classification."""

    def __init__(self, name: str, pattern: str = "", keywords: Optional[List[str]] = None,
                 extensions: Optional[List[str]] = None, confidence: float = 0.8):
        self.name = name
        self.pattern = pattern
        self.keywords = keywords or []
        self.extensions = extensions or []
        self.confidence = confidence


class ContentClassifier:
    """Rule-based + heuristic content classifier."""

    def __init__(self):
        self._rules: List[ClassificationRule] = []
        self._custom_classifiers: Dict[str, Callable] = {}
        self._register_defaults()

    def _register_defaults(self):
        self._rules.extend([
            ClassificationRule("python", extensions=[".py"], keywords=["def ", "import ", "class "], confidence=0.95),
            ClassificationRule("javascript", extensions=[".js", ".ts", ".jsx", ".tsx"], keywords=["function", "const ", "=>"], confidence=0.95),
            ClassificationRule("sql", extensions=[".sql"], keywords=["SELECT", "INSERT", "CREATE TABLE"], confidence=0.95),
            ClassificationRule("markdown", extensions=[".md", ".markdown"], keywords=["# ", "## ", "```"], confidence=0.9),
            ClassificationRule("csv", extensions=[".csv", ".tsv"], keywords=[], confidence=0.95),
            ClassificationRule("json", extensions=[".json"], keywords=["{", "["], confidence=0.9),
            ClassificationRule("yaml", extensions=[".yaml", ".yml"], keywords=["---"], confidence=0.9),
            ClassificationRule("image", extensions=[".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"], confidence=0.98),
            ClassificationRule("audio", extensions=[".mp3", ".wav", ".ogg", ".flac"], confidence=0.98),
            ClassificationRule("video", extensions=[".mp4", ".avi", ".mkv", ".mov"], confidence=0.98),
            ClassificationRule("pdf", extensions=[".pdf"], confidence=0.98),
            ClassificationRule("spreadsheet", extensions=[".xlsx", ".xls"], confidence=0.95),
            ClassificationRule("presentation", extensions=[".pptx", ".ppt"], confidence=0.95),
            ClassificationRule("archive", extensions=[".zip", ".tar", ".gz", ".rar", ".7z"], confidence=0.95),
        ])

    def classify_by_filename(self, filename: str) -> Dict[str, Any]:
        """Classify content type by filename extension."""
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        for rule in self._rules:
            if ext in rule.extensions:
                return {
                    "classification": rule.name,
                    "confidence": rule.confidence,
                    "method": "extension",
                    "extension": ext,
                }
        return {"classification": "unknown", "confidence": 0.0, "method": "extension"}

    def classify_by_content(self, content: str) -> Dict[str, Any]:
        """Classify content type by analyzing text patterns."""
        content_lower = content.lower().strip()
        scores: Dict[str, float] = {}

        # Code patterns
        code_score = 0
        if re.search(r"^\s*(def |class |import |from .+ import)", content, re.MULTILINE):
            code_score += 0.4
        if re.search(r"^\s*(function|const |let |var |=>)", content, re.MULTILINE):
            code_score += 0.3
        if "SELECT " in content.upper() and "FROM " in content.upper():
            code_score += 0.4
        scores["code"] = code_score

        # Data patterns
        data_score = 0
        lines = content.split("\n")
        if len(lines) > 1:
            first_line = lines[0]
            comma_count = first_line.count(",")
            if comma_count >= 2:
                data_score += 0.5
        if content.startswith("{") or content.startswith("["):
            try:
                import json
                json.loads(content)
                data_score += 0.4
            except (json.JSONDecodeError, ValueError):
                pass
        scores["data"] = data_score

        # Document patterns
        doc_score = 0
        heading_count = len(re.findall(r"^#{1,6}\s", content, re.MULTILINE))
        if heading_count >= 2:
            doc_score += 0.3
        if "```" in content:
            doc_score += 0.1
        word_count = len(content.split())
        if word_count > 100:
            doc_score += 0.2
        scores["document"] = doc_score

        if not scores:
            return {"classification": "unknown", "confidence": 0.0, "method": "content"}

        best = max(scores, key=scores.get)
        conf = min(scores[best], 1.0)
        if conf < 0.2:
            return {"classification": "unknown", "confidence": conf, "method": "content"}
        return {"classification": best, "confidence": round(conf, 2), "method": "content"}

    def classify(self, filename: str = "", content: str = "") -> Dict[str, Any]:
        """Classify using both filename and content signals."""
        file_result = self.classify_by_filename(filename) if filename else None
        content_result = self.classify_by_content(content) if content else None

        if file_result and file_result["confidence"] >= 0.9:
            return file_result
        if content_result and content_result["confidence"] >= 0.5:
            return content_result
        if file_result:
            return file_result
        return content_result or {"classification": "unknown", "confidence": 0.0, "method": "none"}

    def register_custom(self, name: str, classifier: Callable[[str, str], Dict[str, Any]]) -> None:
        """Register a custom classifier function."""
        self._custom_classifiers[name] = classifier

    def get_stats(self) -> Dict[str, Any]:
        """Get classifier statistics."""
        return {
            "total_rules": len(self._rules),
            "rule_categories": list(set(r.name for r in self._rules)),
            "custom_classifiers": len(self._custom_classifiers),
        }
