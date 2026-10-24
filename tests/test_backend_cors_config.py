import pytest

from backend.cors_config import DEFAULT_DEV_ORIGINS, parse_cors_origins


def test_defaults_to_explicit_local_frontend_origins():
    assert parse_cors_origins(None) == list(DEFAULT_DEV_ORIGINS)


def test_empty_configuration_disables_cross_origin_access():
    assert parse_cors_origins("") == []


def test_normalizes_trailing_slash_and_deduplicates_origins():
    assert parse_cors_origins(
        " https://Example.com/ ,https://example.com,http://localhost:3000 "
    ) == ["https://example.com", "http://localhost:3000"]


@pytest.mark.parametrize(
    "value",
    [
        "*",
        "https://example.com,*",
        "file:///tmp",
        "https://example.com/path",
        "https://user:pass@example.com",
        "https://example.com?token=x",
        "https://example.com#fragment",
        "https://example.com:not-a-port",
        "ftp://example.com",
    ],
)
def test_rejects_wildcard_and_malformed_origins(value):
    with pytest.raises(ValueError):
        parse_cors_origins(value)
