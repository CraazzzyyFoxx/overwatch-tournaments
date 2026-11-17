"""One scoring engine for every encounter: a duel series and an FFA lobby alike.

Three questions, all answered by the organizer's own formulas over N teams:

* what one game pays a team -- ``game_formula`` over the rule's columns plus
  ``place``, ``place_pts``, ``teams`` and ``win``;
* whether the encounter is over -- ``end_formula`` over ``best_of``, ``games``
  and ``max_wins``, asked after every confirmed game;
* whether a captain's claim about an unconfirmed series can be true at all --
  :func:`series_claim_errors`.

Pure: no session, no ORM rows, no ``eval``. The result writer validates with it,
the standings rank with it and the lobby read renders with it, so the table a
viewer sees and the rows advancement reads are the same arithmetic by
construction. A series is not a special case here: "one point per map won" is
the ``wins`` preset's game formula, nothing more.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, cast

from shared.domain.ffa_formula import END_VARIABLES, Formula, compile_formula, round_half_up

if TYPE_CHECKING:  # pragma: no cover - typing only, the domain never imports models
    from shared.models.encounter import ScoringRule

__all__ = (
    "DEFAULT_COLUMN_KEY",
    "DEFAULT_COLUMN_LABEL",
    "DEFAULT_FORMULA",
    "FFA_MAX_COLUMNS",
    "FFA_MAX_LOBBY_SIZE",
    "FFA_STAT_MAX",
    "GAME_POINTS_DIGITS",
    "PLACEMENT_VARIABLES",
    "POINTS_END_FORMULA",
    "STANDING_DIGITS",
    "WINS_END_FORMULA",
    "WINS_RULES",
    "EncounterOutcome",
    "FfaResultError",
    "GameLine",
    "ScoringColumn",
    "ScoringRules",
    "SeriesClaim",
    "TeamTotals",
    "compile_rules",
    "encounter_ended",
    "evaluate_encounter",
    "game_points",
    "normalize_game_lines",
    "resolve_placements",
    "series_claim_errors",
    "team_totals",
)

#: Toornament's cap on one FFA match; a lobby past it is a data-entry mistake.
FFA_MAX_LOBBY_SIZE = 100
#: A dialog with more inputs than this is a spreadsheet, not a result form.
FFA_MAX_COLUMNS = 10
#: The biggest value a game may record: past it the number is a typo.
FFA_STAT_MAX = 1_000_000_000.0
#: What a stage that configured nothing scores: one column of raw score, paid
#: one for one. The label is stored data the UI shows verbatim, so it is the
#: stage editor's own "Score only" preset label, not a locale's word.
DEFAULT_COLUMN_KEY = "score"
DEFAULT_COLUMN_LABEL = "Score"
DEFAULT_FORMULA = DEFAULT_COLUMN_KEY
#: Float noise must not become a false inequality in a tiebreak.
GAME_POINTS_DIGITS = 4
#: The precision every standings tiebreak (Buchholz, median Buchholz) is stored and compared at: finer
#: digits are float noise or an opposition too close to call, so the next tiebreaker decides.
STANDING_DIGITS = 3
#: The variables that read a team's place: a game formula naming one needs every
#: place entered by hand.
PLACEMENT_VARIABLES: frozenset[str] = frozenset({"place", "place_pts"})
#: A series is decided by wins, and it is over once every position is
#: played or one side is past half (a drawn map pays no win but burns a game).
#: The same two strings the ``enclayer01`` revision writes into every rule row.
WINS_END_FORMULA = "games >= best_of or max_wins * 2 > best_of"
#: A lobby plays its whole card; points decide, not wins.
POINTS_END_FORMULA = "games >= best_of"


class FfaResultError(ValueError):
    """An invalid game result, carrying the machine-readable ``code``.

    Named for the ``ffa_result_*`` codes it carries: those are the API contract
    the result dialog underlines, so the exception tracks them, not the module.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ScoringColumn:
    """One value the organizer records per team per game."""

    key: str
    label: str
    #: False = the value is the organizer's business: not in the public table
    #: and not in the public API answer.
    public: bool = True
    #: Which way this column ranks when a tiebreak sums it.
    better: Literal["higher", "lower"] = "higher"


