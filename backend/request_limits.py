"""Bound incoming ASGI request bodies before FastAPI parses them."""

import os

from starlette.responses import JSONResponse

DEFAULT_MAX_REQUEST_BODY_BYTES = 50 * 1024 * 1024
MIN_MAX_REQUEST_BODY_BYTES = 1024
MAX_MAX_REQUEST_BODY_BYTES = 256 * 1024 * 1024


def configured_request_body_limit() -> int:
    """Read a bounded request-body limit from the environment.

    The default is 50 MiB. Deployments may choose 1 KiB through 256 MiB;
    invalid values fail startup rather than silently disabling the limit.
    """
    raw = os.getenv("DATAOS_MAX_REQUEST_BODY_BYTES", str(DEFAULT_MAX_REQUEST_BODY_BYTES))
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("DATAOS_MAX_REQUEST_BODY_BYTES must be an integer") from exc
    if not MIN_MAX_REQUEST_BODY_BYTES <= value <= MAX_MAX_REQUEST_BODY_BYTES:
        raise RuntimeError(
            "DATAOS_MAX_REQUEST_BODY_BYTES must be between "
            f"{MIN_MAX_REQUEST_BODY_BYTES} and {MAX_MAX_REQUEST_BODY_BYTES}"
        )
    return value


class _RequestBodyTooLarge(Exception):
    """Raised when streamed request bytes exceed the configured limit."""


class RequestBodyLimitMiddleware:
    """Enforce request size using both Content-Length and streamed byte counts."""

    def __init__(self, app, max_body_bytes: int = DEFAULT_MAX_REQUEST_BODY_BYTES):
        if not isinstance(max_body_bytes, int) or max_body_bytes < 1:
            raise ValueError("max_body_bytes must be a positive integer")
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def _reject(self, scope, receive, send, status_code: int, detail: str):
        headers = {"Connection": "close"} if scope.get("http_version") in {"1.0", "1.1"} else {}
        response = JSONResponse(
            status_code=status_code,
            content={"detail": detail},
            headers=headers,
        )
        await response(scope, receive, send)

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        length_headers = [
            value.strip()
            for key, value in scope.get("headers", [])
            if key.lower() == b"content-length"
        ]
        # Reject every duplicate field, even identical values. Different HTTP
        # components may normalize duplicates differently, creating request-
        # smuggling ambiguity before this middleware sees the ASGI scope.
        if len(length_headers) > 1:
            await self._reject(scope, receive, send, 400, "Invalid Content-Length")
            return
        if length_headers:
            raw_length = length_headers[0]
            # HTTP Content-Length is one or more ASCII decimal digits. Python's
            # int() also accepts forms such as +10, 1_0, and Unicode digits.
            if not raw_length.isascii() or not raw_length.isdigit():
                await self._reject(scope, receive, send, 400, "Invalid Content-Length")
                return
            # Strip leading zeroes before integer conversion. Apart from being
            # unnecessary work, converting an attacker-controlled thousands-digit
            # value can raise ValueError on Python builds with an integer-string
            # conversion limit instead of returning a controlled HTTP response.
            normalized_length = raw_length.lstrip(b"0") or b"0"
            max_length_digits = len(str(self.max_body_bytes))
            if len(normalized_length) > max_length_digits:
                await self._reject(scope, receive, send, 413, "Request body too large")
                return
            declared_length = int(normalized_length)
            if declared_length > self.max_body_bytes:
                await self._reject(scope, receive, send, 413, "Request body too large")
                return

        received_bytes = 0
        response_started = False

        async def limited_receive():
            nonlocal received_bytes
            message = await receive()
            if message.get("type") == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self.max_body_bytes:
                    raise _RequestBodyTooLarge
            return message

        async def tracked_send(message):
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except _RequestBodyTooLarge:
            # A response cannot be replaced after headers have been sent.
            if response_started:
                raise
            await self._reject(scope, receive, send, 413, "Request body too large")
