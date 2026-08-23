"""
Tests for Enhanced Event Bus (Rule #34).
Validates pub/sub, wildcards, filtering, interceptors, priorities, and lifecycle.
"""

import unittest
import threading
import time
from runtime.events.event_bus import (
    EventBus, EventFilter, EventSubscription, EventPriority, EventTopics
)


class TestEventBus(unittest.TestCase):

    def setUp(self):
        self.bus = EventBus(max_history=100)

    def tearDown(self):
        self.bus.shutdown()

    def test_basic_publish_subscribe(self):
        received = []
        self.bus.subscribe("test.topic", lambda e: received.append(e))
        self.bus.publish("test.topic", {"key": "value"})
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["payload"]["key"], "value")

    def test_multiple_subscribers(self):
        received_a = []
        received_b = []
        self.bus.subscribe("test.topic", lambda e: received_a.append(e))
        self.bus.subscribe("test.topic", lambda e: received_b.append(e))
        self.bus.publish("test.topic", {"data": 1})
        self.assertEqual(len(received_a), 1)
        self.assertEqual(len(received_b), 1)

    def test_unsubscribe(self):
        received = []
        sub_id = self.bus.subscribe("test.topic", lambda e: received.append(e))
        self.bus.publish("test.topic", {"a": 1})
        self.assertTrue(self.bus.unsubscribe(sub_id))
        self.bus.publish("test.topic", {"a": 2})
        self.assertEqual(len(received), 1)

    def test_unsubscribe_nonexistent(self):
        self.assertFalse(self.bus.unsubscribe("no_such_id"))

    def test_unsubscribe_topic(self):
        received = []
        self.bus.subscribe("test.topic", lambda e: received.append(e))
        self.bus.subscribe("test.topic", lambda e: received.append(e))
        count = self.bus.unsubscribe_topic("test.topic")
        self.assertEqual(count, 2)
        self.bus.publish("test.topic", {"a": 1})
        self.assertEqual(len(received), 0)

    def test_wildcard_star(self):
        received = []
        self.bus.subscribe("object.*", lambda e: received.append(e))
        self.bus.publish("object.created", {"id": "1"})
        self.bus.publish("object.updated", {"id": "1"})
        self.bus.publish("query.executed", {"q": "SELECT 1"})
        self.assertEqual(len(received), 2)

    def test_wildcard_question_mark(self):
        received = []
        self.bus.subscribe("objec?.created", lambda e: received.append(e))
        self.bus.publish("object.created", {"id": "1"})
        self.bus.publish("objects.created", {"id": "2"})
        self.assertEqual(len(received), 1)

    def test_global_wildcard(self):
        received = []
        self.bus.subscribe("*", lambda e: received.append(e))
        self.bus.publish("any.topic", {"a": 1})
        self.bus.publish("other.topic", {"b": 2})
        self.assertEqual(len(received), 2)

    def test_event_filter_by_topic(self):
        received = []
        filt = EventFilter(topic_pattern="object.*")
        self.bus.subscribe("object.*", lambda e: received.append(e), event_filter=filt)
        self.bus.publish("object.created", {"id": "1"})
        self.bus.publish("query.executed", {"q": "1"})
        self.assertEqual(len(received), 1)

    def test_event_filter_by_payload(self):
        received = []
        filt = EventFilter(payload_predicate=lambda p: p.get("priority") == "high")
        self.bus.subscribe("test.*", lambda e: received.append(e), event_filter=filt)
        self.bus.publish("test.a", {"priority": "low"})
        self.bus.publish("test.b", {"priority": "high"})
        self.assertEqual(len(received), 1)

    def test_event_filter_by_priority(self):
        received = []
        filt = EventFilter(priority_min=EventPriority.HIGH)
        self.bus.subscribe("test.*", lambda e: received.append(e), event_filter=filt)
        self.bus.publish("test.a", {"x": 1}, priority=EventPriority.LOW)
        self.bus.publish("test.b", {"x": 2}, priority=EventPriority.NORMAL)
        self.bus.publish("test.c", {"x": 3}, priority=EventPriority.HIGH)
        self.bus.publish("test.d", {"x": 4}, priority=EventPriority.CRITICAL)
        self.assertEqual(len(received), 2)

    def test_priority_delivery_order(self):
        received_priorities = []
        def handler(e):
            received_priorities.append(e["priority"])
        self.bus.subscribe("test.*", handler)
        self.bus.publish("test.a", {}, priority=EventPriority.CRITICAL)
        self.bus.publish("test.b", {}, priority=EventPriority.LOW)
        self.bus.publish("test.c", {}, priority=EventPriority.NORMAL)
        # Events delivered in publish order (not priority order for now)
        self.assertEqual(received_priorities, ["critical", "low", "normal"])

    def test_once_subscription(self):
        received = []
        self.bus.subscribe("test.topic", lambda e: received.append(e), once=True)
        self.bus.publish("test.topic", {"a": 1})
        self.bus.publish("test.topic", {"a": 2})
        self.assertEqual(len(received), 1)

    def test_interceptor_modify(self):
        def interceptor(event):
            event["payload"]["modified"] = True
            return event
        self.bus.add_interceptor(interceptor)
        received = []
        self.bus.subscribe("test.*", lambda e: received.append(e))
        self.bus.publish("test.a", {"x": 1})
        self.assertTrue(received[0]["payload"]["modified"])

    def test_interceptor_suppress(self):
        def interceptor(event):
            return None  # suppress
        self.bus.add_interceptor(interceptor)
        received = []
        self.bus.subscribe("test.*", lambda e: received.append(e))
        self.bus.publish("test.a", {"x": 1})
        self.assertEqual(len(received), 0)

    def test_global_handler(self):
        all_events = []
        self.bus.add_global_handler(lambda e: all_events.append(e))
        self.bus.publish("test.a", {"a": 1})
        self.bus.publish("other.b", {"b": 2})
        self.assertEqual(len(all_events), 2)

    def test_get_recent_events(self):
        self.bus.publish("test.a", {"a": 1})
        self.bus.publish("test.b", {"b": 2})
        self.bus.publish("other.c", {"c": 3})
        recent = self.bus.get_recent_events(limit=2)
        self.assertEqual(len(recent), 2)

    def test_get_recent_events_with_filter(self):
        self.bus.publish("test.a", {"a": 1})
        self.bus.publish("other.b", {"b": 2})
        self.bus.publish("test.c", {"c": 3})
        filtered = self.bus.get_recent_events(topic_filter="test.*")
        self.assertEqual(len(filtered), 2)

    def test_get_event_by_id(self):
        event = self.bus.publish("test.a", {"a": 1})
        found = self.bus.get_event_by_id(event["event_id"])
        self.assertIsNotNone(found)
        self.assertEqual(found["topic"], "test.a")

    def test_get_event_by_id_not_found(self):
        self.assertIsNone(self.bus.get_event_by_id("nonexistent"))

    def test_get_subscribers(self):
        self.bus.subscribe("test.*", lambda e: None, subscriber_id="sub1")
        self.bus.subscribe("test.*", lambda e: None, subscriber_id="sub2")
        self.bus.subscribe("other.*", lambda e: None, subscriber_id="sub3")
        all_subs = self.bus.get_subscribers()
        self.assertEqual(len(all_subs), 3)
        test_subs = self.bus.get_subscribers(topic="test.*")
        self.assertEqual(len(test_subs), 2)

    def test_stats(self):
        self.bus.subscribe("test.*", lambda e: None)
        self.bus.publish("test.a", {"a": 1})
        stats = self.bus.get_stats()
        self.assertEqual(stats["published"], 1)
        self.assertEqual(stats["active_subscriptions"], 1)
        self.assertIn("test.*", stats["topics"])

    def test_clear_history(self):
        self.bus.publish("test.a", {"a": 1})
        self.bus.publish("test.b", {"b": 2})
        count = self.bus.clear_history()
        self.assertEqual(count, 2)
        self.assertEqual(len(self.bus.get_recent_events()), 0)

    def test_history_max_limit(self):
        bus = EventBus(max_history=3)
        for i in range(5):
            bus.publish("test", {"i": i})
        self.assertEqual(len(bus.get_recent_events(limit=10)), 3)
        bus.shutdown()

    def test_thread_safety(self):
        received = []
        self.bus.subscribe("test.*", lambda e: received.append(e))

        def publish_events():
            for i in range(50):
                self.bus.publish("test.thread", {"i": i})

        threads = [threading.Thread(target=publish_events) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(received), 200)

    def test_subscriber_error_doesnt_break_delivery(self):
        def bad_handler(e):
            raise RuntimeError("oops")

        received = []
        self.bus.subscribe("test.*", bad_handler)
        self.bus.subscribe("test.*", lambda e: received.append(e))
        self.bus.publish("test.a", {"a": 1})
        self.assertEqual(len(received), 1)

    def test_shutdown_stops_delivery(self):
        received = []
        self.bus.subscribe("test.*", lambda e: received.append(e))
        self.bus.shutdown()
        self.bus.publish("test.a", {"a": 1})
        self.assertEqual(len(received), 0)

    def test_subscriber_metadata(self):
        sub_id = self.bus.subscribe("test.*", lambda e: None, subscriber_id="my_sub")
        self.assertEqual(sub_id, "my_sub")
        subs = self.bus.get_subscribers()
        self.assertEqual(subs[0]["subscriber_id"], "my_sub")
        self.assertEqual(subs[0]["call_count"], 0)
        self.bus.publish("test.a", {"a": 1})
        subs = self.bus.get_subscribers()
        self.assertEqual(subs[0]["call_count"], 1)
        self.assertIsNotNone(subs[0]["last_called_at"])

    def test_event_topics_constants(self):
        self.assertEqual(EventTopics.OBJECT_CREATED, "object.created")
        self.assertEqual(EventTopics.QUERY_EXECUTED, "query.executed")
        self.assertEqual(EventTopics.WORKFLOW_COMPLETED, "workflow.completed")


