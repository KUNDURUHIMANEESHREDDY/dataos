import asyncio

import pytest

from backend.request_limits import (
    DEFAULT_MAX_REQUEST_BODY_BYTES,
    RequestBodyLimitMiddleware,
    configured_request_body_limit,
)


def scope_for(headers=(), scope_type="http"):
    return {
        "type": scope_type,
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/test",
        "raw_path": b"/api/test",
        "query_string": b"",
        "headers": list(headers),
        "server": ("test", 80),
        "client": ("test", 1234),
    }


def request_messages(*chunks):
    messages = [
        {"type": "http.request", "body": body, "more_body": index < len(chunks) - 1}
        for index, body in enumerate(chunks)
    ]

    async def receive():
        if messages:
            return messages.pop(0)
        return {"type": "http.disconnect"}

    return receive


async def invoke(middleware, scope, receive):
    sent = []

    async def send(message):
        sent.append(message)

    await middleware(scope, receive, send)
    return sent


def run(coro):
    return asyncio.run(coro)


def response_status(messages):
    return next(message["status"] for message in messages if message["type"] == "http.response.start")


def response_body(messages):
    return b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )


def test_accepts_body_at_exact_limit():
    called = []

    async def app(scope, receive, send):
        called.append(True)
        while True:
            message = await receive()
            if message["type"] != "http.request" or not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = RequestBodyLimitMiddleware(app, max_body_bytes=3)
    sent = run(invoke(middleware, scope_for(), request_messages(b"abc")))

    assert response_status(sent) == 200
    assert called == [True]


def test_rejects_streamed_body_over_limit_without_leaking_exception():
    called = []

    async def app(scope, receive, send):
        called.append(True)
        while True:
            message = await receive()
            if message["type"] != "http.request" or not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = RequestBodyLimitMiddleware(app, max_body_bytes=3)
    sent = run(invoke(middleware, scope_for(), request_messages(b"ab", b"cd")))

    assert response_status(sent) == 413
    assert b"Request body too large" in response_body(sent)
    assert any(
        key.lower() == b"connection" and value.lower() == b"close"
        for key, value in next(m["headers"] for m in sent if m["type"] == "http.response.start")
    )
    assert called == [True]


def test_rejects_oversized_content_length_before_calling_app():
    called = []

    async def app(scope, receive, send):
        called.append(True)

    middleware = RequestBodyLimitMiddleware(app, max_body_bytes=3)
    sent = run(
        invoke(
            middleware,
            scope_for([(b"content-length", b"4")]),
            request_messages(b"data"),
        )
    )

    assert response_status(sent) == 413
    assert called == []


@pytest.mark.parametrize(
    "headers",
    [
        [(b"content-length", b"not-a-number")],
        [(b"content-length", b"-1")],
        [(b"content-length", b"+3")],
        [(b"content-length", b"1_0")],
        [(b"content-length", "٣".encode("utf-8"))],
        [(b"content-length", b"2"), (b"content-length", b"3")],
        [(b"content-length", b"3"), (b"content-length", b"3")],
    ],
)
def test_rejects_invalid_or_duplicate_content_length(headers):
    async def app(scope, receive, send):
        raise AssertionError("invalid or duplicate Content-Length must be rejected before the route")

    sent = run(
        invoke(
            RequestBodyLimitMiddleware(app, max_body_bytes=10),
            scope_for(headers),
            request_messages(b""),
        )
    )
    assert response_status(sent) == 400
    assert b"Invalid Content-Length" in response_body(sent)


def test_non_http_scopes_are_forwarded_unchanged():
    called = []

    async def app(scope, receive, send):
        called.append(scope["type"])

    scope = scope_for(scope_type="lifespan")
    run(invoke(RequestBodyLimitMiddleware(app, max_body_bytes=3), scope, request_messages()))
    assert called == ["lifespan"]


def test_request_body_limit_configuration_is_bounded(monkeypatch):
    monkeypatch.delenv("DATAOS_MAX_REQUEST_BODY_BYTES", raising=False)
    assert configured_request_body_limit() == DEFAULT_MAX_REQUEST_BODY_BYTES

    monkeypatch.setenv("DATAOS_MAX_REQUEST_BODY_BYTES", "2048")
    assert configured_request_body_limit() == 2048

    monkeypatch.setenv("DATAOS_MAX_REQUEST_BODY_BYTES", "unlimited")
    with pytest.raises(RuntimeError, match="must be an integer"):
        configured_request_body_limit()

    monkeypatch.setenv("DATAOS_MAX_REQUEST_BODY_BYTES", "999999999")
    with pytest.raises(RuntimeError, match="between"):
        configured_request_body_limit()
