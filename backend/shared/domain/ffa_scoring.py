"""FFA lobby scoring: validate one game, pay it by the formula, sum the totals.

Pure: no session, no ORM rows. The result writer validates with it, the
standings builder ranks with it and the lobby read renders with it, so the
table a viewer sees and the ``Standing`` rows advancement reads are the same
arithmetic by construction (docs/plans/2026-09-26-ffa-custom-scoring.md §5).

What a game pays is the organizer's own formula over the organizer's own
columns; nothing here knows what a "kill" is.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from shared.domain.ffa_formula import Formula, compile_formula, round_half_up

__all__ = (
    "DEFAULT_COLUMN_KEY",
    "DEFAULT_COLUMN_LABEL",
    "DEFAULT_FORMULA",
    "FFA_MAX_COLUMNS",
    "FFA_MAX_LOBBY_SIZE",
    "FFA_STAT_MAX",
    "FfaColumn",
    "FfaGameLine",
    "FfaResultError",
    "FfaRules",
    "FfaTeamTotals",
    "ffa_rules",
    "game_points",
    "normalize_game_lines",
    "rank_game",
    "team_totals",
)

#: Toornament's cap on one FFA match; a lobby past it is a data-entry mistake.
FFA_MAX_LOBBY_SIZE = 100
#: A dialog with more inputs than this is a spreadsheet, not a result form.
FFA_MAX_COLUMNS = 10
#: The biggest value a game may record: past it the number is a typo.
FFA_STAT_MAX = 1_000_000_000.0
#: A stage that configured nothing scores exactly what it scored before this
#: feature: one column of raw score, paid one for one.
DEFAULT_COLUMN_KEY = "score"
DEFAULT_COLUMN_LABEL = "Счёт"
DEFAULT_FORMULA = DEFAULT_COLUMN_KEY
#: Float noise must not become a false inequality in a tiebreak (plan §12).
GAME_POINTS_DIGITS = 4


class FfaResultError(ValueError):
    """An invalid game result, carrying the machine-readable ``code``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class FfaColumn:
    """One value the organizer records per team per game."""

    key: str
    label: str
    #: False = the value is the organizer's business: not in the public table
    #: and not in the public API answer.
    public: bool = True
    #: Which way this column ranks when a tiebreak sums it.
    better: Literal["higher", "lower"] = "higher"


@dataclass(frozen=True, slots=True)
class FfaRules:
    columns: tuple[FfaColumn, ...]
    #: Points for 1st, 2nd, ... place, read by the formula as ``place_pts``.
    #: A place past the end scores 0.
    placement_points: tuple[float, ...]
    formula: Formula

    @property
    def requires_placement(self) -> bool:
        """Must every team's place be entered by hand?

        It is a question about the formula, never a separate flag: a flag could
        drift away from the rule it describes.
        """
        return bool(self.formula.names & {"place", "place_pts"})

    @property
    def column_keys(self) -> tuple[str, ...]:
        return tuple(column.key for column in self.columns)


_DEFAULT_COLUMNS = (FfaColumn(key=DEFAULT_COLUMN_KEY, label=DEFAULT_COLUMN_LABEL),)


def ffa_rules(stage: Any | None) -> FfaRules:
    """A stage's scoring from its columns (``Stage.ffa_columns``/``ffa_formula``).

    No stage at all reads as the default block. A stage always carries its own
    columns -- the column default is the score column (plan §3.1) -- so an empty
    list is a legal placement-only league, never "not configured". The columns
    and the formula were validated on write (``FfaScoring``), so a formula that
    does not compile here is corrupt data: it raises rather than silently scoring
    zero.
    """
    if stage is None:
        return FfaRules(
            columns=_DEFAULT_COLUMNS,
            placement_points=(),
            formula=compile_formula(DEFAULT_FORMULA, (DEFAULT_COLUMN_KEY,)),
        )
    columns = tuple(
        FfaColumn(
            key=str(item["key"]),
            label=str(item["label"]),
            public=bool(item.get("public", True)),
            better="lower" if item.get("better") == "lower" else "higher",
        )
        for item in stage.ffa_columns or ()
    )
    return FfaRules(
        columns=columns,
        placement_points=tuple(float(value) for value in stage.ffa_placement_points or ()),
        formula=compile_formula(stage.ffa_formula, [column.key for column in columns]),
    )


@dataclass(frozen=True, slots=True)
class FfaGameLine:
    team_id: int
    placement: int | None
    #: The raw values entered for this team in this game, by column key.
    stats: Mapping[str, float]


