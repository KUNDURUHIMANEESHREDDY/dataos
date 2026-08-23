"""
Tests for Usage Tracking (Rule #38).
Validates event recording, querying, analytics, and summary statistics.
"""

import unittest
from engines.usage.tracker import UsageTracker, UsageEvent, UsageType


class TestUsageTracker(unittest.TestCase):

    def setUp(self):
        self.tracker = UsageTracker(max_events=100)

    def test_track_event(self):
        event = self.tracker.track(
            usage_type=UsageType.QUERY,
            consumer_id="agent_1",
            target_object_ids=["obj_a", "obj_b"],
            description="SQL query",
        )
        self.assertIsNotNone(event.event_id)
        self.assertEqual(event.usage_type, UsageType.QUERY)
        self.assertEqual(event.consumer_id, "agent_1")
        self.assertEqual(len(event.target_object_ids), 2)

    def test_get_events(self):
        self.tracker.track(UsageType.QUERY, "a1", ["o1"])
        self.tracker.track(UsageType.ANALYSIS, "a2", ["o1", "o2"])
        self.tracker.track(UsageType.REPORT, "a1", ["o3"])
        events = self.tracker.get_events()
        self.assertEqual(len(events), 3)

    def test_filter_by_type(self):
        self.tracker.track(UsageType.QUERY, "a1", ["o1"])
        self.tracker.track(UsageType.ANALYSIS, "a1", ["o2"])
        self.tracker.track(UsageType.QUERY, "a2", ["o3"])
        queries = self.tracker.get_events(usage_type=UsageType.QUERY)
        self.assertEqual(len(queries), 2)

    def test_filter_by_consumer(self):
        self.tracker.track(UsageType.QUERY, "a1", ["o1"])
        self.tracker.track(UsageType.QUERY, "a2", ["o2"])
        a1_events = self.tracker.get_events(consumer_id="a1")
        self.assertEqual(len(a1_events), 1)

    def test_filter_by_object(self):
        self.tracker.track(UsageType.QUERY, "a1", ["o1", "o2"])
        self.tracker.track(UsageType.ANALYSIS, "a2", ["o2", "o3"])
        self.tracker.track(UsageType.REPORT, "a3", ["o4"])
        o2_events = self.tracker.get_events(object_id="o2")
        self.assertEqual(len(o2_events), 2)

    def test_get_object_usage_count(self):
        self.tracker.track(UsageType.QUERY, "a1", ["o1"])
        self.tracker.track(UsageType.ANALYSIS, "a2", ["o1", "o2"])
        self.tracker.track(UsageType.REPORT, "a3", ["o1"])
        self.assertEqual(self.tracker.get_object_usage_count("o1"), 3)
        self.assertEqual(self.tracker.get_object_usage_count("o2"), 1)
        self.assertEqual(self.tracker.get_object_usage_count("o_none"), 0)

    def test_get_consumer_activity(self):
        self.tracker.track(UsageType.QUERY, "agent_1", ["o1"])
        self.tracker.track(UsageType.ANALYSIS, "agent_1", ["o1", "o2"])
        self.tracker.track(UsageType.QUERY, "agent_2", ["o3"])
        activity = self.tracker.get_consumer_activity("agent_1")
        self.assertEqual(activity["total_events"], 2)
        self.assertEqual(activity["by_type"]["query"], 1)
        self.assertEqual(activity["by_type"]["analysis"], 1)
        self.assertEqual(activity["unique_objects_accessed"], 2)

    def test_get_popular_objects(self):
        self.tracker.track(UsageType.QUERY, "a1", ["o1"])
        self.tracker.track(UsageType.QUERY, "a2", ["o1"])
        self.tracker.track(UsageType.QUERY, "a3", ["o1"])
        self.tracker.track(UsageType.QUERY, "a4", ["o2"])
        popular = self.tracker.get_popular_objects(top_k=1)
        self.assertEqual(len(popular), 1)
        self.assertEqual(popular[0]["object_id"], "o1")
        self.assertEqual(popular[0]["access_count"], 3)

    def test_get_type_breakdown(self):
        self.tracker.track(UsageType.QUERY, "a1", ["o1"])
        self.tracker.track(UsageType.QUERY, "a1", ["o2"])
        self.tracker.track(UsageType.ANALYSIS, "a2", ["o3"])
        breakdown = self.tracker.get_type_breakdown()
        self.assertEqual(breakdown["query"], 2)
        self.assertEqual(breakdown["analysis"], 1)

    def test_get_timeline(self):
        self.tracker.track(UsageType.QUERY, "a1", ["o1"])
        timeline = self.tracker.get_timeline(hours=1)
        self.assertIsInstance(timeline, list)
        self.assertGreaterEqual(len(timeline), 1)

    def test_get_stats(self):
        self.tracker.track(UsageType.QUERY, "a1", ["o1"])
        self.tracker.track(UsageType.ANALYSIS, "a2", ["o1", "o2"])
        stats = self.tracker.get_stats()
        self.assertEqual(stats["total_events"], 2)
        self.assertEqual(stats["unique_consumers"], 2)
        self.assertEqual(stats["unique_objects"], 2)

    def test_max_events_limit(self):
        small_tracker = UsageTracker(max_events=3)
        for i in range(5):
            small_tracker.track(UsageType.QUERY, "a1", [f"o{i}"])
        self.assertEqual(len(small_tracker.get_events(limit=10)), 3)

    def test_clear(self):
        self.tracker.track(UsageType.QUERY, "a1", ["o1"])
        self.tracker.track(UsageType.ANALYSIS, "a2", ["o2"])
        count = self.tracker.clear()
        self.assertEqual(count, 2)
        self.assertEqual(len(self.tracker.get_events()), 0)

    def test_limit_results(self):
        for i in range(20):
            self.tracker.track(UsageType.QUERY, "a1", [f"o{i}"])
        limited = self.tracker.get_events(limit=5)
        self.assertEqual(len(limited), 5)


class TestUsageEvent(unittest.TestCase):

    def test_to_dict(self):
        event = UsageEvent(
            usage_type=UsageType.REPORT,
            consumer_id="user_1",
            target_object_ids=["r1"],
            description="Monthly report",
            metadata={"format": "pdf"},
        )
        d = event.to_dict()
        self.assertEqual(d["usage_type"], "report")
        self.assertEqual(d["consumer_id"], "user_1")
        self.assertEqual(d["metadata"]["format"], "pdf")
        self.assertIn("timestamp", d)


class TestUsageType(unittest.TestCase):

    def test_all_types(self):
        for ut in UsageType:
            self.assertIsInstance(ut.value, str)


if __name__ == "__main__":
    unittest.main()
