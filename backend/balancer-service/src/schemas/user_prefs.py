"""The caller's own pickup-mix settings: everything a host configures, once.

Deliberately not the full ``ConfigOverrides`` vocabulary -- only these keys ever
reach the mix engine, so the wire names them one by one instead of carrying an
opaque blob a client could stuff a tournament-GA knob into. The read and the
write carry the same stored fields: a PUT answers with exactly what the next GET returns.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field

from shared.disciplines import DISCIPLINES
from shared.domain.pick_ban_rules import mix_ban_preset
from src.domain.balancer.config.defaults import MAX_RESULT_VARIANTS, MixRules, validate_role_settings

__all__ = (
    "MAX_POINTS_PER_WIN",
    "MixFormationDefault",
    "MixRoleSettings",
    "UserMixPreferencesRead",
    "UserMixPreferencesUpsert",
)

#: Upper bound on the rank-adjustment-per-win. Generous for any plausible rank
#: scale, guards against a fat-fingered setting wrecking the host's whole rank
#: book in one recorded match.
MAX_POINTS_PER_WIN = 1000

_TILT_DOC = (
    "Trade-off between rank balance (0) and role comfort (1); null leaves the mix engine's own 0.5 weighting in place."
)
_SETTINGS_DOC = (
    "Per-role mix weights, keyed by declared role code: how much this role's gap counts "
    "towards role fairness. An omitted role weighs 1.0; null means no per-role opinion at all."
)
_VARIANTS_DOC = "How many balance options the solver keeps for the host to page through; null leaves the mix default."
_POINTS_DOC = (
    "How far a decided match moves both teams' ranks in this account's own rank book. "
    "0 and null both mean recording a match adjusts nothing."
)
_MODE_DOC = (
    "How recording a match moves this account's rank book: 'points' by points_per_win, 'ranker' by the "
    "mix ranker (each seat by its own amount; mixes then balance on the effective rating). The workspace's "
    "hidden ratings advance in both."
)
_BANS_DOC = (
    "Per game (discipline code): the hero ban preset a new mix of that game starts with. "
    "A game left out starts without bans."
)


def _valid_ban_presets(value: dict[str, str]) -> dict[str, str]:
    for discipline, code in value.items():
        if mix_ban_preset(discipline, code) is None:
            raise ValueError(f"{code!r} is not a hero ban preset a {discipline!r} mix can play")
    return value


_BanPresets = Annotated[dict[str, str], AfterValidator(_valid_ban_presets)]

_FORMATION_DOC = (
    "Per game (discipline code): how a new mix of that game forms its teams -- 'balance' (the solver) or 'draft' "
    "(captains pick) -- and the draft's pick clock in seconds (10..600). A game left out starts with the balancer "
    "and 30 seconds."
)


class MixFormationDefault(BaseModel):
    """How a new mix of one game forms its teams (spec §4.3)."""

    model_config = ConfigDict(extra="forbid")

    team_formation: Literal["balance", "draft"] = "balance"
    draft_pick_seconds: int = Field(default=30, ge=10, le=600)


def _valid_formation_games(value: dict[str, MixFormationDefault]) -> dict[str, MixFormationDefault]:
    unknown = sorted(set(value) - set(DISCIPLINES))
    if unknown:
        raise ValueError(f"not installed games: {unknown}")
    return value


_FormationDefaults = Annotated[dict[str, MixFormationDefault], AfterValidator(_valid_formation_games)]

_RULES_DOC = "Soft rules of the mix engine (Deadlock lane matchup); null keeps every rule's default."

RatingMode = Literal["points", "ranker"]


class MixRoleSettings(BaseModel):
    """The mix engine's share of a role's settings -- the only one a host may set.

    The tournament drawer owns the rest (``impact``, the line weights), and
    ``extra="forbid"`` is what keeps a host from storing a GA knob through their
    own preferences.
    """

    model_config = ConfigDict(extra="forbid")

    mix_weight: float = Field(ge=0.0, le=100.0, description="Multiplier for this role's gap in role fairness.")


_RoleSettings = Annotated[dict[str, MixRoleSettings], BeforeValidator(validate_role_settings)]


class UserMixPreferencesRead(BaseModel):
    """Stored preferences; unset knobs use the engine defaults."""

    mix_comfort_tilt: float | None = Field(default=None, ge=0.0, le=1.0, description=_TILT_DOC)
    role_settings: _RoleSettings | None = Field(default=None, description=_SETTINGS_DOC)
    max_result_variants: int | None = Field(default=None, ge=1, le=MAX_RESULT_VARIANTS, description=_VARIANTS_DOC)
    open_slot_settings: MixRoleSettings | None = None
    points_per_win: int | None = Field(default=None, ge=0, le=MAX_POINTS_PER_WIN, description=_POINTS_DOC)
    rating_mode: RatingMode = Field(default="points", description=_MODE_DOC)
    hero_ban_presets: dict[str, str] = Field(default_factory=dict, description=_BANS_DOC)
    formation_defaults: dict[str, MixFormationDefault] = Field(default_factory=dict, description=_FORMATION_DOC)
    mix_rules: MixRules | None = Field(default=None, description=_RULES_DOC)


class UserMixPreferencesUpsert(BaseModel):
    """A full replacement; nullable knobs unset the corresponding override."""

    model_config = ConfigDict(extra="forbid")

    mix_comfort_tilt: float | None = Field(ge=0.0, le=1.0, description=_TILT_DOC)
    role_settings: _RoleSettings | None = Field(description=_SETTINGS_DOC)
    max_result_variants: int | None = Field(ge=1, le=MAX_RESULT_VARIANTS, description=_VARIANTS_DOC)
    open_slot_settings: MixRoleSettings | None
    points_per_win: int | None = Field(ge=0, le=MAX_POINTS_PER_WIN, description=_POINTS_DOC)
    rating_mode: RatingMode = Field(description=_MODE_DOC)
    hero_ban_presets: _BanPresets = Field(description=_BANS_DOC)
    formation_defaults: _FormationDefaults = Field(description=_FORMATION_DOC)
    mix_rules: MixRules | None = Field(description=_RULES_DOC)
