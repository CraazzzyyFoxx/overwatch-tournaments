"""Canonical social-provider catalog: identity, handle grammar, normalization.

Single source of truth for the set of social providers a player identity can
belong to (``players.social_account.provider``), for the shape a handle must
have, and for how a raw handle is canonicalized for matching / uniqueness
(``username_normalized``).

Everything a provider "is" lives in exactly one :class:`ProviderSpec` row of
:data:`PROVIDERS`. Before this catalog, the BattleTag grammar alone existed in
five places in three mutually incompatible spellings (two service settings, two
frontend defaults and a sheet scanner), so the same handle was accepted by one
service and refused by the next. Adding a sixth spelling is now impossible: the
set, the grammar, the normalizer, the OAuth field shapes and the display label
are all read off the same row, and the frontend is served that row rather than
keeping its own copy.

**Patterns match the NORMALIZED handle, never the raw input.** That is what lets
a grammar be written once: ``discord`` may say ``[a-z0-9_.]`` without refusing
``CoolGuy``, because by the time the pattern runs the value is already
``coolguy`` — the same string that will be stored in ``username_normalized`` and
matched against. A pattern written against raw input would have to re-encode the
normalizer's rules, which is how the two drifted apart in the first place.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Final, Literal

__all__ = (
    "MAX_HANDLE_PATTERN_LENGTH",
    "OAUTH_PROVIDERS",
    "PROVIDERS",
    "SOCIAL_PROVIDERS",
    "InvalidHandlePattern",
    "ProviderSpec",
    "SocialProvider",
    "compile_handle_pattern",
    "get_provider",
    "handle_pattern_for",
    "is_oauth_provider",
    "matches_handle_pattern",
    "normalize_social_handle",
    "oauth_handle",
    "oauth_handle_candidates",
    "social_provider_for_oauth",
)


class SocialProvider:
    """Canonical provider identifiers stored in ``social_account.provider``.

    Constants rather than bare strings so a typo is an ``AttributeError`` at
    import instead of a row nobody ever matches. ``test_social.py`` pins them to
    :data:`PROVIDERS` keys, so the two cannot drift.
    """

    BATTLENET = "battlenet"
    DISCORD = "discord"
    TWITCH = "twitch"
    BOOSTY = "boosty"
    VK = "vk"
    YOUTUBE = "youtube"


#: How a raw handle becomes its canonical matching form.
#:
#: - ``casefold`` — trim + casefold. A handle is case-insensitively unique
#:   everywhere we integrate, so two spellings denote one account.
#: - ``battletag`` — additionally collapse ``#``-separator spacing and strip
#:   every remaining space, because a BattleTag pasted out of a chat client
#:   routinely arrives as ``Player # 1234``.
NormalizeRule = Literal["casefold", "battletag"]


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    """Everything the platform knows about one social provider."""

    id: str
    label: str
    #: Display/selection order, ascending. Shared with the frontend so both
    #: sides list providers identically.
    order: int

    #: Grammar of a valid handle, matched against the NORMALIZED value with
    #: ``fullmatch``. Unanchored by convention: anchoring is the validator's job
    #: and doing it here would make organizer overrides double-anchor.
    handle_pattern: str
    #: i18n key of the "wrong format" message. A key, not a sentence: the
    #: registry is served to a frontend that renders in the user's locale.
    handle_error_key: str
    normalize: NormalizeRule = "casefold"

    #: Whether a handle may be typed in by hand.
    supports_text: bool = True
    #: Whether ownership can be proven by OAuth (``social_account.is_verified``).
    supports_oauth: bool = False
    #: Whether a paid subscription on this provider can be resolved.
    supports_subscription: bool = False

    #: Default ceiling on how many handles of this provider one registration may
    #: carry. Five for BattleNet — smurfs are a normal Overwatch fact — one
    #: everywhere else. Per-tournament config may narrow or widen it.
    default_max_count: int = 1

    #: ``str.format`` template for a public profile URL, or None when the
    #: provider has no addressable profile.
    profile_url: str | None = None

    #: Keys of the OAuth provider's raw response that may CARRY the canonical
    #: handle, in preference order. Consulted before falling back to the
    #: provider's generic ``username`` when storing a verified account.
    oauth_primary_fields: tuple[str, ...] = ()
    #: Keys of the raw response that may NAME the same account. Used only for
    #: matching an existing handle against a live OAuth connection, so a
    #: legitimately-owned account is not refused because the provider reported
    #: it under a different field than the one we stored.
    oauth_alias_fields: tuple[str, ...] = ()


PROVIDERS: Final[dict[str, ProviderSpec]] = {
    spec.id: spec
    for spec in (
        ProviderSpec(
            id=SocialProvider.BATTLENET,
            label="Battle.net",
            order=0,
            # 2-12 characters (Blizzard allows non-ASCII, so no \w restriction)
            # with no '#' and no whitespace, then '#' and at least four digits.
            handle_pattern=r"[^#\s]{2,12}#\d{4,}",
            handle_error_key="identity.battlenet.format",
            normalize="battletag",
            supports_oauth=True,
            default_max_count=5,
            oauth_primary_fields=("battletag", "battle_tag"),
            oauth_alias_fields=("battletag", "battle_tag", "preferred_username"),
        ),
        ProviderSpec(
            id=SocialProvider.DISCORD,
            label="Discord",
            order=1,
            # Modern Discord usernames are lowercase and unique; the trailing
            # ``#1234`` is the retired discriminator form, still carried by
            # accounts that registered before the 2023 migration.
            handle_pattern=r"[a-z0-9_.]{2,32}(?:#\d{4})?",
            handle_error_key="identity.discord.format",
            supports_oauth=True,
            supports_subscription=True,
            oauth_alias_fields=("username", "global_name"),
        ),
        ProviderSpec(
            id=SocialProvider.TWITCH,
            label="Twitch",
            order=2,
            handle_pattern=r"[a-z0-9_]{4,25}",
            handle_error_key="identity.twitch.format",
            supports_oauth=True,
            supports_subscription=True,
            profile_url="https://twitch.tv/{handle}",
            oauth_alias_fields=("login",),
        ),
        ProviderSpec(
            id=SocialProvider.BOOSTY,
            label="Boosty",
            order=3,
            handle_pattern=r"[^#\s]{2,50}",
            handle_error_key="identity.boosty.format",
            # Deliberately not OAuth-capable: Boosty exposes no third-party
            # OAuth, and neither viable proof path (Discord roles, challenge
            # code) reveals the handle. What gets verified is the SUBSCRIPTION,
            # never the nickname.
            supports_subscription=True,
            profile_url="https://boosty.to/{handle}",
        ),
        ProviderSpec(
            id=SocialProvider.VK,
            label="VK",
            order=4,
            handle_pattern=r"[a-z0-9_.]{3,32}",
            handle_error_key="identity.vk.format",
            profile_url="https://vk.com/{handle}",
        ),
        ProviderSpec(
            id=SocialProvider.YOUTUBE,
            label="YouTube",
            order=5,
            handle_pattern=r"@?[a-z0-9_.\-]{3,30}",
            handle_error_key="identity.youtube.format",
            profile_url="https://youtube.com/{handle}",
        ),
    )
}

SOCIAL_PROVIDERS: Final[frozenset[str]] = frozenset(PROVIDERS)

# Providers that can be OAuth-verified (ownership proven → ``is_verified``).
OAUTH_PROVIDERS: Final[frozenset[str]] = frozenset(spec.id for spec in PROVIDERS.values() if spec.supports_oauth)

#: Ceiling on an organizer-supplied handle pattern. The pattern is compiled and
#: run server-side on every submission, so an unbounded one is a ReDoS handed to
#: us by whoever can edit a registration form.
MAX_HANDLE_PATTERN_LENGTH: Final = 256

_BATTLE_TAG_HASH = re.compile(r"\s*#\s*")


class InvalidHandlePattern(ValueError):
    """An organizer-supplied handle pattern is unusable (too long or not a regex).

    Raised rather than silently ignored: falling back to "no validation" would
    turn one organizer's typo into an unvalidated identity field that still
    looks validated in the form editor.
    """


def get_provider(provider: str) -> ProviderSpec | None:
    return PROVIDERS.get(provider)


def is_oauth_provider(provider: str) -> bool:
    return provider in OAUTH_PROVIDERS


def social_provider_for_oauth(provider: str) -> str | None:
    """The social identity an OAuth login maps to, or None if it maps to none.

    Identity today — an OAuth provider IS a social provider — but the guard is
    the point: a login mechanism that proves nothing about a player handle
    (an email/password IdP, an SSO broker) must not silently mint a
    ``social_account`` row under its own name.
    """
    return provider if provider in OAUTH_PROVIDERS else None


def normalize_social_handle(provider: str, username: str | None) -> str:
    """Return the canonical form of ``username`` used for matching/uniqueness.

    Display casing is preserved separately in ``social_account.username``; this
    is only ever the lookup key. An unknown provider falls back to the plain
    casefold rule — a handle we cannot classify is still better matched
    case-insensitively than not at all.
    """
    text = (username or "").strip()
    spec = PROVIDERS.get(provider)
    if spec is not None and spec.normalize == "battletag":
        text = _BATTLE_TAG_HASH.sub("#", text).replace(" ", "").strip()
    return text.casefold()


def handle_pattern_for(provider: str, override: str | None = None) -> str | None:
    """The grammar to enforce for ``provider``: the organizer's, else the canon.

    ``None`` means "nothing to enforce" — an unknown provider with no override.
    Callers must not substitute a default of their own; that is the duplication
    this module exists to delete.
    """
    trimmed = (override or "").strip()
    if trimmed:
        return trimmed
    spec = PROVIDERS.get(provider)
    return spec.handle_pattern if spec is not None else None


@lru_cache(maxsize=256)
def compile_handle_pattern(pattern: str) -> re.Pattern[str]:
    """Compile a handle grammar, bounded and cached.

    Cached because organizer overrides are per-form and re-compiled on every
    submission otherwise; bounded because the cache key is attacker-influenced.
    """
    if len(pattern) > MAX_HANDLE_PATTERN_LENGTH:
        raise InvalidHandlePattern(f"Handle pattern exceeds {MAX_HANDLE_PATTERN_LENGTH} characters")
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise InvalidHandlePattern(f"Invalid handle pattern: {exc}") from exc


def matches_handle_pattern(provider: str, value: str, override: str | None = None) -> bool:
    """Whether ``value`` is a well-formed handle for ``provider``.

    ``value`` is normalized here, so callers pass whatever the user typed. An
    empty value matches: "required" is a separate rule, and conflating the two
    made a blank optional field fail its format check.
    """
    pattern = handle_pattern_for(provider, override)
    if pattern is None:
        return True
    candidate = normalize_social_handle(provider, value)
    if not candidate:
        return True
    return compile_handle_pattern(pattern).fullmatch(candidate) is not None


def oauth_handle(provider: str, username: str, provider_data: dict | None = None) -> str:
    """The handle to STORE for a freshly linked OAuth account.

    A provider's generic ``username`` is not always the handle players know each
    other by — BattleNet's is an account name, while ``battletag`` is the thing
    printed in-game — so the spec names which raw fields outrank it.
    """
    spec = PROVIDERS.get(provider)
    data = provider_data or {}
    if spec is not None:
        for field in spec.oauth_primary_fields:
            value = data.get(field)
            if value:
                return str(value)
    return username


def oauth_handle_candidates(
    provider: str,
    *,
    username: str | None,
    display_name: str | None,
    provider_data: dict | None = None,
) -> set[str]:
    """Every normalized handle this OAuth response could have named the account by.

    Compared directly against ``social_account.username_normalized`` to decide
    whether a stored handle is backed by a real OAuth connection. Unioned rather
    than ranked: the question is "does this connection prove this handle", and
    any field naming it is proof.
    """
    spec = PROVIDERS.get(provider)
    data = provider_data or {}
    raw: set[str | None] = {username, display_name}
    if spec is not None:
        raw |= {data.get(field) for field in spec.oauth_alias_fields}
    return {normalize_social_handle(provider, value) for value in raw if value}
