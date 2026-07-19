import pytest

from shared.tenancy.hostnames import (
    PLATFORM_ZONE,
    is_platform_host,
    normalize_custom_domain,
    subdomain_from_host,
    validate_subdomain_label,
)


def test_platform_zone():
    assert PLATFORM_ZONE == "owt.craazzzyyfoxx.me"


@pytest.mark.parametrize("label", ["team-a", "owcs", "a", "x1y2"])
def test_validate_accepts_valid_labels(label):
    assert validate_subdomain_label(label.upper()) == label  # normalizes case


@pytest.mark.parametrize("bad", ["team_a", "-team", "te am", "", "a" * 64, "café"])
def test_validate_rejects_malformed(bad):
    with pytest.raises(ValueError):
        validate_subdomain_label(bad)


@pytest.mark.parametrize("reserved", ["www", "api", "auth", "admin", "ws"])
def test_validate_rejects_reserved(reserved):
    with pytest.raises(ValueError):
        validate_subdomain_label(reserved)


def test_subdomain_from_host_extracts_label():
    assert subdomain_from_host("team-a.owt.craazzzyyfoxx.me") == "team-a"
    assert subdomain_from_host("TEAM-A.owt.craazzzyyfoxx.me") == "team-a"


def test_subdomain_from_host_ignores_apex_www_and_foreign():
    assert subdomain_from_host("owt.craazzzyyfoxx.me") is None
    assert subdomain_from_host("www.owt.craazzzyyfoxx.me") is None
    assert subdomain_from_host("a.b.owt.craazzzyyfoxx.me") is None  # multi-segment
    assert subdomain_from_host("evil.com") is None
    assert subdomain_from_host("team-a.owt.craazzzyyfoxx.me:443") == "team-a"  # port stripped


@pytest.mark.parametrize(
    "host",
    [
        "te$t.owt.craazzzyyfoxx.me",
        "-team.owt.craazzzyyfoxx.me",
        ("a" * 64) + ".owt.craazzzyyfoxx.me",
        "api.owt.craazzzyyfoxx.me",
        "admin.owt.craazzzyyfoxx.me",
    ],
)
def test_subdomain_from_host_rejects_invalid_or_reserved(host):
    assert subdomain_from_host(host) is None


@pytest.mark.parametrize(
    "raw,norm",
    [
        ("Tourney.Customer.com", "tourney.customer.com"),
        ("example.org.", "example.org"),
        ("Tourney.Customer.com:8443", "tourney.customer.com"),
        ("example.com.:8080", "example.com"),
    ],
)
def test_normalize_custom_domain_ok(raw, norm):
    assert normalize_custom_domain(raw) == norm


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "owt.craazzzyyfoxx.me",
        "team.owt.craazzzyyfoxx.me",
        "nodot",
        "has space.com",
        "example-.com",
        "customer.com-",
    ],
)
def test_normalize_custom_domain_rejects(bad):
    with pytest.raises(ValueError):
        normalize_custom_domain(bad)


def test_is_platform_host():
    assert is_platform_host("owt.craazzzyyfoxx.me")
    assert is_platform_host("team-a.owt.craazzzyyfoxx.me")
    assert not is_platform_host("tourney.customer.com")
    assert is_platform_host("owt.craazzzyyfoxx.me:443")
