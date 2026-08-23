"""
Observability Engine for DataOS (Rule #41).
OpenTelemetry-compatible structured traces, metrics, and logging.
Provides: Logs, Metrics (counters/histograms/gauges), Traces with span hierarchy.
"""

from __future__ import annotations
import time
import uuid
import json
import datetime
import contextlib
import threading
import statistics
from typing import Dict, Any, List, Optional, Callable
from enum import Enum


# ---------------------------------------------------------------------------
# Log Levels
# ---------------------------------------------------------------------------
class LogLevel(str, Enum):
    """Log severity levels."""
    DEBUG = "debug"
    INFO = "info"
    WARN = "warn"
    ERROR = "error"
    FATAL = "fatal"


# ---------------------------------------------------------------------------
# Structured Log Entry
# ---------------------------------------------------------------------------
class LogEntry:
    """A single structured log record."""

    def __init__(
        self,
        level: LogLevel,
        message: str,
        logger: str = "dataos",
        trace_id: Optional[str] = None,
        span_id: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ):
        self.entry_id = str(uuid.uuid4())[:12]
        self.timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.level = level
        self.message = message
        self.logger = logger
        self.trace_id = trace_id
        self.span_id = span_id
        self.attributes = attributes or {}

    def to_dict(self) -> Dict[str, Any]:
        """Return log entry as dictionary."""
        return {
            "entry_id": self.entry_id,
            "timestamp": self.timestamp,
            "level": self.level.value,
            "message": self.message,
            "logger": self.logger,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "attributes": self.attributes,
        }


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
class MetricType(str, Enum):
    """Metric type identifiers."""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


class MetricPoint:
    """Single metric data point."""

    def __init__(self, name: str, value: float, labels: Optional[Dict[str, str]] = None):
        self.name = name
        self.value = value
        self.labels = labels or {}
        self.timestamp = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """Return metric point as dictionary."""
        return {
            "name": self.name,
            "value": self.value,
            "labels": self.labels,
            "timestamp": self.timestamp,
        }


class Counter:
    """Monotonically increasing counter."""

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self._value = 0.0
        self._lock = threading.Lock()

    def inc(self, amount: float = 1.0) -> None:
        """Increment counter by amount."""
        with self._lock:
            self._value += amount

    def get_value(self) -> float:
        """Return current counter value."""
        with self._lock:
            return self._value

    def to_dict(self) -> Dict[str, Any]:
        """Return counter as dictionary."""
        return {"name": self.name, "type": "counter", "value": self.get_value(), "description": self.description}


class Gauge:
    """Gauge that can go up and down."""

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self._value = 0.0
        self._lock = threading.Lock()

    def set(self, value: float) -> None:
        """Set gauge value."""
        with self._lock:
            self._value = value

    def inc(self, amount: float = 1.0) -> None:
        """Increment gauge by amount."""
        with self._lock:
            self._value += amount

    def dec(self, amount: float = 1.0) -> None:
        """Decrement gauge by amount."""
        with self._lock:
            self._value -= amount

    def get_value(self) -> float:
        """Return current gauge value."""
        with self._lock:
            return self._value

    def to_dict(self) -> Dict[str, Any]:
        """Return gauge as dictionary."""
        return {"name": self.name, "type": "gauge", "value": self.get_value(), "description": self.description}


class Histogram:
    """Histogram tracking distribution of values."""

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self._values: List[float] = []
        self._lock = threading.Lock()

    def observe(self, value: float) -> None:
        """Record a value observation."""
        with self._lock:
            self._values.append(value)

    def get_value(self) -> Dict[str, float]:
        """Return histogram statistics."""
        with self._lock:
            if not self._values:
                return {"count": 0, "sum": 0, "min": 0, "max": 0, "mean": 0, "p50": 0, "p95": 0, "p99": 0}
            vals = sorted(self._values)
            n = len(vals)
            return {
                "count": n,
                "sum": sum(vals),
                "min": vals[0],
                "max": vals[-1],
                "mean": statistics.mean(vals),
                "median": statistics.median(vals),
                "p50": vals[int(n * 0.5)] if n > 0 else 0,
                "p95": vals[int(n * 0.95)] if n > 1 else vals[-1],
                "p99": vals[int(n * 0.99)] if n > 1 else vals[-1],
                "stdev": statistics.stdev(vals) if n > 1 else 0,
            }

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "type": "histogram", "stats": self.get_value(), "description": self.description}


