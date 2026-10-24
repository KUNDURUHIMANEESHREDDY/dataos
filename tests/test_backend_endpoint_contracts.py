import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend import app as api


class FakeDataOS:
    def __init__(self):
        self.calls = []
        self.storage = SimpleNamespace(list_objects=self.list_objects)
        self.graph = SimpleNamespace(
            create_relation=self.create_relation,
            neighbors=self.neighbors,
            engine=SimpleNamespace(traverse=self.traverse),
            analytics_engine=SimpleNamespace(
                compute_pagerank=lambda: {"a": 1.0},
                compute_degree_centrality=lambda: {"a": 0.5},
                compute_betweenness_centrality=lambda: {"a": 0.0},
                detect_communities=lambda: [["a"]],
            ),
        )

    def list_objects(self, **kwargs):
        self.calls.append(("list_objects", kwargs))
        return []

    def create_relation(self, **kwargs):
        self.calls.append(("create_relation", kwargs))
        return SimpleNamespace(to_dict=lambda: {"source_id": kwargs["source_id"], "target_id": kwargs["target_id"]})

    def neighbors(self, object_id, direction="both"):
        self.calls.append(("neighbors", object_id, direction))
        return [{"id": "neighbor-1"}]

    def traverse(self, **kwargs):
        self.calls.append(("traverse", kwargs))
        return {"total_nodes_reached": 2, "total_edges_traversed": 1}

    def sql(self, query):
        self.calls.append(("sql", query))
        return {"kind": "sql", "query": query}

    def python(self, code, input_object_ids=None):
        self.calls.append(("python", code, input_object_ids or []))
        return {"kind": "python", "code": code, "inputs": input_object_ids or []}

    def ask(self, query):
        self.calls.append(("ask", query))
        return {"kind": "ask", "query": query}

    def search(self, query, top_k=10):
        self.calls.append(("search", query, top_k))
        return [
            {"id": "one", "type": "dataset", "context_id": "ctx-a"},
            {"id": "two", "type": "document", "metadata": {"context_id": "ctx-b"}},
        ]


@pytest.fixture
def fake_dataos(monkeypatch):
    fake = FakeDataOS()
    monkeypatch.setattr(api, "dataos", fake)
    return fake


def run(coro):
    return asyncio.run(coro)


def test_compute_sql_uses_public_kernel_method(fake_dataos):
    result = run(api.compute_sql(api.SQLQueryRequest(query="SELECT 1")))
    assert result == {"kind": "sql", "query": "SELECT 1"}
    assert fake_dataos.calls[-1] == ("sql", "SELECT 1")


def test_compute_python_uses_public_kernel_method(fake_dataos):
    result = run(api.compute_python(api.PythonComputeRequest(code="print(1)", input_object_ids=["obj-1"])))
    assert result["kind"] == "python"
    assert fake_dataos.calls[-1] == ("python", "print(1)", ["obj-1"])


@pytest.mark.parametrize(
    ("query_type", "expected_kind"),
    [("auto", "ask"), ("sql", "sql"), ("python", "python"), ("search", "search")],
)
def test_unified_query_dispatches_only_to_supported_methods(fake_dataos, query_type, expected_kind):
    result = run(api.query_unified(api.UnifiedQueryRequest(query="SELECT 1", query_type=query_type)))
    if expected_kind == "search":
        assert result["total_matches"] == 2
    else:
        assert result["kind"] == expected_kind


def test_unified_query_rejects_unknown_query_type(fake_dataos):
    with pytest.raises(HTTPException) as exc:
        run(api.query_unified(api.UnifiedQueryRequest(query="hello", query_type="magic")))
    assert exc.value.status_code == 400


def test_hybrid_search_uses_supported_method_and_filters_results(fake_dataos):
    result = run(api.hybrid_search(q="customer", object_type="dataset", context_id="ctx-a", limit=7))
    assert result["results"] == [{"id": "one", "type": "dataset", "context_id": "ctx-a"}]
    assert fake_dataos.calls[-1] == ("search", "customer", 7)


def test_neighbors_and_traversal_use_graph_namespace(fake_dataos):
    assert run(api.get_neighbors("obj-1"))["neighbors"] == [{"id": "neighbor-1"}]
    assert run(api.traverse_graph("obj-1", max_hops=2, min_confidence=0.5))["total_nodes_reached"] == 2
    assert fake_dataos.calls[-1] == ("traverse", {"start_id": "obj-1", "max_hops": 2, "min_confidence": 0.5})


def test_graph_analytics_uses_graph_analytics_engine(fake_dataos):
    assert run(api.graph_analytics("pagerank"))["scores"] == {"a": 1.0}
    assert run(api.graph_analytics("centrality"))["degree_centrality"] == {"a": 0.5}
    assert run(api.graph_analytics("communities"))["communities"] == [["a"]]


def test_create_relationship_uses_graph_namespace(fake_dataos):
    result = run(api.create_relationship(api.RelationCreateRequest(source_id="a", target_id="b")))
    assert result == {"source_id": "a", "target_id": "b"}
    assert fake_dataos.calls[-1][0] == "create_relation"


def test_catalog_health_checks_storage_and_does_not_leak_internal_errors(fake_dataos):
    result = run(api.get_health_overview())
    assert result["status"] == "operational"
    assert result["storage"] == "available"

    def fail(**kwargs):
        raise RuntimeError("private database path")
    fake_dataos.storage.list_objects = fail
    with pytest.raises(HTTPException) as exc:
        run(api.get_health_overview())
    assert exc.value.status_code == 503
    assert exc.value.detail == "DataOS storage unavailable"
    assert "private database path" not in exc.value.detail
