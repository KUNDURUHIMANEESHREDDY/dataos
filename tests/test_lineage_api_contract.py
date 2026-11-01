"""HTTP contract tests for bounded provenance lineage parameters."""

from fastapi.testclient import TestClient

from backend.app import app


def test_lineage_route_publishes_bounded_query_contract():
    parameters = app.openapi()["paths"]["/api/provenance/lineage/{object_id}"]["get"]["parameters"]
    by_name = {parameter["name"]: parameter for parameter in parameters}

    assert by_name["direction"]["schema"]["enum"] == ["upstream", "downstream"]
    assert by_name["direction"]["schema"]["default"] == "upstream"
    assert by_name["max_depth"]["schema"]["minimum"] == 1
    assert by_name["max_depth"]["schema"]["maximum"] == 10
    assert by_name["max_depth"]["schema"]["default"] == 10


def test_lineage_route_rejects_invalid_direction_and_unbounded_depth(monkeypatch):
    for marker in ("DATAOS_ENV", "APP_ENV", "ENVIRONMENT"):
        monkeypatch.delenv(marker, raising=False)

    client = TestClient(app)
    invalid_queries = (
        "direction=sideways",
        "max_depth=0",
        "max_depth=11",
        "max_depth=999999",
    )
    for query in invalid_queries:
        response = client.get(f"/api/provenance/lineage/root?{query}")
        assert response.status_code == 422, query
