"""Algorithm configuration defaults for the balancer solver.

:class:`AlgorithmConfig` is the ONLY place a solver knob is declared. Its field
carries everything downstream needs: type, default, accepted range and — via
:func:`knob` — the operator-facing label/group that the config drawer renders.

Everything else is derived from it and must stay derived:

* ``public_contract.PUBLIC_CONFIG_KEYS`` — what a saved config may write
* ``public_contract.ConfigOverrides`` — the request/write schema
* ``provider.EDITABLE_CONFIG_FIELD_KEYS`` / ``CONFIG_LIMITS`` /
  ``build_config_fields`` — the ``GET /config`` payload the UI draws
* ``presets.ConfigPresets.DEFAULT``
"""

from __future__ import annotations

import typing
from collections.abc import Mapping

import annotated_types
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, SettingsConfigDict

from shared.disciplines import DISCIPLINES

ConfigGroup = typing.Literal["Algorithm", "Quality weights", "Strategy", "Solver output"]
ConfigControl = typing.Literal["integer", "float", "boolean", "slider", "roles", "open_slot"]

# Upper bound for a cost-function weight. It is the field's own constraint, so
# the drawer slider and the API accept the same range.
MAX_WEIGHT = 10000.0

# Most balance options one run hands back, whichever solver. Past a hundred
# nobody pages further, and every option is shipped and (for a mix) stored.
MAX_RESULT_VARIANTS = 100


class RoleSettings(BaseModel):
    """Everything an engine weighs one role by — the only place a per-role weight lives.

    Neither engine carries role names or role defaults of its own: Python sends
    these numbers per role the roster actually fields, so a new game's roles are
    a change of data here and nothing else.

    Frozen because one instance per role is shared by every :class:`AlgorithmConfig`;
    an override copies with the fields it names (:func:`apply_config_overrides`).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    impact: float = Field(
        ge=0.0,
        le=MAX_WEIGHT,
        title="Impact",
        description="Importance multiplier for this role's contribution when comparing effective team totals.",
    )
    line_gap_weight: float = Field(
        ge=0.0,
        le=MAX_WEIGHT,
        title="Line gap",
        description=(
            "Penalty multiplier for the largest gap between adjacent (sorted by strength) lines of this role."
        ),
    )
    line_std_weight: float = Field(
        ge=0.0,
        le=MAX_WEIGHT,
        title="Line spread",
        description="Penalty multiplier for this role's line-strength standard deviation across teams.",
    )
    mix_weight: float = Field(
        ge=0.0,
        le=100.0,
        title="Mix weight",
        description="Mix-engine multiplier for this role's gap in the role-fairness term.",
    )


NEUTRAL_ROLE_SETTINGS = RoleSettings(impact=1.0, line_gap_weight=0.0, line_std_weight=0.0, mix_weight=1.0)


def declared_role_settings(discipline: str | None, preset: str = "default") -> dict[str, dict[str, float]]:
    """What ``discipline`` declares for ``preset`` (``DisciplineSpec.balancer_role_settings``): complete per role for
    ``"default"``, partial overrides for a named balancer preset. An unknown or absent game declares nothing -- it is
    never weighed as another one."""
    spec = DISCIPLINES.get(discipline) if discipline else None
    declared = spec.balancer_role_settings.get(preset, {}) if spec is not None else {}
    return {code: dict(weights) for code, weights in declared.items()}


def default_role_settings(discipline: str | None) -> dict[str, RoleSettings]:
    """The role weights a run of ``discipline`` starts from; a role without an entry weighs ``NEUTRAL_ROLE_SETTINGS``."""
    return {code: RoleSettings(**weights) for code, weights in declared_role_settings(discipline).items()}


def validate_role_settings(value: typing.Any) -> typing.Any:
    """Weights belong to declared module roles, never the open-slot key."""
    if value is None:
        return value
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("role_settings must be an object with role-code keys")
    known = {role.code for spec in DISCIPLINES.values() for dimension in spec.dimensions for role in dimension.roles}
    if unknown := set(value) - known:
        raise ValueError(f"Unknown role settings codes: {', '.join(sorted(unknown))}")
    return value


#: Read by the mix engine only, so the tournament drawer neither renders nor
#: stores it — the same split every other ``mix_*`` knob gets.
MIX_ONLY_ROLE_FIELDS = frozenset({"mix_weight"})

#: Upper bound of a mix rule weight; the rule penalties sit in rating units like
#: the fairness term (weight 1.0 at the default comfort tilt).
MAX_MIX_RULE_WEIGHT = 10.0


class LaneMatchupRule(BaseModel):
    """Seat a format's lanes so lane opponents match in strength (``mix.rs`` ``lane_matchup``).

    Applies only to a format whose preset declares ``lanes`` (Deadlock 6v6).
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    weight: float = Field(
        default=0.5,
        ge=0.0,
        le=MAX_MIX_RULE_WEIGHT,
        description="Penalty per rating point between lane opponents, each lane compared strongest to strongest.",
    )
    cohesion_weight: float = Field(
        default=0.25,
        ge=0.0,
        le=MAX_MIX_RULE_WEIGHT,
        description="Penalty per rating point between the players of one lane: strong lane with strong.",
    )


