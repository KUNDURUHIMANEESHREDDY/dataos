"""
Usage Tracking Engine for DataOS (Rule #38).
Tracks how data is consumed across queries, analyses, reports, and agents.
Maintains first-class usage objects with full provenance.
"""

from __future__ import annotations
import uuid
import datetime
from typing import Dict, Any, List, Optional
from enum import Enum


class UsageType(str, Enum):
    """Categories of data consumption events."""
    QUERY = "query"
    ANALYSIS = "analysis"
    REPORT = "report"
    AGENT = "agent"
    EXPORT = "export"
    INGEST = "ingest"
    SEARCH = "search"


class UsageEvent:
    """A single data consumption event."""

    def __init__(
        self,
        usage_type: UsageType,
        consumer_id: str,
        target_object_ids: List[str],
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.event_id = str(uuid.uuid4())
        self.usage_type = usage_type
        self.consumer_id = consumer_id
        self.target_object_ids = target_object_ids
        self.description = description
        self.metadata = metadata or {}
        self.timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the usage event to a dictionary."""
        return {
            "event_id": self.event_id,
            "usage_type": self.usage_type.value,
            "consumer_id": self.consumer_id,
            "target_object_ids": self.target_object_ids,
            "description": self.description,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }


class UsageTracker:
    """
    In-memory usage tracking engine.
    Records data consumption events and computes analytics.
    """

    def __init__(self, max_events: int = 10000):
        self._events: List[UsageEvent] = []
        self._max_events = max_events

    def track(
        self,
        usage_type: UsageType,
        consumer_id: str,
        target_object_ids: List[str],
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> UsageEvent:
        """Record a usage event."""
        event = UsageEvent(
            usage_type=usage_type,
            consumer_id=consumer_id,
            target_object_ids=target_object_ids,
            description=description,
            metadata=metadata,
        )
        self._events.append(event)
        if len(self._events) > self._max_events:
            self._events = self._events[-self._max_events:]
        return event

    def get_events(
        self,
        usage_type: Optional[UsageType] = None,
        consumer_id: Optional[str] = None,
        object_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query usage events with optional filters."""
        results = []
        for event in reversed(self._events):
            if usage_type and event.usage_type != usage_type:
                continue
            if consumer_id and event.consumer_id != consumer_id:
                continue
            if object_id and object_id not in event.target_object_ids:
                continue
            results.append(event.to_dict())
            if len(results) >= limit:
                break
        return results

    def get_object_usage_count(self, object_id: str) -> int:
        """Count how many times an object has been consumed."""
        return sum(
            1 for e in self._events
            if object_id in e.target_object_ids
        )

    def get_consumer_activity(self, consumer_id: str) -> Dict[str, Any]:
        """Get usage statistics for a specific consumer."""
        consumer_events = [e for e in self._events if e.consumer_id == consumer_id]
        by_type = {}
        objects_accessed = set()
        for e in consumer_events:
            t = e.usage_type.value
            by_type[t] = by_type.get(t, 0) + 1
            objects_accessed.update(e.target_object_ids)
        return {
            "consumer_id": consumer_id,
            "total_events": len(consumer_events),
            "by_type": by_type,
            "unique_objects_accessed": len(objects_accessed),
            "object_ids": list(objects_accessed),
        }

    def get_popular_objects(self, top_k: int = 10) -> List[Dict[str, Any]]:
        """Return the most frequently accessed objects."""
        counts: Dict[str, int] = {}
        for e in self._events:
            for oid in e.target_object_ids:
                counts[oid] = counts.get(oid, 0) + 1
        sorted_items = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        return [{"object_id": oid, "access_count": cnt} for oid, cnt in sorted_items[:top_k]]

    def get_type_breakdown(self) -> Dict[str, int]:
        """Get event count breakdown by usage type."""
        breakdown: Dict[str, int] = {}
        for e in self._events:
            t = e.usage_type.value
            breakdown[t] = breakdown.get(t, 0) + 1
        return breakdown

    def get_timeline(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Get usage counts bucketed by hour for the last N hours."""
        now = datetime.datetime.now(datetime.timezone.utc)
        buckets: Dict[str, int] = {}
        cutoff = now - datetime.timedelta(hours=hours)
        for e in self._events:
            try:
                ts = datetime.datetime.fromisoformat(e.timestamp)
                if ts >= cutoff:
                    bucket_key = ts.strftime("%Y-%m-%d %H:00")
                    buckets[bucket_key] = buckets.get(bucket_key, 0) + 1
            except (ValueError, TypeError):
                continue
        return [{"hour": k, "count": v} for k, v in sorted(buckets.items())]

    def get_stats(self) -> Dict[str, Any]:
        """Return summary statistics."""
        return {
            "total_events": len(self._events),
            "type_breakdown": self.get_type_breakdown(),
            "unique_consumers": len(set(e.consumer_id for e in self._events)),
            "unique_objects": len(set(
                oid for e in self._events for oid in e.target_object_ids
            )),
        }

    def clear(self) -> int:
        """Clear all usage events. Returns count cleared."""
        count = len(self._events)
        self._events.clear()
        return count
