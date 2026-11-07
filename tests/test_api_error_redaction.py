"""Ensure API error responses never expose exception internals to clients."""

import asyncio
import importlib

import pytest
from fastapi import HTTPException

api = importlib.import_module("backend.app")


def run(coro):
    return asyncio.run(coro)


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
    def fail_ingestion(*args, **kwargs):
        raise ValueError("parser failed while opening /srv/private/customer-records.pdf")

    monkeypatch.setattr(api.dataos, "ingest", fail_ingestion)
    route = getattr(api, handler)

    with pytest.raises(HTTPException) as exc:
        run(route(filename="customer-file", content="synthetic content"))

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
        "Workflow definition is invalid or exceeds the supported execution limits."
    )
    assert "private-customer-id" not in exc.value.detail
    assert "/srv/private" not in exc.value.detail


def test_invalid_sharing_tokens_return_a_stable_error(monkeypatch):
    monkeypatch.setenv("DATAOS_SHARING_TOKEN_SECRET", "synthetic-secret-" + "x" * 40)

    def fail_verification(token):
        raise ValueError("signature mismatch for token stored in /srv/private/keys")

    monkeypatch.setattr(api.dataos.tokens, "verify_and_decode_token", fail_verification)
    request = api.VerifySharingTokenRequest(token="synthetic-invalid-token")

    with pytest.raises(HTTPException) as exc:
        run(api.verify_sharing_token_api(request))

    assert exc.value.status_code == 403
    assert exc.value.detail == "Sharing token is invalid or expired."
    assert "/srv/private" not in exc.value.detail
    assert "signature mismatch" not in exc.value.detail
