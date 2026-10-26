"""Regression tests for FastAPI routes against the supported DataOS kernel API."""

import asyncio
from types import SimpleNamespace
import importlib

import pytest
from fastapi import HTTPException
from starlette.requests import Request

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



def test_python_compute_is_disabled_by_default_in_production(monkeypatch):
    monkeypatch.setenv("DATAOS_ENV", "production")
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("DATAOS_ALLOW_PYTHON_COMPUTE", raising=False)

    def should_not_execute(*args, **kwargs):
        pytest.fail("Python execution must be rejected before reaching the runtime")

    monkeypatch.setattr(api.dataos, "python", should_not_execute)
    with pytest.raises(HTTPException) as direct_exc:
        run(api.compute_python(api.PythonComputeRequest(code="print('blocked')")))
    assert direct_exc.value.status_code == 403

    with pytest.raises(HTTPException) as unified_exc:
        run(api.query_unified(api.UnifiedQueryRequest(query="print('blocked')", query_type="python")))
    assert unified_exc.value.status_code == 403


def test_python_compute_requires_explicit_production_opt_in(monkeypatch):
    monkeypatch.setenv("DATAOS_ENV", "production")
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("DATAOS_ALLOW_PYTHON_COMPUTE", "true")
    monkeypatch.setattr(api.dataos, "python", lambda code, input_object_ids=None: {"executed": code})
    result = run(api.compute_python(api.PythonComputeRequest(code="print(1)")))
    assert result == {"executed": "print(1)"}


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


def test_workflow_route_rejects_malformed_definition():
    # The workflow endpoint is implemented: an empty definition is invalid input,
    # so it must fail validation rather than claim the feature is unimplemented.
    with pytest.raises(HTTPException) as workflow_exc:
        run(api.execute_workflow(api.WorkflowExecutionRequest(definition={})))
    assert workflow_exc.value.status_code == 422
    assert "nodes" in workflow_exc.value.detail


def test_duplicate_detection_route_returns_candidates_without_graph_mutation(monkeypatch):
    matches = [{
        "object_a_id": "a",
        "object_b_id": "b",
        "similarity_score": 1.0,
        "method": "exact_hash",
        "is_exact_duplicate": True,
    }]
    called = {}

    def find_duplicates(**kwargs):
        called.update(kwargs)
        return matches

    monkeypatch.setattr(api.duplicate_detection_engine, "find_duplicates", find_duplicates)
    monkeypatch.setattr(api.dataos.storage, "list_objects", lambda **kwargs: [object(), object()])
    result = run(api.detect_duplicates_api(min_similarity=0.8))

    assert result == {
        "object_id": None,
        "min_similarity": 0.8,
        "catalog_objects_observed": 2,
        "catalog_count_capped": False,
        "scanned_objects": 2,
        "truncated": False,
        "total": 1,
        "duplicates": matches,
    }
    assert called == {
        "target_object_id": None,
        "min_similarity": 0.8,
        "auto_link_graph": False,
    }


def test_duplicate_detection_route_reports_when_catalog_scan_is_truncated(monkeypatch):
    monkeypatch.setattr(api.dataos.storage, "list_objects", lambda **kwargs: list(range(1001)))
    monkeypatch.setattr(api.duplicate_detection_engine, "find_duplicates", lambda **kwargs: [])
    result = run(api.detect_duplicates_api())
    assert result["catalog_objects_observed"] == 1001
    assert result["catalog_count_capped"] is True
    assert result["scanned_objects"] == 1000
    assert result["truncated"] is True


def test_duplicate_detection_route_rejects_unknown_object(monkeypatch):
    monkeypatch.setattr(api.dataos.storage, "get_object", lambda object_id: None)
    monkeypatch.setattr(
        api.duplicate_detection_engine,
        "find_duplicates",
        lambda **kwargs: pytest.fail("must not scan when target object does not exist"),
    )
    with pytest.raises(HTTPException) as exc:
        run(api.detect_duplicates_api(object_id="missing"))
    assert exc.value.status_code == 404


def test_duplicate_detection_target_lookup_runs_in_threadpool(monkeypatch):
    calls = []
    target = object()

    def get_object(object_id):
        assert object_id == "known"
        return target

    original_run_in_threadpool = api.run_in_threadpool

    async def tracking_run_in_threadpool(func, *args, **kwargs):
        calls.append(func)
        return await original_run_in_threadpool(func, *args, **kwargs)

    monkeypatch.setattr(api.dataos.storage, "get_object", get_object)
    monkeypatch.setattr(api.dataos.storage, "list_objects", lambda **kwargs: [])
    monkeypatch.setattr(api.duplicate_detection_engine, "find_duplicates", lambda **kwargs: [])
    monkeypatch.setattr(api, "run_in_threadpool", tracking_run_in_threadpool)

    result = run(api.detect_duplicates_api(object_id="known"))

    assert result["object_id"] == "known"
    assert get_object in calls


