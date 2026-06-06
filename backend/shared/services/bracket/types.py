from dataclasses import dataclass, field

__all__ = (
    "Pairing",
    "AdvancementEdge",
    "BracketSkeleton",
)


@dataclass(frozen=True)
class AdvancementEdge:
    """Describes how a result of ``source_local_id`` feeds into
    ``target_local_id`` within the same bracket skeleton.

    ``local_id`` values are skeleton-local (0-based); the bracket engine
    consumer must translate them to real DB encounter IDs when persisting
    the resulting ``EncounterLink`` rows.
    """

    source_local_id: int
    target_local_id: int
    role: str  # "winner" | "loser"
    target_slot: str  # "home" | "away"


@dataclass(frozen=True)
class Pairing:
    """A single match pairing between two teams."""

    home_team_id: int | None
    away_team_id: int | None
    round_number: int
    name: str = ""
    local_id: int = 0  # Position in the pairings list (bracket-local identity)


@dataclass(frozen=True)
class BracketSkeleton:
    """Complete bracket structure with all pairings and advancement edges."""

    pairings: list[Pairing]
    total_rounds: int
    advancement_edges: list[AdvancementEdge] = field(default_factory=list)
    bye_team_id: int | None = None