@dataclass(frozen=True, slots=True)
class ScoringRules:
    """A compiled ``encounter.scoring_rule`` row: how an encounter is scored."""

    preset: Literal["wins", "points"]
    columns: tuple[ScoringColumn, ...]
    #: Points for 1st, 2nd, ... place, read by the game formula as ``place_pts``.
    #: A place past the end scores 0.
    placement_points: tuple[float, ...]
    game_formula: Formula
    end_formula: Formula

    @property
    def requires_placement(self) -> bool:
        """Must every team's place be entered by hand?

        It is a question about the formula, never a separate flag: a flag could
        drift away from the rule it describes.
        """
        return bool(self.game_formula.names & PLACEMENT_VARIABLES)

    @property
    def column_keys(self) -> tuple[str, ...]:
        return tuple(column.key for column in self.columns)


def compile_rules(rule: ScoringRule) -> ScoringRules:
    """Compile one stored rule row. Corrupt data raises, it never scores zero.

    Both formulas were validated on write, so a row that does not compile here
    is hand-edited: it must stop the caller, not quietly pay everybody nothing.
    """
    columns = tuple(_column(item) for item in rule.columns or ())
    return ScoringRules(
        # The ``ck_scoring_rule_preset`` check is what keeps this a Literal.
        preset=cast(Literal["wins", "points"], rule.preset),
        columns=columns,
        placement_points=tuple(float(points) for points in rule.placement_points or ()),
        game_formula=compile_formula(rule.game_formula, [column.key for column in columns]),
        end_formula=compile_formula(rule.end_formula, (), variables=END_VARIABLES),
    )


#: The ``wins`` preset compiled once: one point per game won outright, over a
#: best-of card. Every duel's rule row is this (``enclayer01.wins_rule``), so a
#: caller that cannot reach its row -- the live room asking whether another map
#: is due -- may ask this instead. A caller holding the row compiles THAT.
WINS_RULES = ScoringRules(
    preset="wins",
    columns=(),
    placement_points=(),
    game_formula=compile_formula("win", ()),
    end_formula=compile_formula(WINS_END_FORMULA, (), variables=END_VARIABLES),
)


def _column(item: Mapping[str, Any]) -> ScoringColumn:
    """One jsonb column object. ``better`` defaults to higher-is-better: a row
    written without it must rank, not crash a read."""
    return ScoringColumn(
        key=str(item["key"]),
        label=str(item["label"]),
        public=bool(item.get("public", True)),
        better="lower" if item.get("better") == "lower" else "higher",
    )


@dataclass(frozen=True, slots=True)
class GameLine:
    """One team's result in one game: the row the engine is handed."""

    encounter_team_id: int
    #: The raw head-to-head score of a duel map, when the discipline has one.
    #: Places are derived from it when none were entered.
    score: int | None
    placement: int | None
    #: What was entered for this team in this game, by column key.
    values: Mapping[str, float]


# ── one game ─────────────────────────────────────────────────────────────────


def resolve_placements(rules: ScoringRules, lines: Sequence[GameLine]) -> dict[int, int]:
    """Every team's place in one game, best first, equal results sharing a place.

    Three sources, in order: the places the organizer entered, the raw scores a
    duel map recorded (higher is better), and -- for a lobby that enters neither
    -- what the CURRENT game formula pays with no place to read.

    Derived on every read rather than stored: the formula may be edited while
    the stage runs, and a place frozen under the retired one would contradict
    the points printed next to it. A formula that reads the place never meets
    such a game: the write demands every place under it.
    """
    if not lines:
        return {}
    if all(line.placement is not None for line in lines):
        return {line.encounter_team_id: int(cast(int, line.placement)) for line in lines}
    if any(line.score is not None for line in lines):
        return _rank({line.encounter_team_id: float(line.score or 0) for line in lines})
    return _rank(_evaluate(rules, lines, {}))


