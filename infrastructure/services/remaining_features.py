"""
Auto-Discovery, Privacy, Metrics, and Rate Limiting for DataOS (Rules #43, #51, #52, #58, #59).
"""

from __future__ import annotations
import re
import math
import time
import hashlib
import datetime
import secrets
from typing import Dict, Any, List, Optional, Callable, Set
from enum import Enum


# ---- Auto-Discovery (Rule #51) ----

class DiscoveryMethod(str, Enum):
    """Methods for dataset discovery."""
    REGISTRY = "registry"
    FILE_SYSTEM = "file_system"
    DATABASE = "database"
    API = "api"
    MANUAL = "manual"


class DatasetCandidate:
    """A candidate dataset discovered during auto-discovery."""

    def __init__(self, name: str, source: str, method: DiscoveryMethod,
                 metadata: Optional[Dict[str, Any]] = None, confidence: float = 0.5):
        self.name = name
        self.source = source
        self.method = method
        self.metadata = metadata or {}
        self.confidence = confidence
        self.discovered_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """Return candidate as dictionary."""
        return {
            "name": self.name, "source": self.source, "method": self.method.value,
            "metadata": self.metadata, "confidence": self.confidence,
            "discovered_at": self.discovered_at,
        }


class AutoDiscoveryEngine:
    """Discovers datasets automatically from configured sources."""

    def __init__(self):
        self._sources: Dict[str, Callable[[], List[DatasetCandidate]]] = {}
        self._discovered: List[DatasetCandidate] = []
        self._known: Set[str] = set()

    def register_source(self, name: str, finder: Callable[[], List[DatasetCandidate]]) -> None:
        """Register a discovery source."""
        self._sources[name] = finder

    def discover(self) -> List[DatasetCandidate]:
        """Run all registered discovery sources."""
        new_candidates = []
        for name, finder in self._sources.items():
            try:
                candidates = finder()
                for c in candidates:
                    if c.name not in self._known:
                        self._known.add(c.name)
                        self._discovered.append(c)
                        new_candidates.append(c)
            except Exception as e:
                continue
        return new_candidates

    def list_discovered(self) -> List[Dict[str, Any]]:
        """Return all discovered candidates."""
        return [c.to_dict() for c in self._discovered]

    def get_stats(self) -> Dict[str, Any]:
        """Return discovery statistics."""
        by_method = {}
        for c in self._discovered:
            m = c.method.value
            by_method[m] = by_method.get(m, 0) + 1
        return {"total_discovered": len(self._discovered), "by_method": by_method, "sources": len(self._sources)}


# ---- Privacy Methods (Rule #43) ----

class PrivacyMethod(str, Enum):
    """Privacy protection methods."""
    K_ANONYMITY = "k_anonymity"
    L_DIVERSITY = "l_diversity"
    DIFFERENTIAL_PRIVACY = "differential_privacy"
    MASKING = "masking"
    TOKENIZATION = "tokenization"


