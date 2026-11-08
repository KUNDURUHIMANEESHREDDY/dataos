"""Ensure API error responses never expose exception internals to clients."""

import asyncio
import importlib
import json
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from fastapi import HTTPException

api = importlib.import_module("backend.app")


def run(coro):
    return asyncio.run(coro)


def _disable_api_auth(monkeypatch):
    for name in ("DATAOS_ENV", "APP_ENV", "ENVIRONMENT", "DATAOS_JWT_SECRET"):
        monkeypatch.delenv(name, raising=False)


def _http_request(method, path, *, json_body=None, form_body=None):
    """Exercise the FastAPI ASGI boundary and return the serialized HTTP response."""
    if json_body is not None and form_body is not None:
        raise ValueError("Choose either a JSON or form body")
    if json_body is not None:
        body = json.dumps(json_body).encode("utf-8")
        content_type = b"application/json"
    elif form_body is not None:
        body = urlencode(form_body).encode("ascii")
        content_type = b"application/x-www-form-urlencoded"
    else:
        body = b""
        content_type = b"application/octet-stream"

    headers = [
        (b"host", b"testserver"),
        (b"content-type", content_type),
        (b"content-length", str(len(body)).encode("ascii")),
    ]
    messages = []
    request_sent = False
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("testclient", 12345),
        "server": ("testserver", 80),
        "state": {},
    }

    async def receive():
        nonlocal request_sent
        if request_sent:
            return {"type": "http.disconnect"}
        request_sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    async def dispatch():
        await api.app(scope, receive, send)

    asyncio.run(dispatch())
    response_start = next(message for message in messages if message["type"] == "http.response.start")
    response_body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    return response_start["status"], json.loads(response_body.decode("utf-8"))


def test_registration_errors_do_not_disclose_database_details(monkeypatch):
    monkeypatch.setattr(api, "jwt_configured", lambda: True)

    class BrokenStore:
        def register(self, *args):
            raise ValueError("UNIQUE constraint failed at /srv/private/dataos.db")

    monkeypatch.setattr(api, "get_user_store", lambda: BrokenStore())
    request = api.RegisterRequest(
        username="alice",
        email="alice@example.test",
        password="correct-horse-battery",
    )

    with pytest.raises(HTTPException) as exc:
        run(api.register_user(request))

    assert exc.value.status_code == 400
    assert exc.value.detail == (
        "Registration could not be completed. Check the supplied fields or try a different username/email."
    )
    assert "/srv/private" not in exc.value.detail
    assert "UNIQUE constraint" not in exc.value.detail


@pytest.mark.parametrize(
    ("handler", "expected"),
    [
        (
            "ingest_notebook_api",
            "Notebook ingestion failed. Check the format and supported content limits.",
        ),
        (
            "extract_rich_document_api",
            "Document ingestion failed. Check the format and supported content limits.",
        ),
    ],
)
def test_ingestion_errors_do_not_disclose_paths_or_parser_details(monkeypatch, handler, expected):
    _disable_api_auth(monkeypatch)

    def fail_ingestion(*args, **kwargs):
        raise ValueError("parser failed while opening /srv/private/customer-records.pdf")

    monkeypatch.setattr(api.dataos, "ingest", fail_ingestion)
    route = getattr(api, handler)

    with pytest.raises(HTTPException) as exc:
        run(route(filename="customer-file", content="synthetic content", current_user=None))

    assert exc.value.status_code == 422
    assert exc.value.detail == expected
    assert "/srv/private" not in exc.value.detail
    assert "customer-records" not in exc.value.detail


def test_conflict_resolution_errors_do_not_disclose_storage_details(monkeypatch):
    def fail_resolution(**kwargs):
        raise ValueError("object obj-secret-123 is locked by /srv/private/tenant.db")

    monkeypatch.setattr(api.dataos.sync, "resolve_conflict", fail_resolution)
    request = api.ConflictResolutionRequest(
        conflict_object_id="synthetic-object",
        strategy="last_write_wins",
    )

    with pytest.raises(HTTPException) as exc:
        run(api.resolve_conflict_api(request))

    assert exc.value.status_code == 400
    assert exc.value.detail == "Conflict resolution request could not be completed."
    assert "obj-secret-123" not in exc.value.detail
    assert "/srv/private" not in exc.value.detail


def test_workflow_validation_errors_do_not_echo_untrusted_details(monkeypatch):
    def fail_workflow(*args, **kwargs):
        raise api.WorkflowRequestError("node private-customer-id references internal /srv/private path")

    monkeypatch.setattr(api, "execute_safe_workflow", fail_workflow)
    request = api.WorkflowExecutionRequest(
        definition={"name": "safe-test", "nodes": {"step-1": {"action_type": "noop"}}},
        context={},
    )

    with pytest.raises(HTTPException) as exc:
        run(api.execute_workflow(request))

    assert exc.value.status_code == 422
    assert exc.value.detail == (
        "Workflow definition must contain valid nodes and stay within the supported execution limits."
    )
    assert "private-customer-id" not in exc.value.detail
    assert "/srv/private" not in exc.value.detail


