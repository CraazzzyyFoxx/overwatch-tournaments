"""Unit tests for the social provider catalog and handle normalization."""

from shared.core.social import (
    OAUTH_PROVIDERS,
    OAUTH_TO_SOCIAL,
    SocialProvider,
    is_oauth_provider,
    normalize_social_handle,
)


def test_oauth_providers_subset() -> None:
    assert OAUTH_PROVIDERS == {
        SocialProvider.BATTLENET,
        SocialProvider.DISCORD,
        SocialProvider.TWITCH,
    }
    assert is_oauth_provider(SocialProvider.DISCORD)
    assert not is_oauth_provider(SocialProvider.BOOSTY)
    # Every OAuth provider maps to a social provider 1:1.
    assert set(OAUTH_TO_SOCIAL) == OAUTH_PROVIDERS
    assert all(v in OAUTH_PROVIDERS for v in OAUTH_TO_SOCIAL.values())


def test_normalize_battlenet_strips_spaces_and_casefolds() -> None:
    # Whitespace and '#' spacing normalized; casefolded (case-insensitive matching).
    assert normalize_social_handle(SocialProvider.BATTLENET, "  Player # 1234 ") == "player#1234"
    assert normalize_social_handle(SocialProvider.BATTLENET, "Foo Bar#42") == "foobar#42"
    # case variants of the same BattleTag collapse to one normalized form
    assert normalize_social_handle(SocialProvider.BATTLENET, "ABC#1") == normalize_social_handle(
        SocialProvider.BATTLENET, "abc#1"
    )


def test_normalize_other_providers_casefold() -> None:
    assert normalize_social_handle(SocialProvider.DISCORD, "  CoolGuy ") == "coolguy"
    assert normalize_social_handle(SocialProvider.TWITCH, "StreamerX") == "streamerx"
    assert normalize_social_handle(SocialProvider.BOOSTY, "") == ""
    assert normalize_social_handle(SocialProvider.VK, None) == ""