class PrivacyEngine:
    """Privacy protection methods for sensitive data."""

    def __init__(self, epsilon: float = 1.0):
        self.epsilon = epsilon

    def apply_masking(self, value: str, mask_char: str = "*", visible_start: int = 2, visible_end: int = 2) -> str:
        """Mask a string value, keeping first and last N characters visible."""
        if len(value) <= visible_start + visible_end:
            return value
        masked_len = len(value) - visible_start - visible_end
        return value[:visible_start] + mask_char * masked_len + value[-visible_end:]

    def apply_email_masking(self, email: str) -> str:
        """Mask email address preserving domain."""
        if "@" not in email:
            return self.apply_masking(email)
        local, domain = email.split("@", 1)
        if len(local) <= 2:
            masked_local = local[0] + "*" * (len(local) - 1) if local else "*"
        else:
            masked_local = local[0] + "*" * (len(local) - 2) + local[-1]
        return f"{masked_local}@{domain}"

    def apply_k_anonymity(self, records: List[Dict[str, Any]], quasi_identifiers: List[str], k: int = 5) -> Dict[str, Any]:
        """Suppress groups smaller than k for k-anonymity."""
        from collections import Counter
        groups = Counter()
        for rec in records:
            key = tuple(str(rec.get(qi, "")) for qi in quasi_identifiers)
            groups[key] += 1

        suppressed = 0
        kept = []
        for rec in records:
            key = tuple(str(rec.get(qi, "")) for qi in quasi_identifiers)
            if groups[key] >= k:
                kept.append(rec)
            else:
                suppressed += 1

        return {
            "method": "k_anonymity",
            "k": k,
            "original_count": len(records),
            "kept_count": len(kept),
            "suppressed_count": suppressed,
            "records": kept,
        }

    def apply_differential_privacy(self, values: List[float], sensitivity: float = 1.0) -> Dict[str, Any]:
        """Add Laplace noise for differential privacy."""
        import random
        scale = sensitivity / self.epsilon
        noisy_values = []
        for v in values:
            # Laplace distribution via inverse CDF: u - sign(u) * ln(1 - 2|u|) / beta
            u = random.uniform(-0.5, 0.5)
            noise = -scale * (1 if u >= 0 else -1) * math.log(1 - 2 * abs(u)) if u != 0 else 0
            noisy_values.append(round(v + noise, 4))
        return {
            "method": "differential_privacy",
            "epsilon": self.epsilon,
            "sensitivity": sensitivity,
            "original_values": values,
            "noisy_values": noisy_values,
        }

    def apply_tokenization(self, values: List[str]) -> Dict[str, Any]:
        """Replace values with deterministic tokens."""
        tokens = {}
        tokenized = []
        for v in values:
            if v not in tokens:
                tokens[v] = hashlib.sha256(v.encode()).hexdigest()[:16]
            tokenized.append(tokens[v])
        return {
            "method": "tokenization",
            "token_map": tokens,
            "tokenized_values": tokenized,
        }

    def apply_column_masking(self, records: List[Dict[str, Any]], column: str, method: str = "mask") -> List[Dict[str, Any]]:
        """Apply masking to a specific column in all records."""
        result = []
        for rec in records:
            new_rec = dict(rec)
            val = str(new_rec.get(column, ""))
            if method == "mask":
                new_rec[column] = self.apply_masking(val)
            elif method == "email":
                new_rec[column] = self.apply_email_masking(val)
            elif method == "hash":
                new_rec[column] = hashlib.sha256(val.encode()).hexdigest()[:12]
            result.append(new_rec)
        return result


# ---- Metrics System (Rule #58) ----

class MetricType(str, Enum):
    """Metric type identifiers."""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    SUMMARY = "summary"


class MetricDefinition:
    """Definition of a custom metric."""

    def __init__(self, name: str, metric_type: MetricType, description: str = "",
                 unit: str = "", labels: Optional[List[str]] = None):
        self.name = name
        self.metric_type = metric_type
        self.description = description
        self.unit = unit
        self.labels = labels or []
        self.created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """Return metric definition as dictionary."""
        return {
            "name": self.name, "type": self.metric_type.value,
            "description": self.description, "unit": self.unit,
            "labels": self.labels, "created_at": self.created_at,
        }


class MetricsSystem:
    """Custom metrics registry and collection."""

    def __init__(self):
        self._definitions: Dict[str, MetricDefinition] = {}
        self._counters: Dict[str, float] = {}
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, List[float]] = {}
        self._timestamps: Dict[str, str] = {}

    def define(self, name: str, metric_type: MetricType, description: str = "", unit: str = "") -> MetricDefinition:
        """Define a new metric."""
        metric = MetricDefinition(name, metric_type, description, unit)
        self._definitions[name] = metric
        return metric

    def increment(self, name: str, value: float = 1.0) -> None:
        """Increment a counter metric."""
        self._counters[name] = self._counters.get(name, 0) + value
        self._timestamps[name] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    def set_gauge(self, name: str, value: float) -> None:
        """Set a gauge metric value."""
        self._gauges[name] = value
        self._timestamps[name] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    def observe(self, name: str, value: float) -> None:
        """Record a histogram observation."""
        if name not in self._histograms:
            self._histograms[name] = []
        self._histograms[name].append(value)
        self._timestamps[name] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    def get_counter(self, name: str) -> float:
        """Return counter value."""
        return self._counters.get(name, 0)

    def get_gauge(self, name: str) -> Optional[float]:
        """Return gauge value."""
        return self._gauges.get(name)

    def get_histogram(self, name: str) -> Dict[str, float]:
        """Return histogram statistics."""
        values = self._histograms.get(name, [])
        if not values:
            return {"count": 0, "sum": 0, "min": 0, "max": 0, "avg": 0, "p50": 0, "p95": 0, "p99": 0}
        sorted_vals = sorted(values)
        n = len(sorted_vals)
        return {
            "count": n,
            "sum": round(sum(sorted_vals), 4),
            "min": round(sorted_vals[0], 4),
            "max": round(sorted_vals[-1], 4),
            "avg": round(sum(sorted_vals) / n, 4),
            "p50": round(sorted_vals[int(n * 0.5)], 4),
            "p95": round(sorted_vals[int(n * 0.95)], 4),
            "p99": round(sorted_vals[int(n * 0.99)], 4),
        }

    def snapshot(self) -> Dict[str, Any]:
        """Return current metric values."""
        return {
            "counters": dict(self._counters),
            "gauges": dict(self._gauges),
            "histograms": {k: self.get_histogram(k) for k in self._histograms},
        }

    def list_definitions(self) -> List[Dict[str, Any]]:
        """Return all metric definitions."""
        return [d.to_dict() for d in self._definitions.values()]

    def reset(self) -> None:
        """Clear all metrics."""
        self._counters.clear()
        self._gauges.clear()
        self._histograms.clear()
        self._timestamps.clear()


