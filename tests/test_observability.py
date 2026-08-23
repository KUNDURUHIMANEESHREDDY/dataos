"""
Tests for Observability Engine (Rule #41).
Validates logging, tracing, metrics, export, and backward compatibility.
"""

import unittest
import time
from infrastructure.observability.tracer import (
    ObservabilityEngine, TraceSpan, DataOSTracer,
    LogEntry, LogLevel, Counter, Gauge, Histogram,
)


class TestObservabilityEngine(unittest.TestCase):

    def setUp(self):
        self.engine = ObservabilityEngine(service_name="test_service", max_logs=100, max_spans=50)

    def tearDown(self):
        self.engine.clear()

    # -- Logging --
    def test_log_entry(self):
        entry = self.engine.info("Hello world", logger="test")
        self.assertEqual(entry.level, LogLevel.INFO)
        self.assertEqual(entry.message, "Hello world")
        self.assertEqual(entry.logger, "test")

    def test_log_levels(self):
        self.engine.debug("d")
        self.engine.info("i")
        self.engine.warn("w")
        self.engine.error("e")
        self.engine.fatal("f")
        logs = self.engine.get_logs()
        self.assertEqual(len(logs), 5)
        levels = [l["level"] for l in logs]
        self.assertIn("debug", levels)
        self.assertIn("fatal", levels)

    def test_log_with_trace_context(self):
        entry = self.engine.info("ctx", trace_id="t1", span_id="s1")
        self.assertEqual(entry.trace_id, "t1")
        self.assertEqual(entry.span_id, "s1")

    def test_log_with_attributes(self):
        entry = self.engine.info("attrs", attributes={"key": "val"})
        self.assertEqual(entry.attributes["key"], "val")

    def test_get_logs_filter_level(self):
        self.engine.info("a")
        self.engine.error("b")
        self.engine.error("c")
        errors = self.engine.get_logs(level=LogLevel.ERROR)
        self.assertEqual(len(errors), 2)

    def test_get_logs_filter_logger(self):
        self.engine.info("a", logger="auth")
        self.engine.info("b", logger="db")
        auth_logs = self.engine.get_logs(logger="auth")
        self.assertEqual(len(auth_logs), 1)

    def test_log_max_limit(self):
        small = ObservabilityEngine(max_logs=5)
        for i in range(10):
            small.info(f"msg {i}")
        self.assertLessEqual(len(small.get_logs(limit=100)), 10)

    def test_log_subscriber(self):
        received = []
        self.engine.subscribe(lambda e: received.append(e))
        self.engine.info("subscribed")
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["message"], "subscribed")

    # -- Tracing --
    def test_span_context_manager(self):
        with self.engine.span("op1") as s:
            self.assertIsInstance(s, TraceSpan)
            self.assertEqual(s.name, "op1")
        self.assertEqual(s.status, "OK")
        self.assertIsNotNone(s.duration_ms)

    def test_span_error_capture(self):
        try:
            with self.engine.span("fail_op"):
                raise ValueError("boom")
        except ValueError:
            pass
        spans = self.engine.get_spans()
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0]["status"], "ERROR")
        self.assertIn("boom", spans[0]["error_message"])

    def test_span_attributes(self):
        with self.engine.span("with_attrs", attributes={"a": 1}) as s:
            s.set_attribute("b", 2)
        self.assertEqual(s.attributes["a"], 1)
        self.assertEqual(s.attributes["b"], 2)

    def test_span_events(self):
        with self.engine.span("evt_span") as s:
            s.add_event("checkpoint", {"step": 1})
        self.assertEqual(len(s.events), 1)
        self.assertEqual(s.events[0]["name"], "checkpoint")

    def test_nested_spans(self):
        with self.engine.span("parent") as p:
            with self.engine.span("child", trace_id=p.trace_id, parent_span_id=p.span_id) as c:
                pass
        tree = self.engine.get_trace_tree(p.trace_id)
        self.assertEqual(len(tree), 1)
        self.assertIn("children", tree[0])

    def test_get_spans_filter_trace(self):
        with self.engine.span("a") as s1:
            pass
        with self.engine.span("b") as s2:
            pass
        filtered = self.engine.get_spans(trace_id=s1.trace_id)
        self.assertEqual(len(filtered), 1)

    # -- Metrics --
    def test_counter(self):
        c = self.engine.counter("requests", "Total requests")
        c.inc()
        c.inc(5)
        self.assertEqual(c.get_value(), 6)

    def test_gauge(self):
        g = self.engine.gauge("queue_depth", "Queue depth")
        g.set(10)
        self.assertEqual(g.get_value(), 10)
        g.inc(3)
        self.assertEqual(g.get_value(), 13)
        g.dec(5)
        self.assertEqual(g.get_value(), 8)

    def test_histogram(self):
        h = self.engine.histogram("latency", "Request latency")
        for v in [10, 20, 30, 40, 50]:
            h.observe(v)
        stats = h.get_value()
        self.assertEqual(stats["count"], 5)
        self.assertEqual(stats["min"], 10)
        self.assertEqual(stats["max"], 50)
        self.assertEqual(stats["mean"], 30)

    def test_get_metrics(self):
        self.engine.counter("c1")
        self.engine.gauge("g1")
        metrics = self.engine.get_metrics()
        self.assertEqual(len(metrics), 2)

    def test_get_metric_by_name(self):
        self.engine.counter("my_counter")
        m = self.engine.get_metric("my_counter")
        self.assertIsNotNone(m)
        self.assertEqual(m["name"], "my_counter")

    # -- Export --
    def test_export_json(self):
        self.engine.info("log1")
        with self.engine.span("s1"):
            pass
        data = self.engine.export_json()
        self.assertEqual(data["service"], "test_service")
        self.assertGreater(data["logs_count"], 0)
        self.assertGreater(data["spans_count"], 0)

    def test_export_otlp(self):
        with self.engine.span("otlp_span"):
            pass
        otlp = self.engine.export_otlp()
        self.assertIn("resourceSpans", otlp)
        self.assertGreater(len(otlp["resourceSpans"][0]["spans"]), 0)

    def test_stats(self):
        self.engine.info("a")
        self.engine.error("b")
        self.engine.counter("m1")
        stats = self.engine.get_stats()
        self.assertEqual(stats["total_logs"], 2)
        self.assertEqual(stats["log_levels"]["info"], 1)
        self.assertEqual(stats["log_levels"]["error"], 1)
        self.assertEqual(stats["total_metrics"], 1)

    def test_clear(self):
        self.engine.info("a")
        self.engine.counter("m1")
        self.engine.clear()
        self.assertEqual(len(self.engine.get_logs()), 0)
        self.assertEqual(len(self.engine.get_metrics()), 0)