def test_duplicate_detection_route_validates_similarity_and_object_id():
    with pytest.raises(HTTPException) as similarity_exc:
        run(api.detect_duplicates_api(min_similarity=1.01))
    assert similarity_exc.value.status_code == 422

    with pytest.raises(HTTPException) as object_exc:
        run(api.detect_duplicates_api(object_id="   "))
    assert object_exc.value.status_code == 422


@pytest.mark.parametrize("threshold", [float("nan"), float("inf"), float("-inf")])
def test_duplicate_detection_rejects_non_finite_similarity_threshold(threshold):
    with pytest.raises(HTTPException) as exc:
        run(api.detect_duplicates_api(min_similarity=threshold))
    assert exc.value.status_code == 422


def test_workflow_route_rejects_overload_with_retry_after(monkeypatch):
    # A saturated worker budget must fail fast instead of queueing more DAG work.
    monkeypatch.setattr(
        api,
        "workflow_slots",
        SimpleNamespace(acquire=lambda blocking=False: False, release=lambda: None),
    )
    request = api.WorkflowExecutionRequest(
        definition={"nodes": {"n": {"action_type": "noop"}}}
    )
    with pytest.raises(HTTPException) as exc:
        run(api.execute_workflow(request))
    assert exc.value.status_code == 503
    assert exc.value.headers["Retry-After"] == "1"
    assert "capacity is full" in exc.value.detail


def test_workflow_capacity_is_released_after_validation_error(monkeypatch):
    class TrackingSlots:
        active = False

        def acquire(self, blocking=False):
            if self.active:
                return False
            self.active = True
            return True

        def release(self):
            assert self.active
            self.active = False

    slots = TrackingSlots()
    monkeypatch.setattr(api, "workflow_slots", slots)
    with pytest.raises(HTTPException) as exc:
        run(api.execute_workflow(api.WorkflowExecutionRequest(definition={})))
    assert exc.value.status_code == 422
    assert slots.active is False


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


def _api_request(path, authorization=None):
    headers = []
    if authorization is not None:
        headers.append((b"authorization", authorization.encode("utf-8")))
    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "headers": headers,
        "client": ("testclient", 12345),
        "server": ("testserver", 80),
    })


def test_production_api_auth_fails_closed_without_or_with_weak_token(monkeypatch):
    monkeypatch.setenv("DATAOS_ENV", "production")
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("DATAOS_API_TOKEN", raising=False)

    with pytest.raises(HTTPException) as missing:
        api.require_production_api_token(_api_request("/api/objects/"), None)
    assert missing.value.status_code == 503

    monkeypatch.setenv("DATAOS_API_TOKEN", "short")
    with pytest.raises(HTTPException) as weak:
        api.require_production_api_token(_api_request("/api/objects/"), None)
    assert weak.value.status_code == 503


def test_production_api_auth_rejects_invalid_bearer_and_accepts_valid_token(monkeypatch):
    token = "test-only-token-with-at-least-32-bytes"
    monkeypatch.setenv("DATAOS_ENV", "production")
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("DATAOS_API_TOKEN", token)

    with pytest.raises(HTTPException) as invalid:
        api.require_production_api_token(_api_request("/api/objects/"), "Bearer wrong")
    assert invalid.value.status_code == 401
    assert invalid.value.headers["WWW-Authenticate"] == "Bearer"

    assert api.require_production_api_token(_api_request("/api/objects/"), f"Bearer {token}") is None


def test_conflicting_environment_markers_cannot_disable_production_api_auth(monkeypatch):
    monkeypatch.setenv("DATAOS_ENV", "development")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("DATAOS_API_TOKEN", raising=False)

    with pytest.raises(HTTPException) as exc:
        api.require_production_api_token(_api_request("/api/compute/python"), None)
    assert exc.value.status_code == 503


def test_non_api_health_path_remains_available_without_api_token(monkeypatch):
    monkeypatch.setenv("DATAOS_ENV", "production")
    monkeypatch.delenv("DATAOS_API_TOKEN", raising=False)

    assert api.require_production_api_token(_api_request("/health"), None) is None

    api_routes = [
        route for route in api.app.routes
        if getattr(route, "path", "").startswith("/api/")
    ]
    assert api_routes
    assert all(
        any(dependency.call is api.require_production_api_token for dependency in route.dependant.dependencies)
        for route in api_routes
    )