# ---- API Rate Limiting (Rule #59) ----

class RateLimiter:
    """Token bucket rate limiter per API key."""

    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._buckets: Dict[str, List[float]] = {}
        self._stats: Dict[str, int] = {}

    def _clean_bucket(self, key: str) -> None:
        now = time.time()
        if key in self._buckets:
            self._buckets[key] = [t for t in self._buckets[key] if now - t < self.window_seconds]

    def allow(self, api_key: str) -> Dict[str, Any]:
        """Check if a request is allowed for the given API key."""
        self._clean_bucket(api_key)
        current = len(self._buckets.get(api_key, []))

        if current >= self.max_requests:
            self._stats[api_key] = self._stats.get(api_key, 0) + 1
            return {
                "allowed": False,
                "remaining": 0,
                "limit": self.max_requests,
                "window_seconds": self.window_seconds,
                "retry_after_seconds": self._retry_after(api_key),
            }

        self._buckets.setdefault(api_key, []).append(time.time())
        remaining = self.max_requests - current - 1
        return {
            "allowed": True,
            "remaining": remaining,
            "limit": self.max_requests,
            "window_seconds": self.window_seconds,
        }

    def _retry_after(self, api_key: str) -> float:
        if api_key not in self._buckets or not self._buckets[api_key]:
            return 0
        oldest = min(self._buckets[api_key])
        return max(0, round(self.window_seconds - (time.time() - oldest), 1))

    def get_usage(self, api_key: str) -> Dict[str, Any]:
        """Return usage stats for an API key."""
        self._clean_bucket(api_key)
        return {
            "api_key": api_key,
            "current_requests": len(self._buckets.get(api_key, [])),
            "limit": self.max_requests,
            "window_seconds": self.window_seconds,
            "rejected_count": self._stats.get(api_key, 0),
        }

    def reset(self, api_key: Optional[str] = None) -> None:
        """Reset rate limiter state."""
        if api_key:
            self._buckets.pop(api_key, None)
            self._stats.pop(api_key, None)
        else:
            self._buckets.clear()
            self._stats.clear()

    def get_stats(self) -> Dict[str, Any]:
        """Return rate limiting statistics."""
        total_allowed = sum(max(0, self.max_requests - len(v)) for v in self._buckets.values())
        total_rejected = sum(self._stats.values())
        return {
            "total_keys": len(self._buckets),
            "total_rejected": total_rejected,
            "max_requests": self.max_requests,
            "window_seconds": self.window_seconds,
        }


# ---- Dashboard Screenshot (Rule #52) ----

class DashboardCapture:
    """Captures dashboard state as structured metadata (no actual screenshot)."""

    def __init__(self):
        self._snapshots: List[Dict[str, Any]] = []

    def capture(self, dashboard_id: str, title: str, widgets: List[Dict[str, Any]],
                layout: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Capture dashboard state as metadata."""
        snapshot = {
            "dashboard_id": dashboard_id,
            "title": title,
            "widget_count": len(widgets),
            "widgets": widgets,
            "layout": layout or {},
            "captured_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "format": "metadata",
        }
        self._snapshots.append(snapshot)
        return snapshot

    def get_snapshot(self, index: int = -1) -> Optional[Dict[str, Any]]:
        """Return a snapshot by index."""
        if self._snapshots:
            return self._snapshots[index]
        return None

    def list_snapshots(self) -> List[Dict[str, Any]]:
        """Return all snapshots."""
        return self._snapshots.copy()

    def get_stats(self) -> Dict[str, Any]:
        """Return capture statistics."""
        return {"total_snapshots": len(self._snapshots)}
