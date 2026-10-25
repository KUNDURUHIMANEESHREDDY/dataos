"""Regression tests for FastAPI routes against the supported DataOS kernel API."""

import asyncio
from types import SimpleNamespace
import importlib

import pytest
from fastapi import HTTPException

api = importlib.import_module("backend.app")


def run(coro):
    return asyncio.run(coro)


def test_relationship_creation_uses_graph_namespace(monkeypatch):
    expected = SimpleNamespace(to_dict=lambda: {"id": "rel-1"})
    called = {}
    def create_relation(**kwargs):
        called.update(kwargs)
        return expected
    monkeypatch.setattr(api.dataos.graph, "create_relation", create_relation)
    result = run(api.create_relationship(api.RelationCreateRequest(
        source_id="source", target_id="target", relation_type="references", confidence=0.8
    )))
    assert result == {"id": "rel-1"}
    assert called["source_id"] == "source"
    assert called["target_id"] == "target"


def test_graph_neighbors_uses_graph_namespace(monkeypatch):
    monkeypatch.setattr(api.dataos.graph, "neighbors", lambda object_id, direction: [{"neighbor_id": "b"}])
    result = run(api.get_neighbors("a", direction="incoming"))
    assert result == {"object_id": "a", "total": 1, "neighbors": [{"neighbor_id": "b"}]}


def test_graph_traversal_uses_engine_contract(monkeypatch):
    engine = SimpleNamespace(traverse=lambda **kwargs: {"visited": [kwargs["start_id"]], "hops": kwargs["max_hops"]})
    monkeypatch.setattr(api.dataos.graph, "engine", engine)
    result = run(api.traverse_graph("root", max_hops=2, min_confidence=0.4))
    assert result == {"visited": ["root"], "hops": 2}


def test_graph_analytics_uses_supported_namespace(monkeypatch):
    metrics = {
        "pagerank": {"a": 1.0},
        "degree_centrality": {"a": 0.5},
        "betweenness_centrality": {"a": 0.2},
        "communities": [["a"]],
    }
    monkeypatch.setattr(api.dataos.graph, "analytics", lambda: metrics)
    assert run(api.graph_analytics("pagerank")) == {"algorithm": "pagerank", "scores": {"a": 1.0}}
    assert run(api.graph_analytics("centrality")) == {
        "degree_centrality": {"a": 0.5}, "betweenness_centrality": {"a": 0.2}
    }
    assert run(api.graph_analytics("communities")) == {"communities": [["a"]]}


def test_compute_routes_call_real_kernel_methods(monkeypatch):
    monkeypatch.setattr(api.dataos, "sql", lambda query: {"sql": query})
    monkeypatch.setattr(api.dataos, "python", lambda code, input_object_ids=None: {"code": code, "inputs": input_object_ids})
    assert run(api.compute_sql(api.SQLQueryRequest(query="SELECT 1"))) == {"sql": "SELECT 1"}
    assert run(api.compute_python(api.PythonComputeRequest(code="print(1)", input_object_ids=["obj-1"]))) == {
        "code": "print(1)", "inputs": ["obj-1"]
    }


def test_unified_query_auto_dispatches_sql_and_natural_language(monkeypatch):
    monkeypatch.setattr(api.dataos, "sql", lambda query: {"kind": "sql", "query": query})
    monkeypatch.setattr(api.dataos, "ask", lambda query: {"kind": "ask", "query": query})
    assert run(api.query_unified(api.UnifiedQueryRequest(query="SELECT 1"))) == {
        "kind": "sql", "query": "SELECT 1"
    }
    assert run(api.query_unified(api.UnifiedQueryRequest(query="Why is this dataset empty?"))) == {
        "kind": "ask", "query": "Why is this dataset empty?"
    }


def test_unified_query_rejects_unknown_type(monkeypatch):
    with pytest.raises(HTTPException) as exc:
        run(api.query_unified(api.UnifiedQueryRequest(query="x", query_type="not-a-mode")))
    assert exc.value.status_code == 400


def test_vector_recompute_uses_vector_index(monkeypatch):
    index = SimpleNamespace(recompute_all=lambda storage: {"indexed": 3, "backend": type(storage).__name__})
    monkeypatch.setattr(api.dataos, "vector_index", index)
    result = run(api.recompute_vectors())
    assert result["indexed"] == 3