class TestCounter(unittest.TestCase):

    def test_inc(self):
        c = Counter("c", "desc")
        c.inc()
        c.inc(2.5)
        self.assertEqual(c.get_value(), 3.5)

    def test_to_dict(self):
        c = Counter("c")
        d = c.to_dict()
        self.assertEqual(d["type"], "counter")


class TestGauge(unittest.TestCase):

    def test_set_inc_dec(self):
        g = Gauge("g")
        g.set(10)
        g.inc(5)
        g.dec(3)
        self.assertEqual(g.get_value(), 12)

    def test_to_dict(self):
        g = Gauge("g")
        d = g.to_dict()
        self.assertEqual(d["type"], "gauge")


class TestHistogram(unittest.TestCase):

    def test_empty(self):
        h = Histogram("h")
        stats = h.get_value()
        self.assertEqual(stats["count"], 0)

    def test_observe(self):
        h = Histogram("h")
        h.observe(1)
        h.observe(2)
        h.observe(3)
        stats = h.get_value()
        self.assertEqual(stats["count"], 3)
        self.assertEqual(stats["min"], 1)
        self.assertEqual(stats["max"], 3)

    def test_to_dict(self):
        h = Histogram("h")
        d = h.to_dict()
        self.assertEqual(d["type"], "histogram")


class TestBackwardCompat(unittest.TestCase):

    def test_dataos_tracer(self):
        with DataOSTracer.span("test_span") as s:
            s.add_event("checkpoint")
        self.assertEqual(s.status, "OK")
        recent = DataOSTracer.get_recent_spans(limit=1)
        self.assertEqual(len(recent), 1)

    def test_dataos_tracer_error(self):
        try:
            with DataOSTracer.span("fail"):
                raise RuntimeError("test")
        except RuntimeError:
            pass
        recent = DataOSTracer.get_recent_spans(limit=1)
        self.assertEqual(recent[0]["status"], "ERROR")


class TestLogLevel(unittest.TestCase):

    def test_all_levels(self):
        for lv in LogLevel:
            self.assertIsInstance(lv.value, str)


class TestLogEntry(unittest.TestCase):

    def test_to_dict(self):
        entry = LogEntry(level=LogLevel.INFO, message="test", logger="l", trace_id="t", span_id="s")
        d = entry.to_dict()
        self.assertEqual(d["level"], "info")
        self.assertEqual(d["trace_id"], "t")


if __name__ == "__main__":
    unittest.main()