class TestEventFilter(unittest.TestCase):

    def test_topic_matches_exact(self):
        f = EventFilter(topic_pattern="object.created")
        self.assertTrue(f._topic_matches("object.created", "object.created"))
        self.assertFalse(f._topic_matches("object.updated", "object.created"))

    def test_topic_matches_wildcard(self):
        f = EventFilter(topic_pattern="object.*")
        self.assertTrue(f._topic_matches("object.created", "object.*"))
        self.assertTrue(f._topic_matches("object.deleted", "object.*"))
        self.assertFalse(f._topic_matches("query.executed", "object.*"))

    def test_matches_with_payload_predicate(self):
        f = EventFilter(payload_predicate=lambda p: p.get("x") == 1)
        event = {"topic": "t", "payload": {"x": 1}}
        self.assertTrue(f.matches(event))
        event2 = {"topic": "t", "payload": {"x": 2}}
        self.assertFalse(f.matches(event2))


class TestEventSubscription(unittest.TestCase):

    def test_to_dict(self):
        sub = EventSubscription(subscriber_id="s1", topic="t", handler=lambda e: None)
        d = sub.to_dict()
        self.assertEqual(d["subscriber_id"], "s1")
        self.assertEqual(d["topic"], "t")
        self.assertEqual(d["call_count"], 0)


if __name__ == "__main__":
    unittest.main()