class MixRules(BaseModel):
    """The mix engine's soft rules, one field per rule kind."""

    model_config = ConfigDict(extra="forbid")

    lane_matchup: LaneMatchupRule = Field(default_factory=LaneMatchupRule)


def tournament_role_settings(role_settings: Mapping[str, RoleSettings]) -> dict[str, dict[str, float]]:
    """Per-role settings as the operator drawer sees them: mix-only fields dropped."""
    return {code: settings.model_dump(exclude=MIX_ONLY_ROLE_FIELDS) for code, settings in role_settings.items()}


def knob(label: str, group: ConfigGroup, control: ConfigControl | None = None) -> dict[str, typing.Any]:
    """Mark a field operator-editable and give it its drawer presentation.

    Presence of this block is what makes a knob editable: it gets a row in
    ``GET /config`` and may appear in a tournament config. A field without it is
    internal (``role_mask`` is a projection of the roster shape,
    ``rating_scale_ceiling`` is applied Python-side) or belongs to another engine
    (``mix_*`` is read by ``mix_balancer`` only, and would be a dead control in
    the tournament drawer).

    ``control`` defaults to the annotation (``int`` -> integer, ``float`` ->
    float, ``bool`` -> boolean); pass it only to ask for a different widget.
    """
    ui: dict[str, typing.Any] = {"label": label, "group": group}
    if control is not None:
        ui["control"] = control
    return {"ui": ui}


def field_ui(field: FieldInfo) -> dict[str, typing.Any] | None:
    """The :func:`knob` block of a field, or ``None`` when it is not editable."""
    extra = field.json_schema_extra
    return extra.get("ui") if isinstance(extra, dict) else None


def field_limits(field: FieldInfo) -> dict[str, int | float]:
    """``{"min": ..., "max": ...}`` read off the field's own constraints."""
    limits: dict[str, int | float] = {}
    for constraint in field.metadata:
        if isinstance(constraint, annotated_types.Ge):
            limits["min"] = constraint.ge  # type: ignore[assignment]
        elif isinstance(constraint, annotated_types.Le):
            limits["max"] = constraint.le  # type: ignore[assignment]
    return limits


def field_control(field: FieldInfo) -> ConfigControl:
    """Widget for a field: explicit ``control``, else derived from its type.

    ``time_limit_ms`` is ``int | None`` (omitting it means "no hard stop"), so
    the optional wrapper is looked through before deciding.
    """
    ui = field_ui(field) or {}
    if control := ui.get("control"):
        return typing.cast(ConfigControl, control)
    types_ = set(typing.get_args(field.annotation)) - {type(None)} or {field.annotation}
    return "boolean" if bool in types_ else "integer" if int in types_ else "float"


