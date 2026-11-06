"""Canonicalize Google AI Platform resource names without substring matching."""

from urllib.parse import urlsplit


def normalize_aiplatform_resource_name(full_name: str) -> str:
    """Strip only an exact, trusted AI Platform authority from a resource URL.

    Bare resource paths are returned unchanged. URL-like values with lookalike
    hosts, credentials, ports, query strings, or fragments are never partially
    stripped.
    """
    if not isinstance(full_name, str) or not full_name:
        return full_name

    try:
        parsed = urlsplit(full_name)
        port = parsed.port
    except ValueError:
        return full_name

    if parsed.scheme not in ("", "https"):
        return full_name
    if parsed.netloc.lower() != "aiplatform.googleapis.com":
        return full_name
    if parsed.username is not None or parsed.password is not None or port is not None:
        return full_name
    if parsed.query or parsed.fragment:
        return full_name

    resource_path = parsed.path.lstrip("/")
    return resource_path or full_name
