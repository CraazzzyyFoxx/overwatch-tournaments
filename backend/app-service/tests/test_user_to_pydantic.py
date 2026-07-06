"""Unit tests for user_flows.to_pydantic (unified social_accounts, no DB)."""

import asyncio

from shared.core.social import SocialProvider
from shared.models.identity.social import SocialAccountVisibility
from src import models
from src.services.user import flows


def _acc(id_: int, provider: str, username: str, *, is_primary: bool = False, is_verified: bool = False, url=None):
    return models.SocialAccount(
        id=id_,
        user_id=7,
        provider=provider,
        username=username,
        url=url,
        is_verified=is_verified,
        is_primary=is_primary,
    )


def _user_with(accounts):
    user = models.User(id=7, name="Tester")
    user.social_accounts = accounts
    return user


def test_to_pydantic_returns_unified_social_accounts():
    accounts = [
        _acc(1, SocialProvider.BATTLENET, "Player#1234", is_primary=True, is_verified=True),
        _acc(2, SocialProvider.DISCORD, "coolguy"),
        _acc(3, SocialProvider.TWITCH, "streamer"),
        _acc(4, SocialProvider.BOOSTY, "patron", url="https://boosty.to/patron"),
    ]
    res = asyncio.run(flows.to_pydantic(None, _user_with(accounts), ["battle_tag", "discord", "twitch"]))

    assert len(res.social_accounts) == 4
    assert {s.provider for s in res.social_accounts} == {"battlenet", "discord", "twitch", "boosty"}
    primary_bn = next(s for s in res.social_accounts if s.username == "Player#1234")
    assert primary_bn.is_verified is True and primary_bn.is_primary is True
    # Legacy grouped fields are gone.
    assert not hasattr(res, "battle_tag")
    assert not hasattr(res, "discord")
    assert not hasattr(res, "twitch")


def test_to_pydantic_empty_entities_skips_identity_access():
    # No identity entity requested -> social_accounts not touched (would lazy-load otherwise).
    res = asyncio.run(flows.to_pydantic(None, models.User(id=7, name="Tester"), []))
    assert res.social_accounts == []


def test_to_pydantic_serializes_loaded_visibility_scopes():
    # When ``visibilities`` is eager-loaded, visible_global / visible_workspace_ids
    # reflect the real rows (presence of a global/workspace row = visible). This is
    # what the admin list (get_users) now loads so the profile-dialog switches match
    # the self-service modal instead of defaulting to visible_global=True.
    shown = _acc(1, SocialProvider.DISCORD, "shown", is_verified=True)
    shown.visibilities = [
        SocialAccountVisibility(account_id=1, workspace_id=None),
        SocialAccountVisibility(account_id=1, workspace_id=5),
    ]
    hidden = _acc(2, SocialProvider.TWITCH, "hidden", is_verified=True)
    hidden.visibilities = []  # loaded but no rows -> hidden from the public profile

    res = asyncio.run(flows.to_pydantic(None, _user_with([shown, hidden]), ["discord", "twitch"]))

    shown_read = next(s for s in res.social_accounts if s.username == "shown")
    hidden_read = next(s for s in res.social_accounts if s.username == "hidden")
    assert shown_read.visible_global is True
    assert shown_read.visible_workspace_ids == [5]
    assert hidden_read.visible_global is False
    assert hidden_read.visible_workspace_ids == []


def test_to_pydantic_defaults_visible_when_visibilities_unloaded():
    # No visibilities loaded (transient account) -> fail-open to visible_global=True,
    # never touching the relationship (avoids a lazy load outside the greenlet).
    acc = _acc(1, SocialProvider.DISCORD, "coolguy", is_verified=True)
    res = asyncio.run(flows.to_pydantic(None, _user_with([acc]), ["discord"]))
    assert res.social_accounts[0].visible_global is True
