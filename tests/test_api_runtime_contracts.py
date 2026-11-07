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


@pytest.mark.parametrize("direction", ["sideways", "", "UPSTREAM"])
def test_lineage_rejects_unknown_direction_before_traversal(monkeypatch, direction):
    def unexpected(*args, **kwargs):
        pytest.fail("lineage traversal must not run for an invalid direction")

    monkeypatch.setattr(api.dataos.lineage, "trace_upstream_lineage", unexpected)
    monkeypatch.setattr(api.dataos.lineage, "trace_downstream_impact", unexpected)
    with pytest.raises(HTTPException) as exc:
        run(api.get_lineage("root", direction=direction, max_depth=1))
    assert exc.value.status_code == 400


@pytest.mark.parametrize("max_depth", [0, -1, 33, 10_000])
def test_lineage_rejects_unbounded_depth_before_traversal(monkeypatch, max_depth):
    def unexpected(*args, **kwargs):
        pytest.fail("lineage traversal must not run for an out-of-range depth")

    monkeypatch.setattr(api.dataos.lineage, "trace_upstream_lineage", unexpected)
    monkeypatch.setattr(api.dataos.lineage, "trace_downstream_impact", unexpected)
    with pytest.raises(HTTPException) as exc:
        run(api.get_lineage("root", direction="upstream", max_depth=max_depth))
    assert exc.value.status_code == 422


def test_lineage_accepts_only_supported_directions_with_bounded_depth(monkeypatch):
    monkeypatch.setattr(
        api.dataos.lineage,
        "trace_upstream_lineage",
        lambda object_id, max_depth: {"direction": "upstream", "depth": max_depth},
    )
    monkeypatch.setattr(
        api.dataos.lineage,
        "trace_downstream_impact",
        lambda object_id, max_depth: {"direction": "downstream", "depth": max_depth},
    )
    assert run(api.get_lineage("root", direction="upstream", max_depth=32)) == {
        "direction": "upstream", "depth": 32
    }
    assert run(api.get_lineage("root", direction="downstream", max_depth=1)) == {
        "direction": "downstream", "depth": 1
    }


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
        run(api.query_unified(api.UnifiedQueryRequest(query="print('blocked')", query_type="python"), current_user=None))
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
    assert run(api.query_unified(api.UnifiedQueryRequest(query="SELECT 1"), current_user=None)) == {
        "kind": "sql", "query": "SELECT 1"
    }
    assert run(api.query_unified(api.UnifiedQueryRequest(query="Why is this dataset empty?"), current_user=None)) == {
        "kind": "ask", "query": "Why is this dataset empty?"
    }


def test_unified_query_rejects_unknown_type(monkeypatch):
    with pytest.raises(HTTPException) as exc:
        run(api.query_unified(api.UnifiedQueryRequest(query="x", query_type="not-a-mode"), current_user=None))
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
        "as_of": "2026-01-01T00:00:00+00:00"
    }
    assert run(api.time_travel_changes(t1="2026-01-01T00:00:00Z", t2="2026-01-02T00:00:00Z")) == {
        "from": "2026-01-01T00:00:00+00:00", "to": "2026-01-02T00:00:00+00:00"
    }


def test_time_travel_normalizes_offsets_before_engine_comparisons(monkeypatch):
    called = {}
    engine = SimpleNamespace(
        changes_between=lambda t1, t2, temporal_axis: called.update(
            t1=t1, t2=t2, temporal_axis=temporal_axis
        ) or {"from": t1, "to": t2}
    )
    monkeypatch.setattr(api.dataos, "time_travel", engine)

    result = run(api.time_travel_changes(
        t1="2026-01-01T00:30:00+01:00",
        t2="2026-01-01T00:00:00Z",
        temporal_axis="validity_time",
    ))
    assert result == {
        "from": "2025-12-31T23:30:00+00:00",
        "to": "2026-01-01T00:00:00+00:00",
    }
    assert called == {
        "t1": "2025-12-31T23:30:00+00:00",
        "t2": "2026-01-01T00:00:00+00:00",
        "temporal_axis": "validity_time",
    }


def test_time_travel_rejects_naive_and_reversed_timestamps(monkeypatch):
    def should_not_execute(*args, **kwargs):
        pytest.fail("invalid time-travel input must be rejected before engine execution")

    monkeypatch.setattr(api.dataos, "time_travel", SimpleNamespace(
        get_object_as_of=should_not_execute,
        changes_between=should_not_execute,
    ))
    with pytest.raises(HTTPException) as naive_exc:
        run(api.time_travel_object("obj-1", as_of="2026-01-01T00:00:00"))
    assert naive_exc.value.status_code == 422
    assert "UTC offset" in naive_exc.value.detail

    with pytest.raises(HTTPException) as order_exc:
        run(api.time_travel_changes(
            t1="2026-01-02T00:00:00Z",
            t2="2026-01-01T00:00:00Z",
        ))
    assert order_exc.value.status_code == 422
    assert "earlier than or equal" in order_exc.value.detail


def test_time_travel_openapi_declares_temporal_axis_enum():
    parameters = api.app.openapi()["paths"]["/api/time_travel/object/{object_id}"]["get"]["parameters"]
    temporal_axis = next(parameter for parameter in parameters if parameter["name"] == "temporal_axis")
    assert temporal_axis["schema"]["enum"] == ["system_time", "validity_time"]
    assert temporal_axis["schema"]["default"] == "system_time"


def test_time_travel_rejects_malformed_whitespace_and_oversized_timestamps():
    for value in (" 2026-01-01T00:00:00Z", "not-a-timestamp", "x" * 65):
        with pytest.raises(HTTPException) as exc:
            run(api.time_travel_object("obj-1", as_of=value))
        assert exc.value.status_code == 422
        assert "ISO 8601 timestamp" in exc.value.detail

