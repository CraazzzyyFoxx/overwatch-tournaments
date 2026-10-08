"""Unit tests for the public workspace profile fields (no DB required)."""

import pytest
from pydantic import ValidationError

from src import schemas

_LINKS = (
    ("discord_url", "https://discord.gg/abcdef"),
    ("discord_url", "https://discord.com/invite/abcdef"),
    ("twitch_url", "https://twitch.tv/anak"),
    ("boosty_url", "https://boosty.to/anak"),
)


@pytest.mark.parametrize(("field", "url"), _LINKS)
def test_update_accepts_matching_https_link(field, url):
    model = schemas.WorkspaceUpdate(**{field: url})
    assert getattr(model, field) == url


def test_update_accepts_www_prefixed_host():
    model = schemas.WorkspaceUpdate(twitch_url="https://www.twitch.tv/anak")
    assert model.twitch_url == "https://www.twitch.tv/anak"


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        # http, not https
        ("twitch_url", "http://twitch.tv/anak"),
        # right shape, wrong service
        ("twitch_url", "https://boosty.to/anak"),
        ("discord_url", "https://twitch.tv/anak"),
        ("boosty_url", "https://discord.gg/abcdef"),
        # lookalike host
        ("twitch_url", "https://twitch.tv.evil.com/anak"),
        ("discord_url", "https://notdiscord.gg/abcdef"),
        # not a URL at all
        ("boosty_url", "anak"),
    ],
)
def test_update_rejects_mismatched_link(field, bad):
    with pytest.raises(ValidationError):
        schemas.WorkspaceUpdate(**{field: bad})


@pytest.mark.parametrize("field", ("tagline", "about", "discord_url", "twitch_url", "boosty_url"))
def test_update_blank_clears_the_field(field):
    model = schemas.WorkspaceUpdate(**{field: "   "})
    assert getattr(model, field) is None
    assert model.model_dump(exclude_unset=True) == {field: None}


def test_update_trims_text():
    model = schemas.WorkspaceUpdate(tagline="  Weekly 5v5  ", about="  # Hi  ")
    assert model.tagline == "Weekly 5v5"
    assert model.about == "# Hi"


@pytest.mark.parametrize(("field", "length"), [("tagline", 121), ("about", 4001)])
def test_update_rejects_overlong_text(field, length):
    with pytest.raises(ValidationError):
        schemas.WorkspaceUpdate(**{field: "x" * length})


def test_read_exposes_profile_fields():
    fields = schemas.WorkspaceRead.model_fields
    for name in ("tagline", "about", "discord_url", "twitch_url", "boosty_url"):
        assert name in fields