def game_points(rules: ScoringRules, lines: Sequence[GameLine]) -> dict[int, float]:
    """What one game pays each team, by the rule's game formula."""
    return _evaluate(rules, lines, resolve_placements(rules, lines))


def _rank(values: Mapping[int, float]) -> dict[int, int]:
    """Competition ranking, best value first: 10, 7, 7, 3 -> 1, 2, 2, 4."""
    places: dict[int, int] = {}
    place = 0
    previous: float | None = None
    for index, (team_id, value) in enumerate(sorted(values.items(), key=lambda pair: (-pair[1], pair[0])), 1):
        if value != previous:
            place, previous = index, value
        places[team_id] = place
    return places


def _evaluate(rules: ScoringRules, lines: Sequence[GameLine], placements: Mapping[int, int]) -> dict[int, float]:
    """The formula over every line of one game. A missing place reads as 0."""
    teams = float(len(lines))
    # A shared first place is nobody's win: two teams level on a map have not
    # won it, which is exactly what a drawn duel map is.
    sole_first = sum(1 for place in placements.values() if place == 1) == 1
    points: dict[int, float] = {}
    for line in lines:
        place = placements.get(line.encounter_team_id, 0)
        values: dict[str, float] = {key: float(value) for key, value in line.values.items()}
        values["place"] = float(place)
        values["place_pts"] = _placement_points(rules, place)
        values["teams"] = teams
        values["win"] = 1.0 if place == 1 and sole_first else 0.0
        points[line.encounter_team_id] = round_half_up(rules.game_formula.evaluate(values), GAME_POINTS_DIGITS)
    return points


def _placement_points(rules: ScoringRules, place: int) -> float:
    return rules.placement_points[place - 1] if 1 <= place <= len(rules.placement_points) else 0.0


# ── one encounter ────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class EncounterOutcome:
    """What an encounter's confirmed games add up to."""

    ended: bool
    #: Games counted -- every confirmed one, draws included.
    games: int
    totals: Mapping[int, float]
    #: Games won outright. A shared first place is nobody's win.
    wins: Mapping[int, int]
    #: Equal totals share a place: 10, 7, 7, 3 -> 1, 2, 2, 4.
    placements: Mapping[int, int]


def evaluate_encounter(
    rules: ScoringRules,
    *,
    best_of: int,
    team_ids: Sequence[int],
    games: Sequence[Sequence[GameLine]],
) -> EncounterOutcome:
    """Score one encounter's confirmed games, oldest first.

    ``team_ids`` seeds a zero row for every active seat: the standing is the
    roster, not the results, so a team that has not played yet still appears.

    The end condition is asked after every game and the first game it holds
    after is where the encounter ended; the games after it are an over-played
    series the organizer still owns, so they are counted, not dropped.
    """
    totals: dict[int, float] = dict.fromkeys(dict.fromkeys(team_ids), 0.0)
    wins: dict[int, int] = dict.fromkeys(totals, 0)
    ended = False
    for played, lines in enumerate(games, 1):
        placements = resolve_placements(rules, lines)
        for team_id, points in _evaluate(rules, lines, placements).items():
            totals[team_id] = totals.get(team_id, 0.0) + points
        first = [team_id for team_id, place in placements.items() if place == 1]
        if len(first) == 1:
            wins[first[0]] = wins.get(first[0], 0) + 1
        ended = ended or encounter_ended(rules, best_of=best_of, games=played, max_wins=max(wins.values(), default=0))
    # Summing already-rounded games still drifts (0.1 + 0.2); a total that a
    # tiebreak compares must not differ by 1e-13 from an equal one.
    totals = {team_id: round_half_up(value, GAME_POINTS_DIGITS) for team_id, value in totals.items()}
    return EncounterOutcome(
        ended=ended,
        games=len(games),
        totals=totals,
        wins=wins,
        placements=_rank(totals),
    )


