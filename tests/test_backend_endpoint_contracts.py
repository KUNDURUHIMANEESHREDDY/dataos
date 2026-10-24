import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

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

def test_expensive_query_routes_publish_bounded_parameters():
    schema = api.app.openapi()

    def params(path):
        return {item["name"]: item["schema"] for item in schema["paths"][path]["get"]["parameters"]}

    vector = params("/api/vectors/search")
    assert vector["q"]["minLength"] == 1
    assert vector["q"]["maxLength"] == 1000
    assert vector["top_k"]["minimum"] == 1
    assert vector["top_k"]["maximum"] == 100

    lineage = params("/api/provenance/lineage/{object_id}")
    assert lineage["direction"]["pattern"] == "^(upstream|downstream)$"
    assert lineage["max_depth"]["minimum"] == 1
    assert lineage["max_depth"]["maximum"] == 20

    duplicates = params("/api/governance/duplicates")
    assert duplicates["min_similarity"]["minimum"] == 0.0
    assert duplicates["min_similarity"]["maximum"] == 1.0


def test_sharing_token_contract_bounds_lifetime_and_allowlists():
    schema = api.app.openapi()["components"]["schemas"]["IssueSharingTokenRequest"]["properties"]
    assert schema["duration_seconds"]["minimum"] == 1
    assert schema["duration_seconds"]["maximum"] == 86400
    object_id_array = next(item for item in schema["allowed_object_ids"]["anyOf"] if item.get("type") == "array")
    capability_array = next(item for item in schema["allowed_capabilities"]["anyOf"] if item.get("type") == "array")
    assert object_id_array["maxItems"] == 1000
    assert capability_array["maxItems"] == 100



def test_notebook_ingestion_uses_universal_pipeline(fake_dataos):
    fake_dataos.ingest = Mock(return_value={"id": "notebook-1"})
    content = '{"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}'

    result = run(api.ingest_notebook_api("analysis.ipynb", content))

    assert result == {"id": "notebook-1"}
    fake_dataos.ingest.assert_called_once_with(content, filename="analysis.ipynb", discover_relations=True)


def test_rich_document_ingestion_uses_universal_pipeline(fake_dataos):
    fake_dataos.ingest = Mock(return_value={"id": "document-1"})
    content = "# Report\n\nA table and citations."

    result = run(api.extract_rich_document_api("report.md", content))

    assert result == {"id": "document-1"}
    fake_dataos.ingest.assert_called_once_with(content, filename="report.md", discover_relations=True)


def test_text_ingestion_uses_in_memory_content_and_infers_text_extension(fake_dataos):
    fake_dataos.ingest = Mock(return_value={"id": "text-1"})

    result = run(api.ingest_text("notes", "plain text", "text"))

    assert result == {"id": "text-1"}
    fake_dataos.ingest.assert_called_once_with("plain text", filename="notes.txt", discover_relations=True)


def test_time_travel_routes_use_registered_engine(monkeypatch):
    object_value = SimpleNamespace(to_dict=lambda: {"id": "obj-1", "version": 2})
    engine = SimpleNamespace(
        get_object_as_of=Mock(return_value=object_value),
        get_graph_as_of=Mock(return_value={"nodes": []}),
        changes_between=Mock(return_value={"changes": []}),
    )
    monkeypatch.setattr(api, "dataos", SimpleNamespace(time_travel=engine))

    assert run(api.time_travel_object("obj-1", "2026-01-01T00:00:00Z", temporal_axis="system_time")) == {"id": "obj-1", "version": 2}
    assert run(api.time_travel_graph("2026-01-01T00:00:00Z", temporal_axis="system_time")) == {"nodes": []}
    assert run(api.time_travel_changes("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", temporal_axis="system_time")) == {"changes": []}
    engine.get_object_as_of.assert_called_once_with("obj-1", as_of_timestamp="2026-01-01T00:00:00Z", temporal_axis="system_time")
    engine.get_graph_as_of.assert_called_once_with(as_of_timestamp="2026-01-01T00:00:00Z", temporal_axis="system_time")
    engine.changes_between.assert_called_once_with("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", temporal_axis="system_time")