# ---------------------------------------------------------------------------
# TraceSpan (enhanced)
# ---------------------------------------------------------------------------
class TraceSpan:
    """Individual execution span with OpenTelemetry-compatible fields."""

    def __init__(
        self,
        name: str,
        trace_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ):
        self.span_id = str(uuid.uuid4())[:16]
        self.trace_id = trace_id or str(uuid.uuid4())
        self.parent_span_id = parent_span_id
        self.name = name
        self.attributes = attributes or {}
        self.events: List[Dict[str, Any]] = []
        self.start_time = time.time()
        self.end_time: Optional[float] = None
        self.duration_ms: Optional[float] = None
        self.status = "UNSET"
        self.error_message: Optional[str] = None
        self.resource: Dict[str, Any] = {"service.name": "dataos", "service.version": "1.0.0"}

    def add_event(self, name: str, attributes: Optional[Dict[str, Any]] = None) -> None:
        """Add an event to the span."""
        self.events.append({
            "name": name,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "attributes": attributes or {},
        })

    def set_attribute(self, key: str, value: Any) -> None:
        """Set a span attribute."""
        self.attributes[key] = value

    def set_status(self, status: str, error: Optional[str] = None) -> None:
        """Set span status and optional error message."""
        self.status = status
        if error:
            self.error_message = error

    def end(self, status: str = "OK", error: Optional[str] = None) -> None:
        """End the span and compute duration."""
        self.end_time = time.time()
        self.duration_ms = (self.end_time - self.start_time) * 1000.0
        self.status = status
        if error:
            self.error_message = error

    def to_dict(self) -> Dict[str, Any]:
        """Return span as dictionary."""
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "status": self.status,
            "duration_ms": round(self.duration_ms, 3) if self.duration_ms is not None else None,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "attributes": self.attributes,
            "events": self.events,
            "resource": self.resource,
            "error_message": self.error_message,
        }