def test_invalid_sharing_tokens_return_a_stable_error(monkeypatch):
    monkeypatch.setenv("DATAOS_SHARING_TOKEN_SECRET", "synthetic-secret-" + "x" * 40)

    def fail_verification(token):
        raise ValueError("signature mismatch for token stored in /srv/private/keys")

    monkeypatch.setattr(
        api.dataos,
        "tokens",
        SimpleNamespace(verify_and_decode_token=fail_verification),
    )
    request = api.VerifySharingTokenRequest(token="synthetic-invalid-token")

    with pytest.raises(HTTPException) as exc:
        run(api.verify_sharing_token_api(request))

    assert exc.value.status_code == 403
    assert exc.value.detail == "Sharing token is invalid or expired."
    assert "/srv/private" not in exc.value.detail
    assert "signature mismatch" not in exc.value.detail


def test_registration_http_response_does_not_disclose_database_details(monkeypatch):
    _disable_api_auth(monkeypatch)
    monkeypatch.setattr(api, "jwt_configured", lambda: True)

    class BrokenStore:
        def register(self, *args):
            raise ValueError("UNIQUE constraint failed at /srv/private/dataos.db")

    monkeypatch.setattr(api, "get_user_store", lambda: BrokenStore())
    status, payload = _http_request(
        "POST",
        "/api/auth/register",
        json_body={
            "username": "alice",
            "email": "alice@example.test",
            "password": "correct-horse-battery",
        },
    )

    assert status == 400
    assert payload == {
        "detail": "Registration could not be completed. Check the supplied fields or try a different username/email."
    }
    assert "/srv/private" not in json.dumps(payload)
    assert "UNIQUE constraint" not in json.dumps(payload)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (
            "/api/notebooks/ingest",
            "Notebook ingestion failed. Check the format and supported content limits.",
        ),
        (
            "/api/documents/extract_rich",
            "Document ingestion failed. Check the format and supported content limits.",
        ),
    ],
)
def test_ingestion_http_responses_do_not_disclose_parser_paths(monkeypatch, path, expected):
    _disable_api_auth(monkeypatch)

    def fail_ingestion(*args, **kwargs):
        raise ValueError("parser failed while opening /srv/private/customer-records.pdf")

    monkeypatch.setattr(api.dataos, "ingest", fail_ingestion)
    status, payload = _http_request(
        "POST",
        path,
        form_body={"filename": "customer-file", "content": "synthetic content"},
    )

    assert status == 422
    assert payload == {"detail": expected}
    assert "/srv/private" not in json.dumps(payload)
    assert "customer-records" not in json.dumps(payload)


def test_conflict_resolution_http_response_does_not_disclose_storage_details(monkeypatch):
    _disable_api_auth(monkeypatch)

    def fail_resolution(**kwargs):
        raise ValueError("object obj-secret-123 is locked by /srv/private/tenant.db")

    monkeypatch.setattr(api.dataos.sync, "resolve_conflict", fail_resolution)
    status, payload = _http_request(
        "POST",
        "/api/sync/resolve_conflict",
        json_body={
            "conflict_object_id": "synthetic-object",
            "strategy": "last_write_wins",
        },
    )

    assert status == 400
    assert payload == {"detail": "Conflict resolution request could not be completed."}
    assert "obj-secret-123" not in json.dumps(payload)
    assert "/srv/private" not in json.dumps(payload)


def test_workflow_http_response_does_not_echo_untrusted_validation_details(monkeypatch):
    _disable_api_auth(monkeypatch)

    def fail_workflow(*args, **kwargs):
        raise api.WorkflowRequestError("node private-customer-id references internal /srv/private path")

    monkeypatch.setattr(api, "execute_safe_workflow", fail_workflow)
    status, payload = _http_request(
        "POST",
        "/api/workflows/execute",
        json_body={
            "definition": {"name": "safe-test", "nodes": {"step-1": {"action_type": "noop"}}},
            "context": {},
        },
    )

    assert status == 422
    assert payload == {
        "detail": "Workflow definition must contain valid nodes and stay within the supported execution limits."
    }
    assert "private-customer-id" not in json.dumps(payload)
    assert "/srv/private" not in json.dumps(payload)


def test_sharing_token_http_response_does_not_disclose_verification_details(monkeypatch):
    _disable_api_auth(monkeypatch)
    monkeypatch.setenv("DATAOS_SHARING_TOKEN_SECRET", "synthetic-secret-" + "x" * 40)

    def fail_verification(token):
        raise ValueError("signature mismatch for token stored in /srv/private/keys")

    monkeypatch.setattr(
        api.dataos,
        "tokens",
        SimpleNamespace(verify_and_decode_token=fail_verification),
    )
    status, payload = _http_request(
        "POST",
        "/api/sharing/verify_token",
        json_body={"token": "synthetic-invalid-token"},
    )

    assert status == 403
    assert payload == {"detail": "Sharing token is invalid or expired."}
    assert "/srv/private" not in json.dumps(payload)
    assert "signature mismatch" not in json.dumps(payload)
