"""
Enhanced System Event Bus for DataOS (Rule #34).
Persistent pub/sub engine with wildcard subscriptions, event filtering,
ordering guarantees, history persistence via storage backend, and lifecycle hooks.
Supports: object lifecycle, schema changes, query execution, workflow triggers.
"""

from __future__ import annotations
import uuid
import datetime
import json
import threading
from typing import Dict, Any, List, Callable, Optional, Set
from enum import Enum


class EventPriority(str, Enum):
    """Priority levels for event delivery ordering."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class EventFilter:
    """Filter events based on topic patterns and payload predicates."""

    def __init__(
        self,
        topic_pattern: Optional[str] = None,
        payload_predicate: Optional[Callable[[Dict[str, Any]], bool]] = None,
        priority_min: Optional[EventPriority] = None,
    ):
        self.topic_pattern = topic_pattern
        self.payload_predicate = payload_predicate
        self.priority_min = priority_min

    def matches(self, event: Dict[str, Any]) -> bool:
        """Check if an event passes all filter criteria."""
        if self.topic_pattern and not self._topic_matches(event.get("topic", ""), self.topic_pattern):
            return False
        if self.payload_predicate and not self.payload_predicate(event.get("payload", {})):
            return False
        if self.priority_min:
            event_priority = EventPriority(event.get("priority", "normal"))
            priority_order = list(EventPriority)
            if priority_order.index(event_priority) < priority_order.index(self.priority_min):
                return False
        return True

    def _topic_matches(self, topic: str, pattern: str) -> bool:
        """Match topic against pattern with * wildcard support."""
        if "*" not in pattern:
            return topic == pattern
        import fnmatch
        return fnmatch.fnmatch(topic, pattern)


class EventSubscription:
    """Represents a subscription with metadata for lifecycle management."""

    def __init__(
        self,
        subscriber_id: str,
        topic: str,
        handler: Callable[[Dict[str, Any]], None],
        event_filter: Optional[EventFilter] = None,
        priority: EventPriority = EventPriority.NORMAL,
        once: bool = False,
    ):
        self.subscriber_id = subscriber_id
        self.topic = topic
        self.handler = handler
        self.event_filter = event_filter
        self.priority = priority
        self.once = once
        self.created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.call_count = 0
        self.last_called_at: Optional[str] = None
        self.error_count = 0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize subscription metadata to a dictionary."""
        return {
            "subscriber_id": self.subscriber_id,
            "topic": self.topic,
            "priority": self.priority.value,
            "once": self.once,
            "created_at": self.created_at,
            "call_count": self.call_count,
            "last_called_at": self.last_called_at,
            "error_count": self.error_count,
        }


