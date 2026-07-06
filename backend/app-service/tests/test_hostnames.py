import pytest

from shared.tenancy.hostnames import (
    PLATFORM_ZONE,
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