# ---------------------------------------------------------------------------
# Observability Engine
# ---------------------------------------------------------------------------
class ObservabilityEngine:
    """
    Central observability hub combining logs, metrics, and traces.
    Thread-safe. Compatible with OpenTelemetry data model.
    """

    def __init__(self, service_name: str = "dataos", max_logs: int = 10000, max_spans: int = 5000):
        self.service_name = service_name
        self._logs: List[LogEntry] = []
        self._spans: List[TraceSpan] = []
        self._metrics: Dict[str, Any] = {}
        self._max_logs = max_logs
        self._max_spans = max_spans
        self._lock = threading.Lock()
        self._subscribers: List[Callable[[Dict[str, Any]], None]] = []

    # -- Logging --
    def log(
        self,
        level: LogLevel,
        message: str,
        logger: str = "dataos",
        trace_id: Optional[str] = None,
        span_id: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> LogEntry:
        """Log a message at the specified level."""
        entry = LogEntry(level=level, message=message, logger=logger, trace_id=trace_id, span_id=span_id, attributes=attributes)
        with self._lock:
            self._logs.append(entry)
            if len(self._logs) > self._max_logs:
                self._logs = self._logs[-self._max_logs // 2:]
        self._notify_subscribers(entry.to_dict())
        return entry

    def debug(self, message: str, **kwargs) -> LogEntry:
        """Log a debug message."""
        return self.log(LogLevel.DEBUG, message, **kwargs)

    def info(self, message: str, **kwargs) -> LogEntry:
        """Log an info message."""
        return self.log(LogLevel.INFO, message, **kwargs)

    def warn(self, message: str, **kwargs) -> LogEntry:
        """Log a warning message."""
        return self.log(LogLevel.WARN, message, **kwargs)

    def error(self, message: str, **kwargs) -> LogEntry:
        """Log an error message."""
        return self.log(LogLevel.ERROR, message, **kwargs)

    def fatal(self, message: str, **kwargs) -> LogEntry:
        """Log a fatal message."""
        return self.log(LogLevel.FATAL, message, **kwargs)

    def get_logs(
        self,
        level: Optional[LogLevel] = None,
        logger: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Return filtered log entries."""
        with self._lock:
            logs = list(self._logs)
        if level:
            logs = [l for l in logs if l.level == level]
        if logger:
            logs = [l for l in logs if l.logger == logger]
        return [l.to_dict() for l in logs[-limit:]]

    # -- Tracing --
    @contextlib.contextmanager
    def span(
        self,
        name: str,
        trace_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ):
        """Create and manage a trace span."""
        s = TraceSpan(name=name, trace_id=trace_id, parent_span_id=parent_span_id, attributes=attributes)
        try:
            yield s
            s.end(status="OK")
        except Exception as e:
            s.end(status="ERROR", error=str(e))
            raise
        finally:
            with self._lock:
                self._spans.append(s)
                if len(self._spans) > self._max_spans:
                    self._spans = self._spans[-self._max_spans // 2:]

    def get_spans(
        self,
        trace_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Return filtered trace spans."""
        with self._lock:
            spans = list(self._spans)
        if trace_id:
            spans = [s for s in spans if s.trace_id == trace_id]
        return [s.to_dict() for s in spans[-limit:]]

    def get_trace_tree(self, trace_id: str) -> List[Dict[str, Any]]:
        """Build a tree structure for a trace."""
        with self._lock:
            spans = [s for s in self._spans if s.trace_id == trace_id]
        span_map = {s.span_id: s.to_dict() for s in spans}
        roots = []
        children_map: Dict[str, List[Dict[str, Any]]] = {}
        for sid, sdata in span_map.items():
            pid = sdata.get("parent_span_id")
            if pid and pid in span_map:
                children_map.setdefault(pid, []).append(sdata)
            else:
                roots.append(sdata)
        for sdata in span_map.values():
            sid = sdata["span_id"]
            if sid in children_map:
                sdata["children"] = children_map[sid]
        return roots

    # -- Metrics --
    def counter(self, name: str, description: str = "") -> Counter:
        """Get or create a counter metric."""
        if name not in self._metrics:
            self._metrics[name] = Counter(name, description)
        return self._metrics[name]

    def gauge(self, name: str, description: str = "") -> Gauge:
        """Get or create a gauge metric."""
        if name not in self._metrics:
            self._metrics[name] = Gauge(name, description)
        return self._metrics[name]

    def histogram(self, name: str, description: str = "") -> Histogram:
        """Get or create a histogram metric."""
        if name not in self._metrics:
            self._metrics[name] = Histogram(name, description)
        return self._metrics[name]

    def get_metrics(self) -> List[Dict[str, Any]]:
        """Return all metrics as dictionaries."""
        return [m.to_dict() for m in self._metrics.values()]

    def get_metric(self, name: str) -> Optional[Dict[str, Any]]:
        """Return a metric by name."""
        m = self._metrics.get(name)
        return m.to_dict() if m else None

    # -- Subscribers --
    def subscribe(self, handler: Callable[[Dict[str, Any]], None]) -> None:
        """Subscribe to log events."""
        self._subscribers.append(handler)

    def _notify_subscribers(self, event: Dict[str, Any]) -> None:
        for handler in self._subscribers:
            try:
                handler(event)
            except Exception:
                pass

    # -- Export --
    def export_json(self) -> Dict[str, Any]:
        """Export full observability state as JSON-serializable dict."""
        return {
            "service": self.service_name,
            "logs_count": len(self._logs),
            "spans_count": len(self._spans),
            "metrics_count": len(self._metrics),
            "logs": [l.to_dict() for l in self._logs[-100:]],
            "spans": [s.to_dict() for s in self._spans[-100:]],
            "metrics": [m.to_dict() for m in self._metrics.values()],
        }

    def export_otlp(self) -> Dict[str, Any]:
        """Export in OTLP-compatible format."""
        resource = {"attributes": [{"key": "service.name", "value": {"stringValue": self.service_name}}]}
        spans_data = []
        with self._lock:
            for s in self._spans[-200:]:
                spans_data.append({
                    "traceId": s.trace_id,
                    "spanId": s.span_id,
                    "parentSpanId": s.parent_span_id or "",
                    "name": s.name,
                    "startTimeUnixNano": int(s.start_time * 1e9),
                    "endTimeUnixNano": int((s.end_time or s.start_time) * 1e9),
                    "status": {"code": 1 if s.status == "OK" else 2 if s.status == "ERROR" else 0},
                })
        return {"resourceSpans": [{"resource": resource, "spans": spans_data}]}

    # -- Stats --
    def get_stats(self) -> Dict[str, Any]:
        """Return observability statistics."""
        with self._lock:
            log_levels = {}
            for l in self._logs:
                lv = l.level.value
                log_levels[lv] = log_levels.get(lv, 0) + 1
        return {
            "total_logs": len(self._logs),
            "log_levels": log_levels,
            "total_spans": len(self._spans),
            "total_metrics": len(self._metrics),
        }

    def clear(self) -> None:
        """Clear all logs, spans, and metrics."""
        with self._lock:
            self._logs.clear()
            self._spans.clear()
            self._metrics.clear()


# ---------------------------------------------------------------------------
# Backward-compatible singleton
# ---------------------------------------------------------------------------
class DataOSTracer:
    """Backward-compatible class-level tracer wrapping ObservabilityEngine."""
    _engine = ObservabilityEngine()
    _completed_spans: List[TraceSpan] = []

    @classmethod
    @contextlib.contextmanager
    def span(cls, name: str, trace_id: Optional[str] = None, parent_span_id: Optional[str] = None, attributes: Optional[Dict[str, Any]] = None):
        s = TraceSpan(name=name, trace_id=trace_id, parent_span_id=parent_span_id, attributes=attributes)
        try:
            yield s
            s.end(status="OK")
        except Exception as e:
            s.end(status="ERROR", error=str(e))
            cls._completed_spans.append(s)
            raise
        else:
            cls._completed_spans.append(s)
        finally:
            if len(cls._completed_spans) > 5000:
                cls._completed_spans = cls._completed_spans[-2500:]

    @classmethod
    def get_recent_spans(cls, limit: int = 50) -> List[Dict[str, Any]]:
        return [s.to_dict() for s in cls._completed_spans[-limit:]]
