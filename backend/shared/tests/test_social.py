"""Unit tests for the social provider catalog, handle grammar and normalization."""

import pytest

from shared.core.social import (
    OAUTH_PROVIDERS,
    PROVIDERS,
    SOCIAL_PROVIDERS,
    InvalidHandlePattern,
    SocialProvider,
    compile_handle_pattern,
    handle_pattern_for,
    is_oauth_provider,
    matches_handle_pattern,
    normalize_social_handle,
    oauth_handle,
    oauth_handle_candidates,
    social_provider_for_oauth,
)


def test_named_constants_match_the_catalog() -> None:
    """``SocialProvider.X`` and ``PROVIDERS`` must not drift apart.

    The constants are what 30+ call sites spell; the catalog is what the
    grammar, normalizer and OAuth capability hang off. A constant with no row
    resolves to "unknown provider" at runtime — silently unvalidated.
    """
    named = {
        value for name, value in vars(SocialProvider).items() if not name.startswith("_") and isinstance(value, str)
    }
    assert named == set(PROVIDERS)
    assert SOCIAL_PROVIDERS == frozenset(PROVIDERS)
    assert all(spec.id == key for key, spec in PROVIDERS.items())


def test_provider_order_is_a_total_order() -> None:
    orders = [spec.order for spec in PROVIDERS.values()]
    assert len(set(orders)) == len(orders)


def test_oauth_capability_drives_every_oauth_derived_set() -> None:
    assert OAUTH_PROVIDERS == {
        SocialProvider.BATTLENET,
        SocialProvider.DISCORD,
        SocialProvider.TWITCH,
    }
    assert is_oauth_provider(SocialProvider.DISCORD)
    assert not is_oauth_provider(SocialProvider.BOOSTY)
    assert social_provider_for_oauth(SocialProvider.TWITCH) == SocialProvider.TWITCH
    # A login mechanism that proves no player handle maps to no social identity.
    assert social_provider_for_oauth(SocialProvider.BOOSTY) is None
    assert social_provider_for_oauth("saml") is None


def test_normalize_battlenet_strips_spaces_and_casefolds() -> None:
    assert normalize_social_handle(SocialProvider.BATTLENET, "  Player # 1234 ") == "player#1234"
    assert normalize_social_handle(SocialProvider.BATTLENET, "Foo Bar#42") == "foobar#42"
    assert normalize_social_handle(SocialProvider.BATTLENET, "ABC#1") == normalize_social_handle(
        SocialProvider.BATTLENET, "abc#1"
    )


def test_normalize_other_providers_casefold() -> None:
    assert normalize_social_handle(SocialProvider.DISCORD, "  CoolGuy ") == "coolguy"
    assert normalize_social_handle(SocialProvider.TWITCH, "StreamerX") == "streamerx"
    assert normalize_social_handle(SocialProvider.BOOSTY, "") == ""
    assert normalize_social_handle(SocialProvider.VK, None) == ""
    # An unknown provider still matches case-insensitively rather than not at all.
    assert normalize_social_handle("myspace", " Tom ") == "tom"


@pytest.mark.parametrize(
    ("handle", "valid"),
    [
        ("Player#1234", True),
        # Spacing around '#' is normalized away before the grammar runs, which
        # is the whole reason the pattern may forbid whitespace.
        ("  Player # 1234 ", True),
        ("Фыва#1234", True),
        ("Player#12345", True),
        ("P#1234", False),  # name shorter than two characters
        ("ThirteenChars#1234", False),
        ("Player#123", False),  # discriminator shorter than four digits
        ("Player", False),
        ("Player#1234#5", False),
    ],
)
def test_battletag_grammar(handle: str, valid: bool) -> None:
    assert matches_handle_pattern(SocialProvider.BATTLENET, handle) is valid


@pytest.mark.parametrize(
    ("handle", "valid"),
    [
        ("coolguy", True),
        ("CoolGuy", True),  # casefolded before matching
        ("cool.guy_1", True),
        ("legacy#0001", True),  # retired discriminator form
        ("a", False),
        ("has space", False),
        ("emoji🙂", False),
    ],
)
def test_discord_grammar(handle: str, valid: bool) -> None:
    assert matches_handle_pattern(SocialProvider.DISCORD, handle) is valid


def test_blank_handle_is_not_a_format_error() -> None:
    """Emptiness is the "required" rule's business, not the grammar's.

    Conflating them made a blank OPTIONAL field fail its format check.
    """
    assert matches_handle_pattern(SocialProvider.BATTLENET, "")
    assert matches_handle_pattern(SocialProvider.BATTLENET, "   ")


def test_unknown_provider_has_nothing_to_enforce() -> None:
    assert handle_pattern_for("myspace") is None
    assert matches_handle_pattern("myspace", "anything at all")


def test_override_outranks_the_canon() -> None:
    assert handle_pattern_for(SocialProvider.TWITCH, r"only_me") == "only_me"
    # Blank/whitespace override falls through to the canon rather than
    # disabling validation.
    assert handle_pattern_for(SocialProvider.TWITCH, "   ") == PROVIDERS[SocialProvider.TWITCH].handle_pattern
    assert matches_handle_pattern(SocialProvider.TWITCH, "streamer", r"only_me") is False


def test_unusable_patterns_are_reported_not_ignored() -> None:
    with pytest.raises(InvalidHandlePattern):
        compile_handle_pattern("(unclosed")
    with pytest.raises(InvalidHandlePattern):
        compile_handle_pattern("a" * 1000)


def test_oauth_handle_prefers_the_providers_own_handle_field() -> None:
    """BattleNet's ``username`` is an account name; ``battletag`` is the handle."""
    assert oauth_handle(SocialProvider.BATTLENET, "account-name", {"battletag": "Player#1234"}) == "Player#1234"
    assert oauth_handle(SocialProvider.BATTLENET, "account-name", {}) == "account-name"
    # Providers with no override field keep the generic username.
    assert oauth_handle(SocialProvider.DISCORD, "coolguy", {"global_name": "Cool Guy"}) == "coolguy"


def test_oauth_handle_candidates_union_every_field_that_names_the_account() -> None:
    """Unioned, not ranked: the question is "does this connection prove this
    handle", and any field naming it is proof."""
    assert oauth_handle_candidates(
        SocialProvider.DISCORD,
        username="CoolGuy",
        display_name="Cool Guy",
        provider_data={"username": "coolguy_raw", "global_name": "CoolGlobal"},
    ) == {"coolguy", "cool guy", "coolguy_raw", "coolglobal"}
    assert oauth_handle_candidates(
        SocialProvider.TWITCH,
        username="StreamerX",
        display_name=None,
        provider_data={"login": "streamerx"},
    ) == {"streamerx"}


def test_battlenet_candidates_normalize_tag_spacing() -> None:
    """A stored ``player#1234`` must match a connection reporting ``Player # 1234``."""
    assert "player#1234" in oauth_handle_candidates(
        SocialProvider.BATTLENET,
        username="Player#1234",
        display_name=None,
        provider_data={"battletag": "Player # 1234"},
    )


def test_candidates_survive_a_provider_response_carrying_nothing_extra() -> None:
    assert oauth_handle_candidates(SocialProvider.DISCORD, username="Solo", display_name=None, provider_data=None) == {
        "solo"
    }
