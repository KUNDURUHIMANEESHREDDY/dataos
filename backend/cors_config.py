"""Strict CORS origin configuration for the DataOS API."""

from urllib.parse import urlsplit

DEFAULT_DEV_ORIGINS = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
)


def parse_cors_origins(raw: str | None) -> list[str]:
    """Parse a comma-separated CORS allowlist without accepting wildcards.

    None selects explicit local frontend origins for development. An empty
    string disables cross-origin access. Invalid configuration fails at startup
    rather than silently widening the browser trust boundary.
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

        parsed = urlsplit(candidate)
        try:
            # Accessing .port validates that a supplied port is numeric and in range.
            _ = parsed.port
        except ValueError as exc:
            raise ValueError(f"Invalid CORS origin: {candidate!r}") from exc

        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                f"Invalid CORS origin {candidate!r}; provide only scheme and host, with an optional port"
            )

        origin = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
        if origin not in origins:
            origins.append(origin)

    return origins
