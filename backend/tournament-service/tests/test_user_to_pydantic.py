"""Unit tests for tournament-service user_flows.to_pydantic (unified social_accounts)."""

import asyncio

from shared.core.social import SocialProvider

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
    ]
    res = asyncio.run(flows.to_pydantic(None, _user_with(accounts), ["battle_tag", "discord", "twitch"]))
    assert len(res.social_accounts) == 3
    assert {s.provider for s in res.social_accounts} == {"battlenet", "discord", "twitch"}
    primary = next(s for s in res.social_accounts if s.username == "Player#1234")
    assert primary.is_verified and primary.is_primary
    assert not hasattr(res, "battle_tag")


def test_to_pydantic_empty_entities_skips_identity_access():
    res = asyncio.run(flows.to_pydantic(None, models.User(id=7, name="Tester"), []))
    assert res.social_accounts == []
