import pytest

from backend.cors_config import (
    DEFAULT_DEV_ORIGINS,
    cors_middleware_options,
    parse_cors_origins,
)


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
        "https://example .com",
        "https://example.com\\evil",
        "http://example.com",
        "http://api.example.com:8080",
    ],
)
def test_rejects_wildcard_and_malformed_origins(value):
    with pytest.raises(ValueError):
        parse_cors_origins(value)



def test_middleware_options_disable_credentials_and_limit_methods_and_headers():
    options = cors_middleware_options(None)

    assert options["allow_origins"] == list(DEFAULT_DEV_ORIGINS)
    assert options["allow_credentials"] is False
    assert options["allow_methods"] == ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    assert options["allow_headers"] == ["Authorization", "Content-Type"]


def test_middleware_options_use_configured_origins():
    options = cors_middleware_options("https://console.example.com")
    assert options["allow_origins"] == ["https://console.example.com"]
