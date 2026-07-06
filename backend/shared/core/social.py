"""Canonical social-network provider catalog and handle normalization.

Single source of truth for the set of social providers a player identity can
belong to (``players.social_account.provider``) and how a raw handle is
canonicalized for matching / uniqueness (``username_normalized``).
"""

from __future__ import annotations

import re

__all__ = (
    "SocialProvider",
    "OAUTH_PROVIDERS",
    "OAUTH_TO_SOCIAL",
    "SOCIAL_PROVIDERS",
    "is_oauth_provider",
    "normalize_social_handle",
)


class SocialProvider:
    """Canonical provider identifiers stored in ``social_account.provider``."""

    BATTLENET = "battlenet"
    DISCORD = "discord"
    TWITCH = "twitch"
    BOOSTY = "boosty"
    VK = "vk"
    YOUTUBE = "youtube"


SOCIAL_PROVIDERS: frozenset[str] = frozenset(
    {
        SocialProvider.BATTLENET,
        SocialProvider.DISCORD,
        SocialProvider.TWITCH,
        SocialProvider.BOOSTY,
        SocialProvider.VK,
        SocialProvider.YOUTUBE,
    }
)

# Providers that can be OAuth-verified (ownership proven → ``is_verified``).
OAUTH_PROVIDERS: frozenset[str] = frozenset({SocialProvider.BATTLENET, SocialProvider.DISCORD, SocialProvider.TWITCH})

# OAuth provider identifier -> canonical social provider (currently 1:1).
OAUTH_TO_SOCIAL: dict[str, str] = {
    SocialProvider.BATTLENET: SocialProvider.BATTLENET,
    SocialProvider.DISCORD: SocialProvider.DISCORD,
    SocialProvider.TWITCH: SocialProvider.TWITCH,
}

_BATTLE_TAG_HASH = re.compile(r"\s*#\s*")


def is_oauth_provider(provider: str) -> bool:
    return provider in OAUTH_PROVIDERS


def normalize_social_handle(provider: str, username: str | None) -> str:
    """Return the canonical form of ``username`` used for matching/uniqueness.

    All handles are casefolded so matching/dedup is case-insensitive (the legacy
    import lookups matched battletags via ``initcap``/``lower``/``capitalize``
    variants — a BattleTag is globally unique regardless of case, so two tags
    differing only in case denote the same account). BattleTags additionally have
    whitespace and ``#``-separator spacing normalized. Display casing is preserved
    separately in ``social_account.username``.
    """
    text = (username or "").strip()
    if provider == SocialProvider.BATTLENET:
        text = _BATTLE_TAG_HASH.sub("#", text).replace(" ", "").strip()
    return text.casefold()
