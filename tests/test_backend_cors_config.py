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


def test_normalizes_default_ports_and_deduplicates_equivalent_origins():
    assert parse_cors_origins(
        "https://example.com:443,https://EXAMPLE.com,"
        "http://localhost:80,http://LOCALHOST"
    ) == ["https://example.com", "http://localhost"]


def test_allows_cleartext_http_only_for_loopback_development():
    assert parse_cors_origins(
        "http://localhost:80,http://127.0.0.1,"
        "http://[::1]:8080,http://ui.dev.localhost:3000"
    ) == [
        "http://localhost",
        "http://127.0.0.1",
        "http://[::1]:8080",
        "http://ui.dev.localhost:3000",
    ]


def test_canonicalizes_ipv6_and_browser_compatible_idn_hosts():
    assert parse_cors_origins(
        "https://[2001:0db8:0:0:0:0:0:1]:443,"
        "https://BÜCHER.example,https://faß.de"
    ) == [
        "https://[2001:db8::1]",
        "https://xn--bcher-kva.example",
        "https://xn--fa-hia.de",
    ]


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
        "https://example.com?",
        "https://example.com#",
        "https://example.com:not-a-port",
        "https://example.com:",
        "https://%65xample.com",
        "https://bad_host.example",
        "https://-bad.example",
        "https://example..com",
        "https://[2001:db8::zz]",
        "ftp://example.com",
        "https://example .com",
        "https://example.com\\evil",
        "http://example.com",
        "http://api.example.com:8080",
    ],
)
def test_rejects_wildcard_and_malformed_or_insecure_origins(value):
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
