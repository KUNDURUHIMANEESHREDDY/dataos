"""Canonicalize Google AI Platform resource names without substring matching."""

from urllib.parse import urlsplit


def normalize_aiplatform_resource_name(full_name: str) -> str | None:
    """Return a canonical Vertex AI resource path or None for untrusted input.

    Bare resource paths are preserved. URL authorities are stripped only for
    the exact Google AI Platform host over HTTPS (including its canonical 443
    port); credentials, lookalike hosts, alternate schemes, query strings,
    fragments, and malformed ports are rejected.
    """
    if not isinstance(full_name, str) or not full_name:
        return None

    try:
        parsed = urlsplit(full_name)
        port = parsed.port
    except ValueError:
        return None

    if parsed.netloc:
        if (
            parsed.scheme not in ("", "https")
            or parsed.hostname != "aiplatform.googleapis.com"
            or parsed.username is not None
            or parsed.password is not None
            or port not in (None, 443)
            or parsed.query
            or parsed.fragment
        ):
            return None
        resource_name = parsed.path.lstrip("/")
        return resource_name or None

    if parsed.scheme or full_name.startswith("//"):
        return None
    return full_name