def encounter_ended(rules: ScoringRules, *, best_of: int, games: int, max_wins: int) -> bool:
    """Is the encounter over after ``games`` confirmed games?

    Public because a caller holding only the tally -- the live room asking
    whether another map is due -- must ask the SAME rule the final standing is
    settled by, not a second copy of "best of N" spelled out in Python.
    """
    return bool(
        rules.end_formula.evaluate({"best_of": float(best_of), "games": float(games), "max_wins": float(max_wins)})
    )


# ── a captain's claim ────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class SeriesClaim:
    """What a captain says the finished series ended on.

    ``wins`` and ``placements`` are ``None`` when the report form does not ask
    for them -- a lobby's card, where points alone decide.
    """

    games_played: int
    totals: Mapping[int, float]
    wins: Mapping[int, int] | None
    placements: Mapping[int, int] | None


def series_claim_errors(
    rules: ScoringRules,
    *,
    best_of: int,
    team_ids: Sequence[int],
    confirmed_games: Sequence[Sequence[GameLine]],
    claim: SeriesClaim,
) -> list[str]:
    """Every way this claim contradicts the games already on record.

    A claim covers games nobody entered, so most of it cannot be recomputed --
    only bounded. What CAN be checked: the claim names the encounter's teams, it
    does not claim fewer games than are confirmed or more than the card holds,
    the end condition holds on it and did NOT already hold earlier (a 3:0 in a
    Bo3 never happened), its wins are at least the confirmed ones, and -- when
    every claimed game is confirmed -- its totals are the computed ones.
    """
    errors: list[str] = []
    teams = set(dict.fromkeys(team_ids))
    claimed: list[Mapping[int, Any] | None] = [claim.totals, claim.wins, claim.placements]
    if any(set(mapping) != teams for mapping in claimed if mapping is not None):
        errors.append("series_claim_teams")
    confirmed = len(confirmed_games)
    if not confirmed <= claim.games_played <= best_of:
        errors.append("series_claim_games_played")

    max_wins = max(claim.wins.values(), default=0) if claim.wins else 0
    if not encounter_ended(rules, best_of=best_of, games=claim.games_played, max_wins=max_wins):
        errors.append("series_claim_not_final")
    # The kindest ordering of the unseen games is the one that ends latest, so
    # the fewest wins the claim forces after ``played`` games is what is asked:
    # a team claiming W wins over G games had at least W - (G - played) of them.
    if any(
        encounter_ended(rules, best_of=best_of, games=played, max_wins=max(0, max_wins - (claim.games_played - played)))
        for played in range(1, claim.games_played)
    ):
        errors.append("series_claim_unreachable")

    outcome = evaluate_encounter(rules, best_of=best_of, team_ids=team_ids, games=confirmed_games)
    if (
        "win" in rules.game_formula.names
        and claim.wins is not None
        and any(claim.wins.get(team_id, 0) < won for team_id, won in outcome.wins.items())
    ):
        errors.append("series_claim_wins")
    if claim.games_played == confirmed and any(
        round_half_up(float(claim.totals.get(team_id, 0.0)), GAME_POINTS_DIGITS) != points
        for team_id, points in outcome.totals.items()
    ):
        errors.append("series_claim_mismatch")
    return errors


# ── entering a lobby's game ──────────────────────────────────────────────────


