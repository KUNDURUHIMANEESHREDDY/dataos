"""HTTP contract tests for bounded provenance lineage parameters."""

import asyncio
import importlib
from types import SimpleNamespace

api = importlib.import_module("backend.app")


def test_lineage_route_publishes_bounded_query_contract():
    parameters = api.app.openapi()["paths"]["/api/provenance/lineage/{object_id}"]["get"]["parameters"]
    by_name = {parameter["name"]: parameter for parameter in parameters}

    assert by_name["direction"]["schema"]["enum"] == ["upstream", "downstream"]
    assert by_name["direction"]["schema"]["default"] == "upstream"
    assert by_name["max_depth"]["schema"]["minimum"] == 1
    assert by_name["max_depth"]["schema"]["maximum"] == 10
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

    upstream = asyncio.run(api.get_lineage("root", "upstream", 4))
    downstream = asyncio.run(api.get_lineage("root", "downstream", 2))

    assert upstream == {"direction": "upstream", "object_id": "root", "max_depth": 4}
    assert downstream == {"direction": "downstream", "object_id": "root", "max_depth": 2}
    assert calls == [("upstream", "root", 4), ("downstream", "root", 2)]
