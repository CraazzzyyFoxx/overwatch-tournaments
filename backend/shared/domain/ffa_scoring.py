"""FFA lobby scoring: validate one game, derive placements, sum per-team totals.

Pure: no session, no ORM rows. The result writer validates with it, the
standings builder ranks with it and the lobby read renders with it, so the table
a viewer sees and the ``Standing`` rows advancement reads are the same
arithmetic by construction (docs/plans/2026-09-24-ffa-encounters.md §5.2-5.3).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

__all__ = (
    "FFA_MAX_LOBBY_SIZE",
    "FfaGameLine",
    "FfaResultError",
    "FfaRules",
    "FfaTeamTotals",
    "game_points",
    "normalize_game_lines",
    "ffa_rules",
    "team_totals",
)

#: Toornament's cap on one FFA match; a lobby past it is a data-entry mistake.
FFA_MAX_LOBBY_SIZE = 100


class FfaResultError(ValueError):
    """An invalid game result, carrying the machine-readable ``code``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class FfaRules:
    #: Points for 1st, 2nd, ... place. A place past the end scores 0; an empty
    #: table means placement carries no points (a score-only lobby).
    placement_points: tuple[float, ...] = ()
    #: Points per unit of raw score: a kill, an elimination, a lap point.
    score_points: float = 1.0

    @property
    def uses_placement(self) -> bool:
        return bool(self.placement_points)


def ffa_rules(stage: Any | None) -> FfaRules:
    """A stage's scoring (``Stage.ffa_placement_points``/``ffa_score_points``).

    No stage at all reads as score-only. The columns were validated on write
    (``FfaScoring``), so this only converts.
    """
    if stage is None:
        return FfaRules()
    return FfaRules(
        placement_points=tuple(float(value) for value in stage.ffa_placement_points or ()),
        score_points=float(stage.ffa_score_points),
    )


@dataclass(frozen=True, slots=True)
class FfaGameLine:
    team_id: int
    placement: int | None
    score: int


def normalize_game_lines(
    lines: Iterable[FfaGameLine],
    participant_ids: Iterable[int],
    rules: FfaRules,
) -> tuple[FfaGameLine, ...]:
    """Validate one game; return its lines, best place first, every place set."""
    expected = set(participant_ids)
    given = list(lines)
    seen: set[int] = set()
    for item in given:
        if item.team_id not in expected:
            raise FfaResultError("ffa_result_unknown_team", f"Team {item.team_id} is not in this lobby")
        if item.team_id in seen:
            raise FfaResultError("ffa_result_duplicate_team", f"Team {item.team_id} is listed twice")
        seen.add(item.team_id)
        if item.score < 0:
            raise FfaResultError("ffa_result_invalid_score", f"Team {item.team_id} has a negative score")
    missing = expected - seen
    if missing:
        raise FfaResultError("ffa_result_missing_team", f"No result for teams {sorted(missing)}")

    placements = [item.placement for item in given if item.placement is not None]
    if placements and len(placements) != len(given):
        raise FfaResultError("ffa_result_mixed_placement", "Give a place for every team or for none")
    if not placements:
        if rules.uses_placement:
            raise FfaResultError(
                "ffa_result_placement_required", "This stage scores placement: give every team's place"
            )
        return _derive_placements(given)

    size = len(given)
    if any(place < 1 or place > size for place in placements):
        raise FfaResultError("ffa_result_invalid_placement", f"Places must be between 1 and {size}")
    if rules.uses_placement and sorted(placements) != list(range(1, size + 1)):
        raise FfaResultError("ffa_result_invalid_placement", "Each place from 1 to N must be taken exactly once")
    return tuple(sorted(given, key=lambda item: (item.placement or 0, item.team_id)))


def _derive_placements(lines: Sequence[FfaGameLine]) -> tuple[FfaGameLine, ...]:
    """Competition ranking by score: 10, 7, 7, 3 -> 1, 2, 2, 4."""
    ordered = sorted(lines, key=lambda item: (-item.score, item.team_id))
    derived: list[FfaGameLine] = []
    placement = 0
    previous: int | None = None
    for index, item in enumerate(ordered, 1):
        if item.score != previous:
            placement, previous = index, item.score
        derived.append(FfaGameLine(team_id=item.team_id, placement=placement, score=item.score))
    return tuple(derived)


def game_points(line: FfaGameLine, rules: FfaRules) -> float:
    placement_part = 0.0
    if line.placement is not None and line.placement <= len(rules.placement_points):
        placement_part = rules.placement_points[line.placement - 1]
    return placement_part + line.score * rules.score_points


@dataclass(slots=True)
class FfaTeamTotals:
    team_id: int
    games: int = 0
    points: float = 0.0
    #: Games finished in 1st place, a shared 1st included.
    wins: int = 0
    #: Raw score summed: total kills, eliminations, lap points.
    score: int = 0
    best_placement: int | None = None
    #: Place in the latest game this team has a result in.
    last_placement: int | None = None


def team_totals(
    team_ids: Iterable[int],
    games: Sequence[Sequence[FfaGameLine]],
    rules: FfaRules,
) -> dict[int, FfaTeamTotals]:
    """Sum confirmed games, oldest first, into one row per team.

    ``team_ids`` seeds a zero row for every participant: the table is the
    roster, not the results, so a team that has not played yet still appears.
    """
    totals = {team_id: FfaTeamTotals(team_id=team_id) for team_id in team_ids}
    for game in games:
        for item in game:
            row = totals.setdefault(item.team_id, FfaTeamTotals(team_id=item.team_id))
            row.games += 1
            row.points += game_points(item, rules)
            row.score += item.score
            if item.placement is not None:
                row.wins += item.placement == 1
                row.best_placement = (
                    item.placement if row.best_placement is None else min(row.best_placement, item.placement)
                )
                row.last_placement = item.placement
    return totals
