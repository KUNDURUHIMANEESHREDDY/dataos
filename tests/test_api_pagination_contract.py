"""Contract tests for bounded object-list pagination."""

from backend.app import app


def test_object_list_pagination_is_bounded_in_openapi():
    """Keep the public API contract from allowing unbounded list queries."""
    parameters = app.openapi()["paths"]["/api/objects/"]["get"]["parameters"]
    by_name = {parameter["name"]: parameter for parameter in parameters}

    assert by_name["limit"]["in"] == "query"
    assert by_name["limit"]["schema"]["minimum"] == 1
    assert by_name["limit"]["schema"]["maximum"] == 500
    assert by_name["offset"]["in"] == "query"
    assert by_name["offset"]["schema"]["minimum"] == 0
    assert by_name["offset"]["schema"]["maximum"] == 1_000_000

    relationship_parameters = app.openapi()["paths"]["/api/relationships/"]["get"]["parameters"]
    relationship_by_name = {parameter["name"]: parameter for parameter in relationship_parameters}
    assert relationship_by_name["min_confidence"]["schema"]["minimum"] == 0.0
    assert relationship_by_name["min_confidence"]["schema"]["maximum"] == 1.0
    assert relationship_by_name["limit"]["schema"]["minimum"] == 1
    assert relationship_by_name["limit"]["schema"]["maximum"] == 1000
    assert relationship_by_name["offset"]["schema"]["minimum"] == 0
    assert relationship_by_name["offset"]["schema"]["maximum"] == 1_000_000