def normalize_game_lines(
    lines: Iterable[FfaGameLine],
    participant_ids: Iterable[int],
    rules: FfaRules,
) -> tuple[FfaGameLine, ...]:
    """Validate one game; return its lines, best place first, every place set."""
    expected = set(participant_ids)
    given = list(lines)
    keys = set(rules.column_keys)
    seen: set[int] = set()
    for item in given:
        if item.team_id not in expected:
            raise FfaResultError("ffa_result_unknown_team", f"Team {item.team_id} is not in this lobby")
        if item.team_id in seen:
            raise FfaResultError("ffa_result_duplicate_team", f"Team {item.team_id} is listed twice")
        seen.add(item.team_id)
        _check_stats(item, keys)
    missing = expected - seen
    if missing:
        raise FfaResultError("ffa_result_missing_team", f"No result for teams {sorted(missing)}")

    placements = [item.placement for item in given if item.placement is not None]
    if placements and len(placements) != len(given):
        raise FfaResultError("ffa_result_mixed_placement", "Give a place for every team or for none")
    if not placements:
        if rules.requires_placement:
            raise FfaResultError(
                "ffa_result_placement_required", "This stage scores placement: give every team's place"
            )
        return rank_game(given, rules)

    size = len(given)
    if any(place < 1 or place > size for place in placements):
        raise FfaResultError("ffa_result_invalid_placement", f"Places must be between 1 and {size}")
    if rules.requires_placement and sorted(placements) != list(range(1, size + 1)):
        raise FfaResultError("ffa_result_invalid_placement", "Each place from 1 to N must be taken exactly once")
    return tuple(sorted(given, key=lambda item: (item.placement or 0, item.team_id)))


def _check_stats(line: FfaGameLine, keys: set[str]) -> None:
    """Exactly the stage's columns, each a finite number in range."""
    for key, value in line.stats.items():
        if key not in keys:
            raise FfaResultError("ffa_result_unknown_stat", f"Team {line.team_id}: this stage has no column `{key}`")
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= FFA_STAT_MAX
        ):
            raise FfaResultError(
                "ffa_result_invalid_stat",
                f"Team {line.team_id}: `{key}` must be a number between 0 and {FFA_STAT_MAX:.0f}",
            )
    absent = sorted(keys - set(line.stats))
    if absent:
        raise FfaResultError("ffa_result_missing_stat", f"Team {line.team_id}: no value for {absent}")


def rank_game(lines: Sequence[FfaGameLine], rules: FfaRules) -> tuple[FfaGameLine, ...]:
    """The game's lines with a place on every one, best place first.

    A place the organizer entered is kept as it is. A game with no places --
    what a score-only lobby stores -- is ranked by competition ranking over the
    points the CURRENT formula pays: 10, 7, 7, 3 -> 1, 2, 2, 4. Points, not a
    column: the lobby has several columns and only the formula says how they
    compare.

    Called on every read, not once on write: the formula may be edited while
    the stage runs, and a place derived under the retired one would contradict
    the points printed next to it (plan §5.2). When that formula reads the
    place itself, a missing place pays 0, so the ranking falls back to the
    place-independent part of the formula -- deterministic, ties broken by team.
    """
    if all(item.placement is not None for item in lines):
        return tuple(sorted(lines, key=lambda item: (item.placement or 0, item.team_id)))
    teams = len(lines)
    scored = sorted(
        ((game_points(item, rules, teams), item) for item in lines),
        key=lambda pair: (-pair[0], pair[1].team_id),
    )
    derived: list[FfaGameLine] = []
    placement = 0
    previous: float | None = None
    for index, (points, item) in enumerate(scored, 1):
        if points != previous:
            placement, previous = index, points
        derived.append(FfaGameLine(team_id=item.team_id, placement=placement, stats=item.stats))
    return tuple(derived)


def game_points(line: FfaGameLine, rules: FfaRules, teams: int) -> float:
    """What this team's game pays, by the stage's formula."""
    place = line.placement or 0
    place_points = rules.placement_points[place - 1] if 1 <= place <= len(rules.placement_points) else 0.0
    values: dict[str, float] = {key: float(value) for key, value in line.stats.items()}
    values["place"] = float(place)
    values["place_pts"] = place_points
    values["teams"] = float(teams)
    return round_half_up(rules.formula.evaluate(values), GAME_POINTS_DIGITS)


@dataclass(slots=True)
class FfaTeamTotals:
    team_id: int
    games: int = 0
    points: float = 0.0
    #: Games finished in 1st place, a shared 1st included.
    wins: int = 0
    #: Every column of the stage summed, zero for a team that has not played.
    stats: dict[str, float] = field(default_factory=dict)
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
    keys = rules.column_keys

    def blank(team_id: int) -> FfaTeamTotals:
        return FfaTeamTotals(team_id=team_id, stats=dict.fromkeys(keys, 0.0))

    totals = {team_id: blank(team_id) for team_id in team_ids}
    for game in games:
        teams = len(game)
        for item in game:
            row = totals.setdefault(item.team_id, blank(item.team_id))
            row.games += 1
            row.points += game_points(item, rules, teams)
            for key, value in item.stats.items():
                row.stats[key] = row.stats.get(key, 0.0) + float(value)
            if item.placement is not None:
                row.wins += item.placement == 1
                row.best_placement = (
                    item.placement if row.best_placement is None else min(row.best_placement, item.placement)
                )
                row.last_placement = item.placement
    # Summing already-rounded games still drifts (0.1 + 0.2); a total that a
    # tiebreak compares must not differ by 1e-13 from an equal one.
    for row in totals.values():
        row.points = round_half_up(row.points, GAME_POINTS_DIGITS)
        row.stats = {key: round_half_up(value, GAME_POINTS_DIGITS) for key, value in row.stats.items()}
    return totals