def test_time_travel_rejects_utc_normalization_overflow():
    for value in (
        "0001-01-01T00:00:00+01:00",
        "9999-12-31T23:59:59-01:00",
    ):
        with pytest.raises(HTTPException) as exc:
            run(api.time_travel_object("obj-1", as_of=value))
        assert exc.value.status_code == 422
        assert "representable as a UTC timestamp" in exc.value.detail

def test_ingest_text_does_not_use_client_filename_as_temp_path(monkeypatch):
    called = {}
    def ingest(content, filename, discover_relations, permissions=None):
        called.update(content=content, filename=filename, discover_relations=discover_relations, permissions=permissions)
        return {"status": "ingested"}
    monkeypatch.setattr(api.dataos, "ingest", ingest)
    result = run(api.ingest_text(filename="../../outside.md", content="safe text", current_user=None))
    assert result == {"status": "ingested"}
    assert called == {"content": "safe text", "filename": "outside.md", "discover_relations": True, "permissions": None}


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


def test_workflow_route_rejects_malformed_definition_and_duplicate_route_uses_engine():
    # The workflow endpoint is implemented: an empty definition is invalid input,
    # so it must fail validation rather than claim the feature is unimplemented.
    with pytest.raises(HTTPException) as workflow_exc:
        run(api.execute_workflow(api.WorkflowExecutionRequest(definition={})))
    assert workflow_exc.value.status_code == 422
    assert "nodes" in workflow_exc.value.detail

    # Duplicate detection is implemented via DuplicateDetectionEngine and must
    # return a result payload (empty store -> no duplicates), not a 501 stub.
    result = run(api.detect_duplicates_api())
    assert result["total"] == 0
    assert result["duplicates"] == []


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


def test_graph_neighbors_publishes_supported_direction_contract():
    parameters = api.app.openapi()["paths"]["/api/graph/neighbors/{object_id}"]["get"]["parameters"]
    direction = next(parameter for parameter in parameters if parameter["name"] == "direction")
    assert direction["schema"]["enum"] == ["outgoing", "incoming", "both"]
    assert direction["schema"]["default"] == "both"


def test_graph_neighbors_dispatches_each_supported_direction(monkeypatch):
    calls = []
    monkeypatch.setattr(
        api.dataos.graph,
        "neighbors",
        lambda object_id, direction: calls.append((object_id, direction)) or [],
    )

    for direction in ("outgoing", "incoming", "both"):
        assert run(api.get_neighbors("root", direction=direction)) == {
            "object_id": "root", "total": 0, "neighbors": []
        }

    assert calls == [("root", "outgoing"), ("root", "incoming"), ("root", "both")]


def test_lineage_route_publishes_bounded_query_contract():
    parameters = api.app.openapi()["paths"]["/api/provenance/lineage/{object_id}"]["get"]["parameters"]
    by_name = {parameter["name"]: parameter for parameter in parameters}

    assert by_name["direction"]["schema"]["enum"] == ["upstream", "downstream"]
    assert by_name["direction"]["schema"]["default"] == "upstream"
    assert by_name["max_depth"]["schema"]["minimum"] == 1
    assert by_name["max_depth"]["schema"]["maximum"] == 32
    assert by_name["max_depth"]["schema"]["default"] == 10


def test_lineage_route_dispatches_only_the_two_supported_directions(monkeypatch):
    calls = []
    lineage = SimpleNamespace(
        trace_upstream_lineage=lambda object_id, max_depth: calls.append(
            ("upstream", object_id, max_depth)
        ) or {"direction": "upstream", "object_id": object_id, "max_depth": max_depth},
        trace_downstream_impact=lambda object_id, max_depth: calls.append(
            ("downstream", object_id, max_depth)
        ) or {"direction": "downstream", "object_id": object_id, "max_depth": max_depth},
    )
    monkeypatch.setattr(api.dataos, "lineage", lineage)

    upstream = run(api.get_lineage("root", "upstream", 4))
    downstream = run(api.get_lineage("root", "downstream", 2))

    assert upstream == {"direction": "upstream", "object_id": "root", "max_depth": 4}
    assert downstream == {"direction": "downstream", "object_id": "root", "max_depth": 2}
    assert calls == [("upstream", "root", 4), ("downstream", "root", 2)]

@pytest.mark.parametrize(
    ("managed_key", "managed_value"),
    [
        ("content_hash", "0" * 64),
        ("blob", {"sha256": "0" * 64, "path": "/untrusted/client/path"}),
    ],
)
def test_object_creation_rejects_client_supplied_storage_metadata(
    monkeypatch, managed_key, managed_value
):
    def unexpected_save(_obj):
        pytest.fail("server-managed metadata must be rejected before persistence")

    monkeypatch.setattr(api.dataos.storage, "save_object", unexpected_save)
    request = api.ObjectCreateRequest(metadata={managed_key: managed_value})

    with pytest.raises(HTTPException) as exc:
        run(api.create_object(request, current_user=None))

    assert exc.value.status_code == 422
    assert "managed by DataOS" in exc.value.detail
    assert managed_key in exc.value.detail


def test_object_creation_preserves_ordinary_client_metadata(monkeypatch):
    saved = {}

    def capture_object(obj):
        saved["object"] = obj
        return obj

    monkeypatch.setattr(api.dataos.storage, "save_object", capture_object)
    result = run(api.create_object(
        api.ObjectCreateRequest(metadata={"source_note": "uploaded through API"}),
        current_user=None,
    ))

    assert result["metadata"]["source_note"] == "uploaded through API"
    assert saved["object"].metadata["source_note"] == "uploaded through API"
