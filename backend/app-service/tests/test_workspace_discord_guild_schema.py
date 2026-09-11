"""Unit tests for the workspace Discord-guild schemas (no DB required).

``discord_guild_id`` moved off ``WorkspaceUpdate`` entirely as part of the
workspace self-service design
(``docs/superpowers/specs/2026-08-26-workspace-self-service-design.md`` §4.1):
the free-text ``PATCH`` path let anyone with ``workspace.update`` claim any
guild with only a format check, no ownership proof. Binding now only happens
through ``WorkspaceDiscordGuildVerify`` /
``rpc.app.workspaces.discord_guild_verify``.
"""

import pytest
from pydantic import ValidationError

from src import schemas


def test_update_no_longer_accepts_discord_guild_id():
    assert "discord_guild_id" not in schemas.WorkspaceUpdate.model_fields


def test_read_carries_the_field_defaulting_to_none():
    # The same pin the other deliberately-exposed WorkspaceRead fields carry (see
    # test_workspace_timezone_schema.py:30 and test_workspace_branding_schema.py:98).
    # It looks tautological, but exposing this field on a PUBLIC read model is a
    # deliberate design decision, and nothing else in the suite fails if it
    # silently disappears -- the admin page would just render a blank guild.
    assert "discord_guild_id" in schemas.WorkspaceRead.model_fields
    assert schemas.WorkspaceRead.model_fields["discord_guild_id"].default is None


def test_read_exposes_verified_at_but_not_verified_by():
    # verified_at is public for the same reason custom_domain_verified_at is
    # (an admin screen needs to render it); verified_by_auth_user_id is
    # deliberately absent -- unlike a guild id or a DNS token, an arbitrary
    # internal auth_user_id is not something this design chooses to publish.
    assert "discord_guild_verified_at" in schemas.WorkspaceRead.model_fields
    assert schemas.WorkspaceRead.model_fields["discord_guild_verified_at"].default is None
    assert "discord_guild_verified_by_auth_user_id" not in schemas.WorkspaceRead.model_fields


def test_verify_body_accepts_a_snowflake():
    model = schemas.WorkspaceDiscordGuildVerify(guild_id="1234567890123456789")
    assert model.guild_id == "1234567890123456789"


@pytest.mark.parametrize("bad", ["notanumber", "12345", "1" * 20, "1" * 21, "123456789012345678a", "12 34"])
def test_verify_body_rejects_anything_that_is_not_a_snowflake(bad):
    with pytest.raises(ValidationError):
        schemas.WorkspaceDiscordGuildVerify(guild_id=bad)


@pytest.mark.parametrize("ok", ["1" * 17, "1" * 18, "1" * 19])
def test_verify_body_accepts_every_length_a_bigint_could_hold(ok):
    assert schemas.WorkspaceDiscordGuildVerify(guild_id=ok).guild_id == ok


def test_verify_body_requires_guild_id():
    with pytest.raises(ValidationError):
        schemas.WorkspaceDiscordGuildVerify()


def test_guild_option_carries_an_optional_icon():
    model = schemas.WorkspaceDiscordGuildOption(
        guild_id="123456789012345678",
        name="G",
        owner=True,
        can_manage=True,
    )
    assert model.icon_url is None
    pictured = schemas.WorkspaceDiscordGuildOption(
        guild_id="123456789012345678",
        name="G",
        icon_url="https://cdn.discordapp.com/icons/1/abc.png",
        owner=True,
        can_manage=True,
    )
    assert pictured.icon_url.endswith("abc.png")