def test_time_travel_routes_use_time_travel_engine(monkeypatch):
    object_value = SimpleNamespace(to_dict=lambda: {"id": "obj-1", "version": 1})
    engine = SimpleNamespace(
        get_object_as_of=lambda object_id, as_of_timestamp, temporal_axis: object_value,
        get_graph_as_of=lambda as_of_timestamp, temporal_axis: {"as_of": as_of_timestamp},
        changes_between=lambda t1, t2, temporal_axis: {"from": t1, "to": t2},
    )
    monkeypatch.setattr(api.dataos, "time_travel", engine)
    assert run(api.time_travel_object("obj-1", as_of="2026-01-01T00:00:00Z")) == {
        "id": "obj-1", "version": 1
    }
    assert run(api.time_travel_graph(as_of="2026-01-01T00:00:00Z")) == {
        "as_of": "2026-01-01T00:00:00Z"
    }
    assert run(api.time_travel_changes(t1="2026-01-01", t2="2026-01-02")) == {
        "from": "2026-01-01", "to": "2026-01-02"
    }


def test_ingest_text_does_not_use_client_filename_as_temp_path(monkeypatch):
    called = {}
    def ingest(content, filename, discover_relations):
        called.update(content=content, filename=filename, discover_relations=discover_relations)
        return {"status": "ingested"}
    monkeypatch.setattr(api.dataos, "ingest", ingest)
    result = run(api.ingest_text(filename="../../outside.md", content="safe text"))
    assert result == {"status": "ingested"}
    assert called == {"content": "safe text", "filename": "outside.md", "discover_relations": True}


def test_sharing_token_routes_fail_closed_without_secret(monkeypatch):
    monkeypatch.delenv("DATAOS_SHARING_TOKEN_SECRET", raising=False)
    request = api.IssueSharingTokenRequest(
        issuer="service", subject_principal="reader", subgraph_root_id="root"
    )
    with pytest.raises(HTTPException) as issue_exc:
        run(api.issue_sharing_token_api(request))
    assert issue_exc.value.status_code == 503
    with pytest.raises(HTTPException) as verify_exc:
        run(api.verify_sharing_token_api(api.VerifySharingTokenRequest(token="invalid")))
    assert verify_exc.value.status_code == 503


def test_health_probe_returns_service_unavailable_when_storage_fails(monkeypatch):
    def unavailable(*args, **kwargs):
        raise RuntimeError("database detail must not leak")
    monkeypatch.setattr(api.dataos.storage, "list_objects", unavailable)
    with pytest.raises(HTTPException) as exc:
        run(api.health_check())
    assert exc.value.status_code == 503
    assert exc.value.detail == "DataOS storage is unavailable"


def test_unimplemented_workflow_and_duplicate_routes_return_501():
    with pytest.raises(HTTPException) as workflow_exc:
        run(api.execute_workflow(api.WorkflowExecutionRequest(definition={})))
    assert workflow_exc.value.status_code == 501
    with pytest.raises(HTTPException) as duplicate_exc:
        run(api.detect_duplicates_api())
    assert duplicate_exc.value.status_code == 501


def test_recommendation_routes_use_available_engines(monkeypatch):
    monkeypatch.setattr(api.dataos.graph, "recommendations", lambda object_id, top_k: [{"id": object_id, "top_k": top_k}])
    assert run(api.recommend_connections_api("obj-1", top_k=3)) == {
        "target_object_id": "obj-1", "recommendations": [{"id": "obj-1", "top_k": 3}]
    }

    target = SimpleNamespace(properties={"filename": "sales.csv"}, type="dataset")
    monkeypatch.setattr(api.dataos.storage, "get_object", lambda object_id: target)
    monkeypatch.setattr(
        api.dataos.search_engine,
        "search",
        lambda **kwargs: [{"query": kwargs["query"], "type": kwargs["object_type"]}],
    )
    assert run(api.recommend_datasets_api("obj-1", top_k=2)) == {
        "target_object_id": "obj-1",
        "recommended_datasets": [{"query": "sales.csv", "type": "dataset"}],
    }


def test_multi_agent_pipeline_uses_runtime_orchestrator(monkeypatch):
    monkeypatch.setattr(
        api.dataos.multi_agent,
        "run_end_to_end_research_pipeline",
        lambda **kwargs: {"goal": kwargs["goal_prompt"], "target": kwargs["target_dataset_id"]},
    )
    result = run(api.run_multi_agent_pipeline_api(api.MultiAgentPipelineRequest(
        goal_prompt="profile sales", target_dataset_id="sales-1", analysis_sql_or_python="SELECT 1"
    )))
    assert result == {"goal": "profile sales", "target": "sales-1"}


def test_sharing_duration_validation():
    with pytest.raises(Exception):
        api.IssueSharingTokenRequest(
            issuer="service", subject_principal="reader", subgraph_root_id="root", duration_seconds=90000
        )
