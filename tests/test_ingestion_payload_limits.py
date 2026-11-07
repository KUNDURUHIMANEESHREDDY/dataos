import asyncio
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend import app as api


def run(coro):
    return asyncio.run(coro)


def request_from_body(body: bytes, content_type: str) -> Request:
    headers = [
        (b"content-type", content_type.encode("ascii")),
        (b"content-length", str(len(body)).encode("ascii")),
    ]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/ingest/universal",
        "raw_path": b"/api/ingest/universal",
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "server": ("testserver", 80),
        "client": ("testclient", 12345),
    }
    delivered = False

    async def receive():
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


def multipart_request(content: str, *, filename: str = "large.txt", discover_relations: str = "true") -> Request:
    boundary = "dataos-ingestion-test-boundary"
    fields = (
        ("filename", filename),
        ("content", content),
        ("discover_relations", discover_relations),
    )
    chunks = []
    for name, value in fields:
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii"),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    body = b"".join(chunks)
    return request_from_body(body, f"multipart/form-data; boundary={boundary}")


def urlencoded_request(fields: list[tuple[str, str]]) -> Request:
    body = urlencode(fields).encode("ascii")
    return request_from_body(body, "application/x-www-form-urlencoded")


def test_universal_ingestion_rejects_content_over_five_mib_through_multipart_parser(monkeypatch):
    called = []

    def ingest(*args, **kwargs):
        called.append((args, kwargs))
        return {"status": "ingested"}

    monkeypatch.setattr(api, "dataos", SimpleNamespace(ingest=ingest))
    request = multipart_request("a" * (api.MAX_INGEST_CONTENT_BYTES + 1))

    with pytest.raises(HTTPException) as exc:
        run(api.universal_ingest_api(request, current_user=None))

    assert exc.value.status_code == 413
    assert exc.value.detail == "Ingestion file exceeds the 5 MiB content limit."
    assert called == []


def test_universal_ingestion_accepts_exactly_five_mib_through_multipart_parser(monkeypatch):
    calls = []

    def ingest(*args, **kwargs):
        calls.append((args, kwargs))
        return {"status": "ingested"}

    monkeypatch.setattr(api, "dataos", SimpleNamespace(ingest=ingest))
    content = "a" * api.MAX_INGEST_CONTENT_BYTES
    request = multipart_request(content, filename="limit.txt", discover_relations="false")

    result = run(api.universal_ingest_api(request, current_user=None))

    assert result == {"status": "ingested"}
    assert len(calls) == 1
    assert calls[0][0][0] == content
    assert calls[0][1]["filename"] == "limit.txt"
    assert calls[0][1]["discover_relations"] is False


def test_universal_ingestion_rejects_urlencoded_forms_over_field_limit(monkeypatch):
    monkeypatch.setattr(
        api,
        "dataos",
        SimpleNamespace(ingest=lambda *args, **kwargs: pytest.fail("invalid form must not ingest")),
    )
    request = urlencoded_request([
        ("filename", "safe.txt"),
        ("content", "small"),
        ("discover_relations", "false"),
        ("unexpected", "extra-field"),
    ])

    with pytest.raises(HTTPException) as exc:
        run(api.universal_ingest_api(request, current_user=None))

    assert exc.value.status_code == 400
    assert exc.value.detail == "Invalid ingestion form."


def test_universal_ingestion_rejects_invalid_boolean_form_value(monkeypatch):
    monkeypatch.setattr(
        api,
        "dataos",
        SimpleNamespace(ingest=lambda *args, **kwargs: pytest.fail("invalid form must not ingest")),
    )
    request = multipart_request("small", discover_relations="sometimes")

    with pytest.raises(HTTPException) as exc:
        run(api.universal_ingest_api(request, current_user=None))

    assert exc.value.status_code == 422
