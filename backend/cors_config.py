"""Strict CORS origin configuration for the DataOS API."""

import ipaddress
import re
from urllib.parse import urlsplit

import idna

DEFAULT_DEV_ORIGINS = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
)

_DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")


def _is_loopback_host(hostname: str) -> bool:
    """Return whether a hostname is a loopback address or localhost name."""
    normalized = hostname.rstrip(".").lower()
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return normalized == "localhost" or normalized.endswith(".localhost")


def _canonical_host(hostname: str) -> str:
    """Return the URL-serialized, lower-case host or reject ambiguous forms."""
    if not hostname or "%" in hostname:
        raise ValueError("CORS origin host must not be empty or percent-encoded")

    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        if ":" in hostname or all(char in "0123456789." for char in hostname):
            raise ValueError(f"Invalid IP address in CORS origin: {hostname!r}")

        try:
            # UTS #46 non-transitional processing matches modern browser URL
            # host serialization (not Python's legacy IDNA 2003 codec).
            ascii_host = idna.encode(
                hostname, uts46=True, std3_rules=True
            ).decode("ascii").lower()
        except (idna.IDNAError, UnicodeError) as exc:
            raise ValueError(f"Invalid hostname in CORS origin: {hostname!r}") from exc

        # A trailing dot is valid DNS syntax and is preserved for exact origin
        # matching, but empty/interior labels and malformed labels are rejected.
        labels_host = ascii_host[:-1] if ascii_host.endswith(".") else ascii_host
        labels = labels_host.split(".")
        if (
            not labels_host
            or len(ascii_host) > 254
            or any(not _DNS_LABEL.fullmatch(label) for label in labels)
        ):
            raise ValueError(f"Invalid hostname in CORS origin: {hostname!r}")
        return ascii_host

    if isinstance(address, ipaddress.IPv6Address):
        return f"[{address.compressed}]"
    return str(address)


def parse_cors_origins(raw: str | None) -> list[str]:
    """Parse a comma-separated CORS allowlist without accepting wildcards.

    None selects explicit local frontend origins for development. An empty
    string disables cross-origin access. Invalid configuration fails at startup
    rather than silently widening the browser trust boundary. Hostnames and
    default ports are canonicalized so equivalent origins deduplicate and
    match the browser's serialized Origin header. Cleartext HTTP is permitted
    only for loopback development origins.
    """
    if raw is None:
        candidates = list(DEFAULT_DEV_ORIGINS)
    else:
        candidates = [item.strip() for item in raw.split(",") if item.strip()]

    origins: list[str] = []
    for candidate in candidates:
        if candidate == "*":
            raise ValueError(
                "DATAOS_CORS_ORIGINS must list explicit origins; wildcard origins are forbidden"
            )

        if any(char.isspace() for char in candidate) or "\\" in candidate:
            raise ValueError(f"Invalid CORS origin: {candidate!r}")

        try:
            parsed = urlsplit(candidate)
            port = parsed.port
            hostname = parsed.hostname
        except ValueError as exc:
            raise ValueError(f"Invalid CORS origin: {candidate!r}") from exc

        scheme = parsed.scheme.lower()
        if (
            scheme not in {"http", "https"}
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or "?" in candidate
            or "#" in candidate
            or parsed.netloc.endswith(":")
        ):
            raise ValueError(
                f"Invalid CORS origin {candidate!r}; provide only scheme and host, with an optional port"
            )

        if scheme == "http" and not _is_loopback_host(hostname):
            raise ValueError(
                f"Remote CORS origin {candidate!r} must use HTTPS; "
                "HTTP is allowed only for loopback development"
            )

        host = _canonical_host(hostname)
        if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
            port = None
        port_suffix = f":{port}" if port is not None else ""
        origin = f"{scheme}://{host}{port_suffix}"
        if origin not in origins:
            origins.append(origin)

    return origins


def cors_middleware_options(raw: str | None) -> dict[str, object]:
    """Return least-privilege options for Starlette's CORS middleware."""
    return {
        "allow_origins": parse_cors_origins(raw),
        "allow_credentials": False,
        "allow_methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        "allow_headers": ["Authorization", "Content-Type"],
    }
