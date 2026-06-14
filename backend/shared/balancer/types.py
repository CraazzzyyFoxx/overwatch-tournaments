"""Universal domain types for the balancer subsystem.

These types are algorithm-agnostic: any balancer algorithm consumes
``PlayerInput`` and produces ``BalanceOutput``.  Internal algorithm
models (CPAT ``Player``, Genetic ``Player``, etc.) stay private and
are converted to/from these shared types by adapter layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class BalancerRole(StrEnum):
    TANK = "tank"
    DPS = "dps"
    SUPPORT = "support"


class RoleSubtype(StrEnum):
    HITSCAN = "hitscan"
    PROJECTILE = "projectile"
    MAIN_HEAL = "main_heal"
    LIGHT_HEAL = "light_heal"


class PlayerFlag(StrEnum):
    SHOTCALLER = "shotcaller"
    NEWBIE = "newbie"
    TOXIC = "toxic"
    PASSIVE = "passive"
    FLEX = "flex"
    STREAMER = "streamer"


# ---------------------------------------------------------------------------
# Role mask (team composition template)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoleMask:
    """Defines required slots per role in a team composition.

    ``slots`` maps *role code* (e.g. ``"tank"``) to the number of
    players required for that role in one team.
    """

    slots: dict[str, int]

    @property
    def team_size(self) -> int:
        return sum(self.slots.values())

    @classmethod
    def overwatch_5v5(cls) -> RoleMask:
        return cls(slots={"tank": 1, "dps": 2, "support": 2})

    def to_dict(self) -> dict[str, int]:
        return dict(self.slots)

    @classmethod
    def from_dict(cls, data: dict[str, int]) -> RoleMask:
        return cls(slots=data)


# ---------------------------------------------------------------------------
# Algorithm input
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlayerInput:
    """Universal player input for any balancer algorithm."""

    id: str
    name: str
    role_ratings: dict[str, int]
    """role_code -> rank_value (SR)"""
    preferred_roles: list[str]
    """Ordered by priority (index 0 = most preferred)."""
    subclasses: dict[str, str] = field(default_factory=dict)
    """role_code -> subtype (e.g. ``"hitscan"``)"""
    flags: frozenset[str] = field(default_factory=frozenset)
    avoid_player_ids: frozenset[str] = field(default_factory=frozenset)
    is_captain: bool = False
    division_number: int | None = None


# ---------------------------------------------------------------------------
# Algorithm output
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlayerAssignment:
    """One player's assignment in a balanced result."""

    player_id: str
    team_index: int
    role: str
    assigned_rank: int
    discomfort: int


@dataclass(frozen=True)
class BalanceOutput:
    """Result from any balancer algorithm.

    One ``BalanceOutput`` represents a single solution variant.
    Algorithms may return multiple variants (e.g. CPAT returns up to 8).
    """

    variant_number: int
    assignments: list[PlayerAssignment]
    benched_player_ids: list[str]
    objective_score: float
    metrics: dict[str, Any] = field(default_factory=dict)
