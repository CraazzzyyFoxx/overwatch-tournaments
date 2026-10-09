"""The one catalog of builtin registration fields.

A builtin field is one whose answer has dedicated storage (a ``registration``
column, a ``registration_role`` row, ``registration_identity`` rows). The
schema only decides whether it is present, where, and under which rules; this
module says which keys exist, which params each accepts, and whose visibility
is not the organizer's to choose.

Pure data + functions: no I/O, no ORM, no FastAPI.
"""

from __future__ import annotations

from typing import Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field

from shared.core.social import PROVIDERS, SocialProvider

__all__ = (
    "BUILTIN_KEYS",
    "DEFAULT_PATTERNS",
    "IDENTITY_KEY_PREFIX",
    "IDENTITY_PROVIDERS",
    "BuiltinSpec",
    "IdentityParams",
    "RolesParams",
    "TopHeroesParams",
    "builtin_spec",
    "default_pattern",
    "identity_key",
    "identity_max_count",
    "identity_provider",
    "is_builtin_key",
)

IDENTITY_KEY_PREFIX = "identity_"

#: Providers a registration may ask for, one ``identity_<provider>`` builtin
#: each. Battle.net is one of them: its answer is a list like every other
#: identity's, primary first, smurfs after.
IDENTITY_PROVIDERS: tuple[str, ...] = (
    SocialProvider.BATTLENET,
    SocialProvider.DISCORD,
    SocialProvider.TWITCH,
    SocialProvider.BOOSTY,
    SocialProvider.VK,
    SocialProvider.YOUTUBE,
)

#: Upper bound an organizer may set on handles per identity field.
MAX_IDENTITY_COUNT = 10


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IdentityParams(_Strict):
    #: Only meaningful for providers that ``can_be_verified``; ignored otherwise.
    require_verified: bool = False
    #: How many handles the answer may carry (primary + extras). ``None`` means
    #: the provider's ``default_max_count``.
    max_count: int | None = Field(default=None, ge=1, le=MAX_IDENTITY_COUNT)


class TopHeroesParams(_Strict):
    enabled: bool = False
    required: bool = False
    max: int = Field(default=5, ge=1, le=20)


class RolesParams(_Strict):
    primary_required: bool = True
    additional_required: bool = False
    #: Legacy ``flex_role.enabled``; False ⇒ an all-primary (full-flex)
    #: submission is refused.
    flex_allowed: bool = True
    flex_mode: Literal["optional", "all_roles", "forced"] = "optional"
    #: Role code -> allowed sub-role slugs; ``{}`` means every catalog slug.
    subroles: dict[str, list[str]] = Field(default_factory=dict)
    top_heroes: TopHeroesParams = Field(default_factory=TopHeroesParams)


class BuiltinSpec(NamedTuple):
    key: str
    fixed_visibility: Literal["public", "organizers"] | None
    params_model: type[BaseModel] | None


_STATIC: dict[str, BuiltinSpec] = {
    "roles": BuiltinSpec("roles", "public", RolesParams),
    "stream_pov": BuiltinSpec("stream_pov", "public", None),
    #: "Call me in if a replacement is needed." Public on purpose: a reserve
    #: nobody can see on the roster cannot be called.
    "reserve": BuiltinSpec("reserve", "public", None),
    "public_notes": BuiltinSpec("public_notes", "public", None),
    "organizer_notes": BuiltinSpec("organizer_notes", "organizers", None),
}

BUILTIN_KEYS: tuple[str, ...] = tuple(_STATIC) + tuple(IDENTITY_KEY_PREFIX + p for p in IDENTITY_PROVIDERS)


def identity_key(provider: str) -> str:
    return IDENTITY_KEY_PREFIX + provider


def identity_provider(key: str) -> str | None:
    if not key.startswith(IDENTITY_KEY_PREFIX):
        return None
    provider = key[len(IDENTITY_KEY_PREFIX) :]
    return provider if provider in IDENTITY_PROVIDERS else None


def is_builtin_key(key: str) -> bool:
    return key in BUILTIN_KEYS


def builtin_spec(key: str) -> BuiltinSpec | None:
    if key in _STATIC:
        return _STATIC[key]
    provider = identity_provider(key)
    if provider is None:
        return None
    # The game handle is the roster's public face, as the BattleTag column was.
    visibility = "public" if provider == SocialProvider.BATTLENET else None
    return BuiltinSpec(key, visibility, IdentityParams)


def identity_max_count(provider: str, params: dict | None) -> int:
    """How many handles an ``identity_<provider>`` answer may carry."""
    explicit = IdentityParams.model_validate(params or {}).max_count
    if explicit is not None:
        return explicit
    spec = PROVIDERS.get(provider)
    return spec.default_max_count if spec is not None else 1


#: Server-side defaults, applied when a field carries no explicit
#: ``validation.regex``. Before the schema these patterns existed only in the
#: browser, so a non-browser writer (sheet sync, admin API) could store a
#: malformed handle; the server is now the one place that decides.
DEFAULT_PATTERNS: dict[str, str] = {
    identity_key(SocialProvider.BATTLENET): r"([^#]{2,12}#[0-9]{4,})",
    identity_key(SocialProvider.DISCORD): r"^[a-z0-9_.]{2,32}$",
    identity_key(SocialProvider.TWITCH): r"^[a-zA-Z0-9_]{4,25}$",
    identity_key(SocialProvider.BOOSTY): r"^[^#]{2,50}$",
    "url": r"^https?://.+$",
}


def default_pattern(key: str, kind: str) -> str | None:
    return DEFAULT_PATTERNS.get(key) or DEFAULT_PATTERNS.get(kind)
