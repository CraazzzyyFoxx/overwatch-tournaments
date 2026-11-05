"""Per-kind node configs (spec §4.2): what ``flow_node.config`` holds for each kind."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.core.enums import FlowNodeKind, FlowUnit, SubscriptionEnforcementStage

__all__ = (
    "NODE_CONFIG_MODELS",
    "AggregateNodeConfig",
    "AggregateScore",
    "FilterNodeConfig",
    "FormationNodeConfig",
    "LeaderboardNodeConfig",
    "MergeNodeConfig",
    "RegistrationNodeConfig",
    "SplitBucket",
    "SplitNodeConfig",
    "StageNodeConfig",
    "parse_node_config",
)


class _NodeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RegistrationNodeConfig(_NodeConfig):
    check_in: bool = False
    intake: Literal["solo", "team"] = "solo"
    #: Sign-ups are approved on submit instead of waiting for an organizer.
    auto_approve: bool = False
    #: Advisory capacity shown next to the participant count. NOT a limit: registration past it succeeds. None hides it.
    max_participants: int | None = None
    #: Bench size for team registration: extra ``is_substitute`` members per team on top of the roster shape.
    #: Zero disables the bench; a substitute holds no starter slot, so the shape and the lock guarding it stay.
    max_substitutes: int = Field(0, ge=0)
    #: The per-intake decision; the RULE it enforces is the workspace's (``subscriptions.requirement``), resolved
    #: through ``SubscriptionResolver.load_requirement``.
    require_subscription: bool = False
    #: WHEN the requirement bites. Ordered, not a set: ``registration`` implies check-in as well.
    subscription_stage: SubscriptionEnforcementStage = SubscriptionEnforcementStage.check_in
    #: WHO the rule is evaluated against: ``player`` is the anti-smurf per-entrant gate, ``team`` is "the captain
    #: pays": a coverage stamp on the registered team satisfies the requirement for everyone on that roster.
    subscription_scope: Literal["player", "team"] = "player"
    #: Starter-only rank floor/ceiling/spread for team intakes. None means the rule is off; substitutes never count.
    team_rank_min: int | None = None
    team_rank_max: int | None = None
    team_max_rank_spread: int | None = None
    #: Discord nick / snowflake unique across the teams of this intake.
    team_unique_identity: bool = False
    #: Live members must have a Discord identity in ``Workspace.discord_guild_id``; fails closed without a guild.
    team_require_discord_guild: bool = False
    #: Lifts the ``open`` window's ``ends_at`` (and keeps sign-ups open in ``check_in``) so latecomers can be admitted.
    allow_late_registration: bool = False


class FormationNodeConfig(_NodeConfig):
    mode: Literal["balancer", "draft", "registered", "manual"]


class StageNodeConfig(_NodeConfig):
    pass


class MergeNodeConfig(_NodeConfig):
    pass


class LeaderboardNodeConfig(_NodeConfig):
    pass


class FilterNodeConfig(_NodeConfig):
    mode: Literal["top", "range", "per_item_top", "swiss_status", "manual"]
    n: int | None = Field(None, ge=0)
    from_: int | None = Field(None, alias="from", ge=1)
    to: int | None = Field(None, ge=1)
    per_item: dict[int, int] = {}
    swiss_status: Literal["qualified", "eliminated"] | None = None
    manual: list[int] = []

    @model_validator(mode="after")
    def _n_for_top_modes(self) -> FilterNodeConfig:
        if self.mode in ("top", "per_item_top") and self.n is None:
            raise ValueError(f"n is required for mode {self.mode!r}")
        return self


class SplitBucket(_NodeConfig):
    name: str = Field(min_length=1)
    size: int | None = Field(None, ge=1)


class SplitNodeConfig(_NodeConfig):
    buckets: list[SplitBucket] = Field(min_length=1)
    serpentine: bool = False


class AggregateScore(_NodeConfig):
    preset: Literal["stage_points", "placement_table", "formula"]
    table: dict[str, float] = {}
    formula: str | None = None


class AggregateNodeConfig(_NodeConfig):
    unit: FlowUnit
    score: AggregateScore
    mode: Literal["sum_all", "sum_last_n", "sum_best_n", "average"]
    n: int | None = Field(None, ge=1)
    tiebreak: list[Literal["best_places", "last_input"]] = ["best_places", "last_input"]

    @model_validator(mode="after")
    def _n_for_windowed_modes(self) -> AggregateNodeConfig:
        if self.mode in ("sum_last_n", "sum_best_n") and self.n is None:
            raise ValueError(f"n is required for mode {self.mode!r}")
        return self


NODE_CONFIG_MODELS: Mapping[FlowNodeKind, type[BaseModel]] = MappingProxyType(
    {
        FlowNodeKind.REGISTRATION: RegistrationNodeConfig,
        FlowNodeKind.FORMATION: FormationNodeConfig,
        FlowNodeKind.STAGE: StageNodeConfig,
        FlowNodeKind.FILTER: FilterNodeConfig,
        FlowNodeKind.MERGE: MergeNodeConfig,
        FlowNodeKind.SPLIT: SplitNodeConfig,
        FlowNodeKind.AGGREGATE: AggregateNodeConfig,
        FlowNodeKind.LEADERBOARD: LeaderboardNodeConfig,
    }
)


def parse_node_config(kind: FlowNodeKind, raw: Mapping[str, Any]) -> BaseModel:
    """Validate ``raw`` against the kind's model; raises ``pydantic.ValidationError``."""
    return NODE_CONFIG_MODELS[kind].model_validate(dict(raw))