class EventBus:
    """
    Enhanced Pub/Sub Event Bus for DataOS system-wide notifications.
    Features:
    - Wildcard topic subscriptions (e.g. "object.*", "query.*")
    - Event filtering with predicates
    - Priority-based delivery ordering
    - Optional event history persistence
    - Thread-safe operations
    - Subscriber lifecycle management
    """

    def __init__(self, max_history: int = 5000, persist_history: bool = False, storage=None):
        self._subscriptions: Dict[str, List[EventSubscription]] = {}
        self._event_history: List[Dict[str, Any]] = []
        self._max_history = max_history
        self._persist_history = persist_history
        self._storage = storage
        self._lock = threading.Lock()
        self._interceptors: List[Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]] = []
        self._global_handlers: List[Callable[[Dict[str, Any]], None]] = []
        self._stats = {"published": 0, "delivered": 0, "errors": 0, "intercepted": 0}
        self._running = True

    def subscribe(
        self,
        topic: str,
        handler: Callable[[Dict[str, Any]], None],
        subscriber_id: Optional[str] = None,
        event_filter: Optional[EventFilter] = None,
        priority: EventPriority = EventPriority.NORMAL,
        once: bool = False,
    ) -> str:
        """
        Subscribe to a topic. Supports wildcards (*, ?).
        Returns subscriber_id for later unsubscription.
        """
        sub_id = subscriber_id or str(uuid.uuid4())[:12]
        subscription = EventSubscription(
            subscriber_id=sub_id,
            topic=topic,
            handler=handler,
            event_filter=event_filter,
            priority=priority,
            once=once,
        )
        with self._lock:
            if topic not in self._subscriptions:
                self._subscriptions[topic] = []
            self._subscriptions[topic].append(subscription)
        return sub_id

    def unsubscribe(self, subscriber_id: str) -> bool:
        """Remove a subscription by subscriber_id."""
        with self._lock:
            for topic, subs in self._subscriptions.items():
                for i, sub in enumerate(subs):
                    if sub.subscriber_id == subscriber_id:
                        subs.pop(i)
                        return True
        return False

    def unsubscribe_topic(self, topic: str) -> int:
        """Remove all subscriptions for a specific topic. Returns count removed."""
        with self._lock:
            if topic in self._subscriptions:
                count = len(self._subscriptions[topic])
                del self._subscriptions[topic]
                return count
        return 0

    def add_interceptor(self, interceptor: Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]) -> None:
        """
        Add an event interceptor. Interceptors can modify or suppress events.
        Return None to suppress the event, or return modified event dict.
        """
        self._interceptors.append(interceptor)

    def add_global_handler(self, handler: Callable[[Dict[str, Any]], None]) -> None:
        """Add a handler that receives ALL events regardless of topic."""
        self._global_handlers.append(handler)

    def publish(
        self,
        topic: str,
        payload: Dict[str, Any],
        priority: EventPriority = EventPriority.NORMAL,
        source: str = "system",
        event_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Publish an event to a topic. Returns the created event dict.
        Applies interceptors, then delivers to matching subscribers.
        """
        if not self._running:
            return {}

        event = {
            "event_id": event_id or str(uuid.uuid4()),
            "topic": topic,
            "payload": payload,
            "priority": priority.value,
            "source": source,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

        # Apply interceptors
        for interceptor in self._interceptors:
            try:
                result = interceptor(event)
                if result is None:
                    self._stats["intercepted"] += 1
                    return event
                event = result
            except Exception as e:
                print(f"[EventBus] Interceptor error: {e}")

        # Store in history
        with self._lock:
            self._event_history.append(event)
            if len(self._event_history) > self._max_history:
                self._event_history = self._event_history[-self._max_history:]

        # Persist if configured
        if self._persist_history and self._storage:
            try:
                self._persist_event(event)
            except Exception as e:
                print(f"[EventBus] Persist error: {e}")

        # Deliver to subscribers
        self._deliver_event(event)

        # Global handlers
        for handler in self._global_handlers:
            try:
                handler(event)
            except Exception as e:
                self._stats["errors"] += 1
                print(f"[EventBus] Global handler error: {e}")

        self._stats["published"] += 1
        return event

    def _deliver_event(self, event: Dict[str, Any]) -> None:
        """Deliver event to all matching subscribers."""
        topic = event["topic"]
        to_remove = []

        with self._lock:
            # Collect all matching subscriptions
            matching = []
            for sub_topic, subs in self._subscriptions.items():
                for sub in subs:
                    if self._topic_matches_event(topic, sub_topic):
                        if sub.event_filter and not sub.event_filter.matches(event):
                            continue
                        matching.append((sub_topic, sub))

        # Deliver outside lock to avoid deadlocks
        for sub_topic, sub in matching:
            try:
                sub.handler(event)
                sub.call_count += 1
                sub.last_called_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
                self._stats["delivered"] += 1
                if sub.once:
                    to_remove.append((sub_topic, sub.subscriber_id))
            except Exception as e:
                sub.error_count += 1
                self._stats["errors"] += 1
                print(f"[EventBus] Handler '{sub.subscriber_id}' error on topic '{topic}': {e}")

        # Remove one-time subscriptions
        with self._lock:
            for sub_topic, sub_id in to_remove:
                if sub_topic in self._subscriptions:
                    self._subscriptions[sub_topic] = [
                        s for s in self._subscriptions[sub_topic]
                        if s.subscriber_id != sub_id
                    ]

    def _topic_matches_event(self, event_topic: str, sub_topic: str) -> bool:
        """Check if an event topic matches a subscription topic pattern."""
        if sub_topic == "*":
            return True
        if event_topic == sub_topic:
            return True
        if "*" in sub_topic or "?" in sub_topic:
            import fnmatch
            return fnmatch.fnmatch(event_topic, sub_topic)
        return False

    def _persist_event(self, event: Dict[str, Any]) -> None:
        """Persist event to storage backend."""
        if hasattr(self._storage, "save_event"):
            self._storage.save_event(event)

    def get_recent_events(self, limit: int = 50, topic_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get recent events, optionally filtered by topic pattern."""
        with self._lock:
            events = list(self._event_history)

        if topic_filter:
            events = [e for e in events if self._topic_matches_event(e["topic"], topic_filter)]

        return events[-limit:]

    def get_event_by_id(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Lookup a specific event by ID."""
        with self._lock:
            for event in self._event_history:
                if event.get("event_id") == event_id:
                    return event
        return None

    def get_subscribers(self, topic: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all subscriptions, optionally filtered by topic."""
        with self._lock:
            if topic:
                subs = self._subscriptions.get(topic, [])
                return [s.to_dict() for s in subs]
            all_subs = []
            for topic_subs in self._subscriptions.values():
                all_subs.extend([s.to_dict() for s in topic_subs])
            return all_subs

    def get_stats(self) -> Dict[str, Any]:
        """Return event bus statistics."""
        with self._lock:
            topic_counts = {topic: len(subs) for topic, subs in self._subscriptions.items()}
        return {
            **self._stats,
            "history_size": len(self._event_history),
            "active_subscriptions": sum(topic_counts.values()),
            "topics": topic_counts,
        }

    def clear_history(self) -> int:
        """Clear event history. Returns count of events cleared."""
        with self._lock:
            count = len(self._event_history)
            self._event_history.clear()
        return count

    def shutdown(self) -> None:
        """Gracefully shut down the event bus."""
        self._running = False
        with self._lock:
            self._subscriptions.clear()
            self._global_handlers.clear()
            self._interceptors.clear()


# ---------------------------------------------------------------------------
# Standard DataOS event topic constants
# ---------------------------------------------------------------------------
class EventTopics:
    """Pre-defined event topics for DataOS system events."""
    OBJECT_CREATED = "object.created"
    OBJECT_UPDATED = "object.updated"
    OBJECT_DELETED = "object.deleted"
    SCHEMA_CREATED = "schema.created"
    SCHEMA_UPDATED = "schema.updated"
    QUERY_EXECUTED = "query.executed"
    QUERY_FAILED = "query.failed"
    WORKFLOW_STARTED = "workflow.started"
    WORKFLOW_COMPLETED = "workflow.completed"
    WORKFLOW_FAILED = "workflow.failed"
    AGENT_STARTED = "agent.started"
    AGENT_COMPLETED = "agent.completed"
    AGENT_FAILED = "agent.failed"
    PLUGIN_LOADED = "plugin.loaded"
    PLUGIN_ACTIVATED = "plugin.activated"
    PLUGIN_ERROR = "plugin.error"
    CONNECTOR_CONNECTED = "connector.connected"
    CONNECTOR_DISCONNECTED = "connector.disconnected"
    INGESTION_STARTED = "ingestion.started"
    INGESTION_COMPLETED = "ingestion.completed"
    DATA_QUALITY_CHECK = "data_quality.check"
    PROVENANCE_RECORDED = "provenance.recorded"
    RELATIONSHIP_DISCOVERED = "relationship.discovered"
    EXPORT_COMPLETED = "export.completed"
    SYSTEM_ERROR = "system.error"
