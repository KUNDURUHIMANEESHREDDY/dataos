"""Regression tests for non-ASCII production bearer tokens."""

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend.app import require_production_api_token


def _api_request() -> Request:
    path = "/api/objects/"
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "headers": [],
            "client": ("testclient", 12345),
            "server": ("testserver", 80),
        }
    )


def test_non_ascii_bearer_token_is_compared_without_server_error(monkeypatch):
    expected = "é" * 32
    monkeypatch.setenv("DATAOS_ENV", "production")
    monkeypatch.setenv("DATAOS_API_TOKEN", expected)

    # A valid UTF-8 token must authenticate without hmac.compare_digest(str)
    # raising TypeError for non-ASCII text.
    require_production_api_token(_api_request(), authorization=f"Bearer {expected}")

    # A different non-ASCII token must be rejected as an ordinary 401, not 500.
    with pytest.raises(HTTPException) as exc:
        require_production_api_token(_api_request(), authorization=f"Bearer {'ñ' * 32}")
    assert exc.value.status_code == 401