def normalize_game_lines(
    lines: Iterable[GameLine],
    participant_ids: Iterable[int],
    rules: ScoringRules,
) -> tuple[GameLine, ...]:
    """Validate one game; return its lines, best place first, every place set."""
    expected = set(participant_ids)
    given = list(lines)
    keys = set(rules.column_keys)
    seen: set[int] = set()
    for item in given:
        if item.encounter_team_id not in expected:
            raise FfaResultError("ffa_result_unknown_team", f"Team {item.encounter_team_id} is not in this lobby")
        if item.encounter_team_id in seen:
            raise FfaResultError("ffa_result_duplicate_team", f"Team {item.encounter_team_id} is listed twice")
        seen.add(item.encounter_team_id)
        _check_values(item, keys)
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
        derived = resolve_placements(rules, given)
        given = [
            GameLine(
                encounter_team_id=item.encounter_team_id,
                score=item.score,
                placement=derived[item.encounter_team_id],
                values=item.values,
            )
            for item in given
        ]
        return tuple(sorted(given, key=_order))

    size = len(given)
    if any(place < 1 or place > size for place in placements):
        raise FfaResultError("ffa_result_invalid_placement", f"Places must be between 1 and {size}")
    if rules.requires_placement and sorted(placements) != list(range(1, size + 1)):
        raise FfaResultError("ffa_result_invalid_placement", "Each place from 1 to N must be taken exactly once")
    return tuple(sorted(given, key=_order))


def _order(line: GameLine) -> tuple[int, int]:
    return (line.placement or 0, line.encounter_team_id)


def _check_values(line: GameLine, keys: set[str]) -> None:
    """Exactly the rule's columns, each a finite number in range."""
    for key, value in line.values.items():
        if key not in keys:
            raise FfaResultError(
                "ffa_result_unknown_stat", f"Team {line.encounter_team_id}: this stage has no column `{key}`"
            )
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= FFA_STAT_MAX
        ):
            raise FfaResultError(
                "ffa_result_invalid_stat",
                f"Team {line.encounter_team_id}: `{key}` must be a number between 0 and {FFA_STAT_MAX:.0f}",
            )
    absent = sorted(keys - set(line.values))
    if absent:
        raise FfaResultError("ffa_result_missing_stat", f"Team {line.encounter_team_id}: no value for {absent}")


# ── a lobby's table ──────────────────────────────────────────────────────────


@dataclass(slots=True)
class TeamTotals:
    """One row of a lobby's table: what every confirmed game added up to."""

    team_id: int
    games: int = 0
    points: float = 0.0
    #: Games finished in 1st place, a SHARED 1st included -- the table's "wins"
    #: column, not :attr:`EncounterOutcome.wins`, which counts outright wins.
    wins: int = 0
    #: Every column of the rule summed, zero for a team that has not played.
    stats: dict[str, float] = field(default_factory=dict)
    best_placement: int | None = None
    #: Place in the latest game this team has a result in.
    last_placement: int | None = None


def team_totals(
    team_ids: Iterable[int],
    games: Sequence[Sequence[GameLine]],
    rules: ScoringRules,
) -> dict[int, TeamTotals]:
    """Sum confirmed games, oldest first, into one row per team.

    ``team_ids`` seeds a zero row for every participant: the table is the
    roster, not the results, so a team that has not played yet still appears.
    """
    keys = rules.column_keys

    def blank(team_id: int) -> TeamTotals:
        return TeamTotals(team_id=team_id, stats=dict.fromkeys(keys, 0.0))

    totals = {team_id: blank(team_id) for team_id in team_ids}
    for game in games:
        placements = resolve_placements(rules, game)
        points = _evaluate(rules, game, placements)
        for item in game:
            row = totals.setdefault(item.encounter_team_id, blank(item.encounter_team_id))
            row.games += 1
            row.points += points[item.encounter_team_id]
            for key, value in item.values.items():
                row.stats[key] = row.stats.get(key, 0.0) + float(value)
            place = placements.get(item.encounter_team_id)
            if place is not None:
                row.wins += place == 1
                row.best_placement = place if row.best_placement is None else min(row.best_placement, place)
                row.last_placement = place
    # Summing already-rounded games still drifts (0.1 + 0.2); a total that a
    # tiebreak compares must not differ by 1e-13 from an equal one.
    for row in totals.values():
        row.points = round_half_up(row.points, GAME_POINTS_DIGITS)
        row.stats = {key: round_half_up(value, GAME_POINTS_DIGITS) for key, value in row.stats.items()}
    return totals