def test_conflict_resolution_uses_sync_engine(monkeypatch):
    sync = SimpleNamespace(resolve_conflict=Mock(return_value={"resolved": True}))
    monkeypatch.setattr(api, "dataos", SimpleNamespace(sync=sync))

    result = run(api.resolve_conflict_api(api.ConflictResolutionRequest(conflict_object_id="conflict-1")))

    assert result == {"resolved": True}
    assert sync.resolve_conflict.call_args.kwargs["conflict_object_id"] == "conflict-1"


def test_multi_agent_pipeline_uses_registered_orchestrator(monkeypatch):
    pipeline = SimpleNamespace(run_end_to_end_research_pipeline=Mock(return_value={"pipeline_id": "p-1"}))
    monkeypatch.setattr(api, "dataos", SimpleNamespace(multi_agent=pipeline))

    result = run(api.run_multi_agent_pipeline_api(api.MultiAgentPipelineRequest(
        goal_prompt="Summarize customers",
        target_dataset_id="dataset-1",
        analysis_sql_or_python="SELECT COUNT(*) FROM customers",
    )))

    assert result == {"pipeline_id": "p-1"}
    assert pipeline.run_end_to_end_research_pipeline.call_args.kwargs["target_dataset_id"] == "dataset-1"


def test_connection_recommendations_use_graph_namespace(monkeypatch):
    graph = SimpleNamespace(recommendations=Mock(return_value=[{"id": "related-1"}]))
    monkeypatch.setattr(api, "dataos", SimpleNamespace(graph=graph))

    result = run(api.recommend_connections_api("object-1", top_k=3))

    assert result["recommendations"] == [{"id": "related-1"}]
    graph.recommendations.assert_called_once_with("object-1", top_k=3)


def test_dataset_recommendations_search_and_filter_results(monkeypatch):
    source = SimpleNamespace(properties={"filename": "customers.csv", "title": "Customer table"})
    storage = SimpleNamespace(get_object=Mock(return_value=source))
    search = Mock(return_value=[
        {"id": "doc-1", "type": "document"},
        {"id": "dataset-1", "type": "dataset"},
        {"id": "dataset-2", "object_type": "dataset"},
    ])
    monkeypatch.setattr(api, "dataos", SimpleNamespace(storage=storage, search=search))

    result = run(api.recommend_datasets_api("source-1", top_k=1))

    assert result["recommended_datasets"] == [{"id": "dataset-1", "type": "dataset"}]
    search.assert_called_once_with("customers.csv Customer table", top_k=5)


def test_unimplemented_privileged_routes_fail_explicitly_not_with_attribute_errors(monkeypatch):
    monkeypatch.setattr(api, "dataos", SimpleNamespace())

    with pytest.raises(HTTPException) as agent_exc:
        run(api.execute_agent(api.AgentExecutionRequest(agent_id="unknown", capability="read_object", params={})))
    assert agent_exc.value.status_code == 501

    with pytest.raises(HTTPException) as workflow_exc:
        run(api.execute_workflow(api.WorkflowExecutionRequest(definition={}, context={})))
    assert workflow_exc.value.status_code == 501




def test_duplicate_detection_is_read_only_for_get_requests(monkeypatch):
    engine = SimpleNamespace(find_duplicates=Mock(return_value=[{"id": "duplicate-1", "similarity_score": 0.9}]))
    monkeypatch.setattr(api, "duplicate_detection", engine)

    result = run(api.detect_duplicates_api(object_id="object-1", min_similarity=0.8))

    assert result["total_matches"] == 1
    assert result["duplicates"][0]["similarity_score"] == 0.9
    engine.find_duplicates.assert_called_once_with(
        target_object_id="object-1",
        min_similarity=0.8,
        auto_link_graph=False,
    )