class AlgorithmConfig(BaseSettings):
    """Configuration for balancer solver parameters."""

    model_config = SettingsConfigDict(
        env_prefix="BALANCER_",
        extra="ignore",
    )

    # Role configuration. Not an editable setting: every run overwrites it with
    # the owner's resolved roster shape (see ``algorithm/runtime.py``); a run
    # without one has nothing to fill and is refused there, never given a game.
    role_mask: dict[str, int] = Field(
        default_factory=dict,
        description="Per-team slot counts the solver fills; a projection of the tournament roster shape",
    )

    # Shared optimizer parameters. Budget picked by the ``quality_harness``
    # ablation; it stays a cheap fallback (5x lighter than ``HIGH_QUALITY``)
    # within the API-key caps (population <= 150, generations <= 500).
    population_size: int = Field(
        default=100,
        ge=10,
        le=1000,
        description=(
            "Number of candidate balances kept per generation. Higher values "
            "improve search coverage and cost more time."
        ),
        json_schema_extra=knob("Population size", "Algorithm"),
    )
    generation_count: int = Field(
        default=400,
        ge=10,
        le=5000,
        description="Maximum optimization iterations. Higher values can improve quality and increase runtime.",
        json_schema_extra=knob("Generations", "Algorithm"),
    )
    mutation_rate: float = Field(
        default=0.35,
        ge=0.0,
        le=1.0,
        description="Probability that a solution is changed while producing the next generation.",
        json_schema_extra=knob("Mutation rate", "Algorithm"),
    )
    mutation_strength: int = Field(
        default=2,
        ge=1,
        le=10,
        description="Number of swap/change operations attempted during a mutation.",
        json_schema_extra=knob("Mutation strength", "Algorithm"),
    )

    # Cost function weights. Only the composition inside an axis matters:
    # scaling a whole axis uniformly is a no-op, because NSGA-II dominance and
    # the min-max knee normalization are both scale invariant. These are the
    # middle weights, the same composition ``COMBINED`` uses.
    average_mmr_balance_weight: float = Field(
        default=2.0,
        ge=0.0,
        le=MAX_WEIGHT,
        description="Penalty weight for differences between team average MMR values.",
        json_schema_extra=knob("Average MMR balance", "Quality weights"),
    )
    team_total_balance_weight: float = Field(
        default=1.0,
        ge=0.0,
        le=MAX_WEIGHT,
        description="Penalty weight for standard deviation of total team rating sums.",
        json_schema_extra=knob("Team total consistency", "Quality weights"),
    )
    max_team_gap_weight: float = Field(
        default=1.5,
        ge=0.0,
        le=MAX_WEIGHT,
        description="Penalty weight for the rating gap between the strongest and weakest teams.",
        json_schema_extra=knob("Max team gap", "Quality weights"),
    )
    role_discomfort_weight: float = Field(
        default=2.0,
        ge=0.0,
        le=MAX_WEIGHT,
        description="Penalty weight for assigning players away from their preferred roles.",
        json_schema_extra=knob("Role discomfort", "Quality weights"),
    )
    max_role_discomfort_weight: float = Field(
        default=1.0,
        ge=0.0,
        le=MAX_WEIGHT,
        description="Penalty weight for the single worst role discomfort assignment in a solution.",
        json_schema_extra=knob("Worst discomfort", "Quality weights"),
    )
    role_line_balance_weight: float = Field(
        default=1.0,
        ge=0.0,
        le=MAX_WEIGHT,
        description="Penalty weight for uneven rating strength between the same role across teams.",
        json_schema_extra=knob("Role line balance", "Quality weights"),
    )
    # Per-team normalized terms (Rust divides by team count): defaults are
    # pre-multiplied so their calibration holds at 4 teams.
    intra_team_std_weight: float = Field(
        default=1.8,
        ge=0.0,
        le=MAX_WEIGHT,
        description=(
            "Weight for the standard deviation of ratings inside each team. "
            "Higher values push the optimizer to spread top players across teams."
        ),
        json_schema_extra=knob("Intra-team rating std", "Quality weights"),
    )
    internal_role_spread_weight: float = Field(
        default=0.8,
        ge=0.0,
        le=MAX_WEIGHT,
        description="Penalty weight for uneven average strength between roles inside the same team.",
        json_schema_extra=knob("Internal role spread", "Quality weights"),
    )
    sub_role_collision_weight: float = Field(
        default=24.0,
        ge=0.0,
        le=MAX_WEIGHT,
        description=(
            "Penalty weight per pair of players in the same team sharing the "
            "same role subclass, normalized per team count. Use 0 to disable."
        ),
        json_schema_extra=knob("Subrole collision", "Quality weights"),
    )
    low_rank_threshold: int = Field(
        default=0,
        ge=0,
        le=10000,
        description=(
            "Players whose best role rating is at or below this value (canonical "
            "scale, see rating_scale_ceiling) count as low-rank; teams with two "
            "or more of them get penalized. 0 disables the mechanic."
        ),
        json_schema_extra=knob("Low-rank threshold", "Quality weights"),
    )
    low_rank_collision_weight: float = Field(
        default=250.0,
        ge=0.0,
        le=MAX_WEIGHT,
        description=(
            "Penalty weight per pair of low-rank players in the same team, "
            "normalized per team count. Discourages stacking two low-rank "
            "players together."
        ),
        json_schema_extra=knob("Low-rank pair penalty", "Quality weights"),
    )
    team_max_pain_weight: float = Field(
        default=0.6,
        ge=0.0,
        le=MAX_WEIGHT,
        description=(
            "Penalty weight for the per-team maximum role discomfort averaged "
            "over all teams. Makes 'one suffering player in every team' visible, "
            "unlike the single global maximum."
        ),
        json_schema_extra=knob("Per-team worst discomfort", "Quality weights"),
    )
    rank_comfort_tilt: float = Field(
        default=0.45,
        ge=0.0,
        le=1.0,
        description=(
            "Shifts how result variants are ranked: 0.5 weighs team balance "
            "(StdDev) and comfort (off-role) equally; toward 1 prioritises "
            "comfort/off-role, toward 0 prioritises balance. Ordering and "
            "primary selection only — does not change the optimizer search."
        ),
        json_schema_extra=knob("Rank tilt (balance <-> comfort)", "Quality weights", control="slider"),
    )

    # Rust MOO advanced objective shaping
    # Empty (every role neutral) until a run seeds its game's declared weights (``default_role_settings``).
    role_settings: dict[str, RoleSettings] = Field(
        default_factory=dict,
        description=(
            "Per-role weights keyed by roster slot code: how much a role counts "
            "towards a team's effective total, and how hard uneven lines of it are penalized."
        ),
        json_schema_extra=knob("Role weights", "Quality weights", control="roles"),
    )
    _role_codes = field_validator("role_settings", mode="before")(validate_role_settings)

    open_slot_settings: RoleSettings = Field(
        default=NEUTRAL_ROLE_SETTINGS,
        description="Weights of open slots without a role constraint.",
        json_schema_extra=knob("Open slot weights", "Quality weights", control="open_slot"),
    )
    effective_total_std_weight: float = Field(
        default=1.2,
        ge=0.0,
        le=MAX_WEIGHT,
        description="Penalty multiplier for weighted effective team-total standard deviation.",
        json_schema_extra=knob("Effective total std", "Quality weights"),
    )

    # Strategy configuration
    use_captains: bool = Field(
        default=True,
        description=("Marks top-rated players as captains and uses them as team anchors when supported by the solver."),
        json_schema_extra=knob("Use captains", "Strategy"),
    )
    convergence_patience: int = Field(
        default=100,
        ge=0,
        le=5000,
        description="Generations without meaningful Pareto improvement before early stopping can trigger.",
        json_schema_extra=knob("Convergence patience", "Strategy"),
    )
    convergence_epsilon: float = Field(
        default=0.005,
        ge=0.0,
        le=1.0,
        description="Minimum relative improvement required to continue once convergence patience is reached.",
        json_schema_extra=knob("Convergence epsilon", "Strategy"),
    )
    mutation_rate_min: float = Field(
        default=0.15,
        ge=0.0,
        le=1.0,
        description="Lower bound for the adaptive mutation rate during Rust MOO search.",
        json_schema_extra=knob("Mutation rate min", "Strategy"),
    )
    mutation_rate_max: float = Field(
        default=0.65,
        ge=0.0,
        le=1.0,
        description="Upper bound for the adaptive mutation rate during Rust MOO search.",
        json_schema_extra=knob("Mutation rate max", "Strategy"),
    )
    island_count: int = Field(
        default=6,
        ge=1,
        le=64,
        description="Number of independent Rust MOO islands explored in parallel before merging the archive.",
        json_schema_extra=knob("Island count", "Strategy"),
    )
    polish_max_passes: int = Field(
        default=50,
        ge=0,
        le=1000,
        description="Maximum local-improvement passes applied to each archive solution after the main search.",
        json_schema_extra=knob("Polish passes", "Strategy"),
    )
    greedy_seed_count: int = Field(
        default=3,
        ge=0,
        le=1000,
        description="How many initial individuals are built with greedy seeding before random fill.",
        json_schema_extra=knob("Greedy seed count", "Strategy"),
    )
    stagnation_kick_patience: int = Field(
        default=15,
        ge=0,
        le=5000,
        description="Generations without archive improvement before stronger mutation and crossover are applied.",
        json_schema_extra=knob("Stagnation kick", "Strategy"),
    )
    crossover_rate: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Probability of crossover when producing offspring in the Rust MOO search.",
        json_schema_extra=knob("Crossover rate", "Strategy"),
    )
    # Defaults to the maximum so every job has a mandatory hard stop even when
    # the client omits it; normal jobs converge long before this, so results
    # stay deterministic in practice.
    time_limit_ms: int | None = Field(
        default=600000,
        ge=100,
        le=600000,
        description=(
            "Hard wall-clock budget for the optimizer in milliseconds. When "
            "exceeded, evolution and polishing stop early and the best result "
            "found so far is returned. Trades same-seed reproducibility for latency."
        ),
        json_schema_extra=knob("Time limit (ms)", "Strategy"),
    )

    max_result_variants: int = Field(
        default=10,
        ge=1,
        le=MAX_RESULT_VARIANTS,
        description="Maximum number of solution variants returned by the selected solver.",
        json_schema_extra=knob("Result variants", "Solver output"),
    )

    # mix_balancer only (the brute-force two-team engine behind pickup mixes).
    # Deliberately without a ``knob`` block: the tournament config drawer renders
    # the editable fields, and these two would be dead controls there --
    # ``tournament_balancer`` never reads them.
    mix_comfort_tilt: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description=(
            "Mix trade-off between rank balance and role comfort. 0 weighs only "
            "how evenly the two teams' ranks split, 1 only how many players got "
            "a preferred role; 0.5 reproduces the engine's own defaults."
        ),
    )
    mix_rules: MixRules = Field(
        default_factory=MixRules,
        description="Mix soft rules (lane matchup) and their weights; formats a rule does not fit ignore it.",
    )
    # Not a setting: every run overwrites it with its format's lanes, like ``role_mask``.
    lane_layout: tuple[int, ...] = Field(
        default=(),
        description="Per-team lane sizes of the run's team format; empty when the format has no lanes",
    )

    # Rating normalization
    rating_scale_ceiling: int = Field(
        default=3500,
        ge=100,
        le=10000,
        description=(
            "Canonical max rating. Input ratings are linearly scaled so the "
            "observed maximum maps to this value before optimization. Keeps "
            "gap-penalty thresholds and weight calibration dataset-independent."
        ),
    )


def apply_config_overrides(config: AlgorithmConfig, overrides: Mapping[str, typing.Any]) -> AlgorithmConfig:
    """Apply a normalized override blob onto ``config``, in place.

    Plain assignment for every knob but ``role_settings``, whose overrides are
    partial: ``{"role_settings": {"tank": {"impact": 2.0}}}`` moves tank's impact
    and leaves its line weights -- and every other role -- where they were.
    """
    for key, value in overrides.items():
        if key == "role_settings":
            merged = dict(config.role_settings)
            for code, partial in value.items():
                merged[code] = merged.get(code, NEUTRAL_ROLE_SETTINGS).model_copy(update=partial)
            config.role_settings = merged
        elif key == "open_slot_settings":
            config.open_slot_settings = config.open_slot_settings.model_copy(update=value)
        elif key == "mix_rules":
            config.mix_rules = MixRules.model_validate(value)
        else:
            setattr(config, key, value)
    return config
