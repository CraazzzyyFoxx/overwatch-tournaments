"""Draft-domain value types: no I/O, no algorithm, no orchestration.

Every dataclass the draft domain passes between its rules/services lives
here — mirrors ``domain/balancer/entities.py``'s role for the balancing
engine. Kept out of ``src/schemas/`` deliberately: those are pydantic wire
contracts for the RPC boundary; several types below (``DraftSnapshot``,
``DraftResult``) hold live ORM rows and would force pydantic's
``arbitrary_types_allowed`` (defeating validation) or premature ORM->dict
flattening before a caller decided which fields the wire response needs.

Producing modules re-import the names they use so every existing
``<module>.<Type>`` access — from other draft files, ``rpc/draft.py``, and
tests — keeps resolving unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from shared.core.enums import HeroClass
from shared.domain.roster import PlayerRoster
from shared.models.balancer.draft import DraftPick, DraftPlayer, DraftTeam

__all__ = (
    "DEFAULT_ROLE_IMPACT",
    "DraftAssignment",
    "DraftFeasibilityReport",
    "DraftFeasibilityState",
    "DraftPickOption",
    "DraftResult",
    "DraftSlot",
    "DraftSnapshot",
    "EligiblePlayer",
    "FitConfig",
    "FitPlayer",
    "FitResult",
    "PoolSeat",
    "RoleEditPreview",
    "RoleEditResult",
    "SlotDecision",
    "SlotDeficit",
)


# --- feasibility (domain/draft/feasibility.py) ------------------------------


@dataclass(frozen=True)
class EligiblePlayer:
    player_id: int
    playable_roles: frozenset[HeroClass]


@dataclass(frozen=True)
class DraftAssignment:
    player_id: int
    team_id: int
    # A roster slot code, so ``flex`` is expressible; see
    # ``feasibility._remaining_capacity`` for how a role code that no longer
    # has room falls back to a free flex slot.
    slot_code: str


@dataclass(frozen=True)
class DraftSlot:
    team_id: int
    slot_code: str
    ordinal: int


@dataclass(frozen=True)
class SlotDeficit:
    slot_code: str
    unmatched_slots: int
    eligible_players: int


@dataclass(frozen=True)
class DraftFeasibilityReport:
    is_feasible: bool
    total_open_slots: int
    matched_slots: int
    unmatched_slots: tuple[DraftSlot, ...]
    slot_deficits: tuple[SlotDeficit, ...]
    blocking_player_ids: tuple[int, ...]
    reason_code: str | None = None


@dataclass(frozen=True)
class DraftPickOption:
    player_id: int
    role: HeroClass
    is_safe: bool
    reason_code: str | None
    unmatched_slots: tuple[DraftSlot, ...] = ()
    blocking_player_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class DraftFeasibilityState:
    team_ids: tuple[int, ...]
    slot_targets: dict[str, int]
    players: tuple[EligiblePlayer, ...]
    assignments: tuple[DraftAssignment, ...]


@dataclass(frozen=True)
class DraftSnapshot:
    """One consistent read of a session's rows plus their resolved rosters.

    Loaded once per request and shared by every step that needs the session
    contents (role counts, fit construction, feasibility state) instead of each
    step re-querying the same rows. ``rosters`` is keyed by ``DraftPlayer.id``
    and comes from the one engine (``shared.services.roster``) -- no step
    derives a role or a rank for itself.
    """

    teams: tuple[DraftTeam, ...]
    players: tuple[DraftPlayer, ...]
    picks: tuple[DraftPick, ...]
    rosters: Mapping[int, PlayerRoster]

    def roster(self, player_id: int) -> PlayerRoster | None:
        return self.rosters.get(player_id)


# --- seeding (domain/draft/rules.py) -----------------------------------------


@dataclass(frozen=True)
class PoolSeat:
    """One seat a seed creates: a pool registration, and whether it captains.

    All a seed carries. Roles, ranks, sub-role, flex and division are NOT
    copied: the draft reads them from the registration through the engine, so
    there is nothing here to go stale.
    """

    registration_id: int
    draft_position: int | None = None
    team_name: str | None = None


# --- pick selection (domain/draft/rules.py) ----------------------------------


@dataclass(frozen=True)
class DraftResult:
    pick: DraftPick
    next_pick: DraftPick | None
    completed: bool
    blocked_reason: str | None = None


@dataclass(frozen=True)
class SlotDecision:
    """What a pick resolves to against the roster shape.

    ``role`` is the role the pick is scored and matched as; ``recorded_role`` is
    what lands in ``DraftPick.target_role`` -- ``None`` on a role-less roster,
    where a role would be a value the shape gives no meaning to.
    """

    role: HeroClass
    recorded_role: str | None


# --- role edits (domain/draft/rules.py) --------------------------------------


@dataclass(frozen=True)
class RoleEditPreview:
    before: DraftFeasibilityReport
    after: DraftFeasibilityReport


@dataclass(frozen=True)
class RoleEditResult:
    player_id: int
    role: HeroClass
    player_version: int
    committed: bool
    preview: RoleEditPreview


# --- autopick fit scoring (domain/draft/fit.py) ------------------------------

# Role-impact weights — mirror native/tournament_balancer/src/lib.rs (tank 1.4 / dps 1.0 / support 1.1).
DEFAULT_ROLE_IMPACT: dict[HeroClass, float] = {
    HeroClass.tank: 1.4,
    HeroClass.damage: 1.0,
    HeroClass.support: 1.1,
}


@dataclass(frozen=True)
class FitPlayer:
    player_id: int
    #: The player's strongest playable role -- what they are worth with no role
    #: context (a role-less roster, or the tie-break in a scarce-role choice).
    rank_value: int
    playable_roles: frozenset[HeroClass]
    preference_order: tuple[HeroClass, ...] = ()
    is_flex: bool = False
    user_id: int | None = None
    #: Per-role ranks over PLAYABLE roles only, straight from the engine. No
    #: fallback: a role the player carries no rank on is not playable, so it is
    #: never scored -- ``best`` is only reached for a role-less slot.
    rank_by_role: Mapping[HeroClass, int] = field(default_factory=dict)

    def rank_for(self, role: HeroClass) -> int:
        return self.rank_by_role.get(role, self.rank_value)


@dataclass(frozen=True)
class FitConfig:
    role_impact: Mapping[HeroClass, float] = field(default_factory=lambda: dict(DEFAULT_ROLE_IMPACT))
    discomfort_weight: float = 1.0
    # Large enough that role-need dominates raw fit when filling scarce roles.
    role_need_bonus: float = 1_000_000.0


@dataclass(frozen=True)
class FitResult:
    player_id: int
    role: HeroClass
    fit_score: float
    breakdown: dict[str, float]
