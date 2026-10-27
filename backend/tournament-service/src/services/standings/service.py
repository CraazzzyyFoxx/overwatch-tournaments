import types
import typing
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

import sqlalchemy as sa
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.strategy_options import _AbstractLoad

from shared import models
from shared.core import enums, utils
from shared.core.enums import StageType
from shared.domain.encounter_scoring import GameLine, ScoringRules, TeamTotals, compile_rules, team_totals
from shared.domain.tournament_utils import (
    completed_encounters_in_finished_rounds as _shared_completed_encounters_in_finished_rounds,
)
from shared.domain.tournament_utils import is_completed_encounter, sort_bracket_matches
from shared.repository import EncounterRepository, StandingRepository, TeamRepository, TournamentRepository
from src import schemas
from src.domain.bracket.swiss import SwissThresholds
from src.services.bracket.swiss_state import bye_counts_by_scope, stopped_scopes
from src.services.encounter.ffa import ffa_encounter_service

GROUP_STAGE_TYPES = {StageType.ROUND_ROBIN, StageType.SWISS}
ELIMINATION_STAGE_TYPES = {
    StageType.SINGLE_ELIMINATION,
    StageType.DOUBLE_ELIMINATION,
}
FFA_STAGE_TYPES = {StageType.FFA_LEAGUE}
DEFAULT_STAGE_MAX_ROUNDS = 5

RULE_PRESET_DEFAULTS: dict[str, list[str]] = {
    "challonge_round_robin": [
        "points",
        "head_to_head",
        "median_buchholz",
        "match_wins",
        "score_differential",
    ],
    "challonge_swiss": [
        "points",
        "median_buchholz",
        "buchholz",
        "match_wins",
        "score_differential",
    ],
    "bracket_default": [
        "points",
        "head_to_head",
        "median_buchholz",
        "score_differential",
        "match_wins",
    ],
    # The stage's own headline column is spliced in by ``_tiebreak_order``: it
    # is not a fixed metric name, it depends on what the organizer configured.
    "ffa_default": [
        "points",
        "ffa_game_wins",
        "ffa_last_placement",
    ],
}

#: A tiebreak by the sum of one stage column: ``ffa_stat:kills``. The key after
#: the prefix is an organizer's column key, so it is validated against the
#: stage, not against a fixed list.
FFA_STAT_PREFIX = "ffa_stat:"


#: Every metric ``_metric_value`` can actually score. A stage's configured order
#: is filtered against this: an unknown string would silently rank every team
#: equal (``return 0``), which reads as "the tiebreaker did nothing" instead of
#: "the tiebreaker does not exist".
KNOWN_TIEBREAK_METRICS = frozenset(
    {
        "points",
        "match_wins",
        "head_to_head",
        "buchholz",
        "median_buchholz",
        "score_differential",
        "map_differential",
        "wins_as_higher_stage_specific_metric",
        "ffa_game_wins",
        "ffa_best_placement",
        "ffa_last_placement",
    }
)


@dataclass
class RankedStageTeam:
    team_id: int
    matches: int = 0
    wins: int = 0
    draws: int = 0
    loses: int = 0
    points: float = 0.0
    opponents: list[int] = field(default_factory=list)
    buchholz: float = 0.0
    median_buchholz: float = 0.0
    head_to_head: int = 0
    score_differential: int = 0
    #: FFA only: every stage column summed, already oriented so that more is
    #: better, plus the placement metrics below.
    ffa_stats: dict[str, float] = field(default_factory=dict)
    ffa_best_placement: int | None = None
    ffa_last_placement: int | None = None
    #: Position of the head of this team's tie cluster, ``None`` when it is not
    #: tied. Teams sharing a value were equal on every configured metric; their
    #: relative order is the team-id fallback, not earned. A pinned team is never
    #: in a cluster: its place was decided, not tied.
    tie_group: int | None = None


def _entity_requested(in_entities: list[str], entity: str) -> bool:
    return entity in in_entities or any(item.startswith(f"{entity}.") for item in in_entities)


def standing_entities(in_entities: list[str]) -> list[_AbstractLoad]:
    entities: list[_AbstractLoad] = []
    stage_entity = sa.orm.selectinload(models.Standing.stage)
    stage_item_entity = sa.orm.selectinload(models.Standing.stage_item)
    entities.append(stage_entity)
    entities.append(stage_item_entity)

    if "tournament" in in_entities:
        entities.append(sa.orm.selectinload(models.Standing.tournament))
    if _entity_requested(in_entities, "team"):
        team_entity = sa.orm.selectinload(models.Standing.team)
        entities.append(team_entity)
        entities.extend(TeamRepository.team_entities(utils.prepare_entities(in_entities, "team"), team_entity))
    return entities


@dataclass(frozen=True, slots=True)
class Seat:
    """One participation as the stage table reads it."""

    team_id: int
    slot: int
    score: float
    placement: int | None


@dataclass(frozen=True, slots=True)
class StageEncounter:
    """One encounter of a stage, flattened for the ranking engine.

    The bracket position lives in ``tournament.bracket_encounter`` and the
    result on the participations, not on the ``tournament.encounter`` row.
    Assembled once by :meth:`StandingsService.load_stage_encounters` so the
    ranking below stays a pure function of plain data, which the Swiss pairing
    preview and the tests also build by hand.
    """

    id: int
    round: int
    stage_id: int | None
    stage_item_id: int | None
    completed: bool
    #: The LIVE seats, in slot order.
    seats: tuple[Seat, ...]
    #: An upper-round encounter every link into which carries a LOSING place
    #: (``encounter_link.source_position > 1``): a third-place match. It decides
    #: 3rd and 4th, so it is never the final however high its round.
    third_place: bool = False

    @property
    def is_duel(self) -> bool:
        """Two seats: the only shape ``score_differential`` and head-to-head
        are defined for. A wider encounter is not given an invented home side
        so the metric can be computed anyway."""
        return len(self.seats) == 2

    def places(self) -> dict[int, int]:
        """Each seat's place, best first, equal results sharing a place.

        ``encounter.team.placement`` is what the single result writer decided,
        so it is the answer whenever it is there. A completed encounter without
        one -- a Challonge import of a row nobody re-scored -- falls back to
        competition ranking by score, which is the same rule the engine's own
        ``_rank`` applies.
        """
        if self.seats and all(seat.placement is not None for seat in self.seats):
            return {seat.team_id: typing.cast(int, seat.placement) for seat in self.seats}
        places: dict[int, int] = {}
        place, previous = 0, None
        for index, seat in enumerate(sorted(self.seats, key=lambda one: (-one.score, one.slot)), 1):
            if seat.score != previous:
                place, previous = index, seat.score
            places[seat.team_id] = place
        return places

    def winner(self) -> int | None:
        """The team that finished alone in first, or ``None`` for a draw."""
        firsts = [team_id for team_id, place in self.places().items() if place == 1]
        return firsts[0] if len(firsts) == 1 else None

    @property
    def status(self) -> enums.EncounterStatus:
        """What ``shared.domain.tournament_utils`` asks of an encounter.

        Those helpers are the ONE definition of "counts toward standings" and
        of "is this round closed"; they read ``.status`` and ``.id``, so the
        flattened row answers both rather than forking the predicate here.
        """
        return enums.EncounterStatus.COMPLETED if self.completed else enums.EncounterStatus.OPEN


def _rounds(encounters: typing.Sequence[StageEncounter]) -> dict[int, int]:
    """The playable set keyed by id, as ``shared.domain.tournament_utils`` wants
    it: an encounter with an empty seat is not playable and is left out."""
    return {
        encounter.id: encounter.round
        for encounter in encounters
        if all(seat.team_id is not None for seat in encounter.seats) and encounter.seats
    }


def _completed_encounters_in_finished_rounds(
    encounters: typing.Sequence[StageEncounter],
) -> list[StageEncounter]:
    """Ignore partially completed playable rounds for standings purposes."""
    return _shared_completed_encounters_in_finished_rounds(encounters, _rounds(encounters))


def _assign_final_round_placements(
    encounters: typing.Sequence[StageEncounter],
    data: dict[int, dict[str, float | int]],
) -> None:
    """Hand out 1st/2nd from the bracket's structural final, 3rd/4th from a third-place match.

    The final is the highest positive round that *exists*, not the highest one
    already played: the latter hands out two firsts and two seconds the moment
    both semi-finals are done while the final is still open. Placements are
    assigned only once every encounter of that round is completed. For double
    elimination the lazily created Grand Final Reset lands in GF+1 and so
    becomes the final as soon as it exists. A third-place match is left out of
    that round -- it may share it -- and places its own seats once completed.
    """
    positive = [encounter for encounter in encounters if encounter.round > 0 and not encounter.third_place]
    if positive:
        final_round = max(encounter.round for encounter in positive)
        final_matches = [encounter for encounter in positive if encounter.round == final_round]
        if all(is_completed_encounter(encounter) for encounter in final_matches):
            _place_match(final_matches, data, best=1)
    _place_match(
        [encounter for encounter in encounters if encounter.third_place and is_completed_encounter(encounter)],
        data,
        best=3,
    )


def _place_match(
    matches: typing.Sequence[StageEncounter],
    data: dict[int, dict[str, float | int]],
    *,
    best: int,
) -> None:
    """The winner of each match takes ``best``, everyone else ``best + 1``; a drawn match places no one."""
    for match in matches:
        winner = match.winner()
        if winner is None:
            continue
        data[winner]["placement"] = best
        for seat in match.seats:
            if seat.team_id != winner:
                data[seat.team_id]["placement"] = best + 1


def _stage_max_rounds(stage: models.Stage) -> int:
    raw_value = getattr(stage, "max_rounds", DEFAULT_STAGE_MAX_ROUNDS)
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return DEFAULT_STAGE_MAX_ROUNDS
    return max(1, value)


def _swiss_scope_completed(total: int, completed: int, max_round: int, max_rounds: int) -> bool:
    return total > 0 and completed == total and max_round >= max_rounds


def _rule_profile(stage: models.Stage) -> str:
    if stage.ranking_preset:
        return stage.ranking_preset
    if stage.stage_type == StageType.FFA_LEAGUE:
        return "ffa_default"
    if stage.stage_type == StageType.SWISS:
        return "challonge_swiss"
    if stage.stage_type == StageType.ROUND_ROBIN:
        return "challonge_round_robin"
    return "bracket_default"


def normalize_tiebreak_order(
    metrics: typing.Iterable[typing.Any], *, ffa_columns: typing.Sequence[str] = ()
) -> list[str]:
    """The order the engine will actually apply, from whatever was configured.

    The stored order's own sequence is honoured verbatim, including where it
    puts ``points``: every preset already leads with it, and hoisting it would
    override an explicit organizer choice. What this does fix are the two things
    a stored list can say that mean nothing:

    - unknown metrics are dropped: ``_metric_value`` scores them 0 for every
      team, which is indistinguishable from a tiebreaker that never fires;
    - duplicates collapse to their first occurrence -- a second pass over one
      metric can never separate teams the first pass left equal.

    ``ffa_stat:<key>`` is known only while the stage still has that column:
    deleting a column must not leave a tiebreaker that scores every team 0.

    An organizer's fixed place is not a metric: it is a ``StandingPin``, applied
    after this order has ranked the table (:func:`apply_pins`).
    """
    columns = {f"{FFA_STAT_PREFIX}{key}" for key in ffa_columns}
    ordered: list[str] = []
    for metric in metrics:
        if not isinstance(metric, str) or (metric not in KNOWN_TIEBREAK_METRICS and metric not in columns):
            continue
        if metric not in ordered:
            ordered.append(metric)
    return ordered


def stage_rules(stage: models.Stage) -> ScoringRules:
    """The stage's compiled ``encounter.scoring_rule`` -- the same row every
    encounter of the stage points at, so the table and the cards agree by
    construction."""
    return compile_rules(stage.scoring_rule)


def _tiebreak_order(stage: models.Stage, *, rules: ScoringRules | None = None) -> list[str]:
    """``rules`` is passed by the FFA builder, which already compiled them.

    Without them only the column keys are read off the rule row: the standings read asks this too, and compiling
    both formulas there just to list the keys was wasted work.
    """
    if rules is not None:
        columns = rules.column_keys
    elif stage.stage_type == StageType.FFA_LEAGUE:
        columns = tuple(str(column["key"]) for column in stage.scoring_rule.columns or ())
    else:
        columns = ()
    if stage.tiebreak_order is not None:
        normalized = normalize_tiebreak_order(stage.tiebreak_order, ffa_columns=columns)
        # A stored list with nothing the engine knows would rank by team id alone.
        if normalized:
            return normalized
    profile = _rule_profile(stage)
    preset = RULE_PRESET_DEFAULTS.get(profile, RULE_PRESET_DEFAULTS["bracket_default"])
    if profile == "ffa_default" and columns:
        # The stage's first column is its headline stat: "most kills wins the
        # tie" is what an organizer means by an unconfigured FFA league.
        preset = [*preset[:2], f"{FFA_STAT_PREFIX}{columns[0]}", *preset[2:]]
    return normalize_tiebreak_order(preset, ffa_columns=columns)


def _scoring(stage: models.Stage, tournament: models.Tournament) -> tuple[float, float, float]:
    """Points per win/draw/loss: the stage's own where it set one, else the tournament's."""
    return (
        tournament.win_points if stage.win_points is None else stage.win_points,
        tournament.draw_points if stage.draw_points is None else stage.draw_points,
        tournament.loss_points if stage.loss_points is None else stage.loss_points,
    )


#: Stands in for "this team has no placement yet" so the negated placement
#: metrics sort it below every real place instead of above first place.
_NO_PLACEMENT = 10**9


def _metric_value(team: RankedStageTeam, metric: str) -> float | int:
    if metric == "points":
        return team.points
    if metric == "match_wins":
        return team.wins
    if metric == "head_to_head":
        return team.head_to_head
    # Buchholz hundredths are noise (custom scoring / bye points): round to 0.1
    # so near-equal opposition falls through to the next tiebreaker instead.
    if metric == "buchholz":
        return round(team.buchholz, 1)
    if metric == "median_buchholz":
        return round(team.median_buchholz, 1)
    if metric in {"score_differential", "map_differential"}:
        return team.score_differential
    if metric == "wins_as_higher_stage_specific_metric":
        return team.wins
    if metric == "ffa_game_wins":
        return team.wins
    if metric.startswith(FFA_STAT_PREFIX):
        # Already oriented by ``_ranking_stats``; a team with no value for the
        # column reads as 0, which is what "has not played" sums to anyway.
        return team.ffa_stats.get(metric[len(FFA_STAT_PREFIX) :], 0.0)
    # Lower place is better and the sort is descending: negate, with "never
    # played" ranking below every real place.
    if metric == "ffa_best_placement":
        return -(team.ffa_best_placement or _NO_PLACEMENT)
    if metric == "ffa_last_placement":
        return -(team.ffa_last_placement or _NO_PLACEMENT)
    return 0


def _sort_ranked_teams(
    teams: list[RankedStageTeam],
    *,
    tiebreak_order: list[str],
) -> list[RankedStageTeam]:
    ordered = list(teams)
    # Lowest-priority key first: the metric loop below is applied in reverse, so
    # this decides only teams every configured metric left equal. Without it the
    # order of two identical teams is whatever order they were first seen in
    # (encounter iteration), which is not stable across recalculations -- and
    # ``position`` feeds playoff seeding, so an unstable pair silently moves a
    # team between the upper and lower bracket.
    ordered.sort(key=lambda team: team.team_id)
    for metric in reversed(tiebreak_order):
        ordered.sort(key=lambda team: _metric_value(team, metric), reverse=True)
    return ordered


def assign_tie_groups(
    ordered: typing.Sequence[RankedStageTeam],
    *,
    tiebreak_order: typing.Sequence[str],
    pinned: typing.Collection[int] = (),
) -> None:
    """Mark runs of adjacent teams no configured metric could separate.

    ``ordered`` is the final table order, so a run's head is its first place. A
    team in ``pinned`` is never part of a run -- its place was set by hand, which
    is exactly what resolves a tie -- and it splits the teams around it.
    """

    def key(team: RankedStageTeam) -> tuple:
        if team.team_id in pinned:
            return ("pinned", team.team_id)
        return tuple(_metric_value(team, metric) for metric in tiebreak_order)

    for team in ordered:
        team.tie_group = None
    start = 0
    for index in range(1, len(ordered) + 1):
        if index < len(ordered) and key(ordered[index]) == key(ordered[start]):
            continue
        if index - start > 1:
            head_position = start + 1
            for team in ordered[start:index]:
                team.tie_group = head_position
        start = index


#: A table with no pins: the default of every stage builder.
_EMPTY: typing.Mapping[int, int] = types.MappingProxyType({})


def _pin_seats(pins: typing.Mapping[int, int], size: int) -> dict[int, int]:
    """Place -> team for every pin, each at its own place inside ``1..size``.

    Pins are distinct and in range as stored; this only keeps that true when the
    table shrank under them (a team left the group). Order is kept: a pin is
    pushed below an earlier one it collides with, then the tail is pulled back
    up inside the table, so the last pinned team ends on the last place rather
    than past it.
    """
    ordered = sorted(pins.items(), key=lambda item: (item[1], item[0]))
    places: list[int] = []
    for _team_id, wanted in ordered:
        places.append(max(wanted, places[-1] + 1 if places else 1))
    ceiling = size
    for index in range(len(places) - 1, -1, -1):
        places[index] = min(places[index], ceiling)
        ceiling = places[index] - 1
    return {place: team_id for place, (team_id, _wanted) in zip(places, ordered, strict=True)}


def apply_pins(
    ranked: typing.Sequence[tuple[int, int]],
    pins: typing.Mapping[int, int],
) -> list[tuple[int, int, bool]]:
    """Seat pinned teams at their place; everyone else fills the rest in order.

    ``ranked`` is one table as the engine ranked it: ``(team_id, position)`` in
    table order, position 0 meaning "not ranked yet" (a playoff team that has not
    played). ``pins`` maps team to its fixed place; pins of teams not in the
    table are ignored. Returns ``(team_id, position, is_pinned)`` in final order.

    Unpinned teams keep their computed order, and adjacent unpinned teams that
    shared a computed place keep sharing it -- a playoff's "5th-8th" stays one
    place, under the first free seat of the run. An unpinned, unranked team stays
    at 0 and takes no seat. With no pins this returns ``ranked`` unchanged.

    A bracket mid-way ranks only the teams it eliminated, from the bottom up: the
    seats above its first ranked place are held for the teams still alive, so a
    semi loser keeps 3rd while the final is unplayed instead of closing up to 1st.
    """
    table_pins = {team_id: pins[team_id] for team_id, _position in ranked if team_id in pins}
    free = [(team_id, position) for team_id, position in ranked if team_id not in table_pins and position > 0]
    first = min((position for _team_id, position in ranked if position > 0), default=1)
    # A pinned team still alive already takes one of the held seats.
    alive_pinned = sum(1 for team_id, position in ranked if team_id in table_pins and position <= 0)
    held: list[tuple[int | None, int]] = [(None, place) for place in range(1, first - alive_pinned)]
    free = held + free
    size = len(table_pins) + len(free)
    seats = _pin_seats(table_pins, size)

    output: list[tuple[int, int, bool]] = []
    upcoming = iter(free)
    previous: tuple[int, int] | None = None  # (computed, final) of the unpinned team one seat up
    for place in range(1, size + 1):
        if place in seats:
            output.append((seats[place], place, True))
            previous = None
            continue
        team_id, computed = next(upcoming)
        position = previous[1] if previous is not None and previous[0] == computed else place
        if team_id is not None:
            output.append((team_id, position, False))
        previous = (computed, position)
    output.extend((team_id, 0, False) for team_id, position in ranked if team_id not in table_pins and position <= 0)
    return output


def _pin_group_table(
    ordered: list[RankedStageTeam],
    pins: typing.Mapping[int, int],
    *,
    tiebreak_order: list[str],
) -> tuple[list[RankedStageTeam], set[int]]:
    """A ranked group table with its pins applied and its ties re-marked."""
    by_id = {team.team_id: team for team in ordered}
    placed = apply_pins([(team.team_id, index) for index, team in enumerate(ordered, 1)], pins)
    final = [by_id[team_id] for team_id, _position, _pinned in placed]
    pinned = {team_id for team_id, _position, is_pinned in placed if is_pinned}
    assign_tie_groups(final, tiebreak_order=tiebreak_order, pinned=pinned)
    return final, pinned


def _calculate_buchholz(
    teams_by_id: dict[int, RankedStageTeam],
) -> None:
    for team in teams_by_id.values():
        opponent_scores = [
            teams_by_id[opponent_id].points for opponent_id in team.opponents if opponent_id in teams_by_id
        ]
        team.buchholz = float(sum(opponent_scores))
        if len(opponent_scores) > 2:
            trimmed = sorted(opponent_scores)[1:-1]
            team.median_buchholz = float(sum(trimmed))
        else:
            team.median_buchholz = float(sum(opponent_scores))


def _calculate_head_to_head(
    teams_by_id: dict[int, RankedStageTeam],
    encounters: typing.Sequence[StageEncounter],
) -> None:
    """Wins between teams level on points. Two-seat encounters only: "who beat
    whom" has no meaning for a lobby where three teams met at once."""
    points_buckets: dict[float, set[int]] = defaultdict(set)
    for team in teams_by_id.values():
        points_buckets[team.points].add(team.team_id)

    for team_ids in points_buckets.values():
        if len(team_ids) < 2:
            continue
        for encounter in encounters:
            if not encounter.is_duel or not team_ids.issuperset(seat.team_id for seat in encounter.seats):
                continue
            winner = encounter.winner()
            if winner is not None:
                teams_by_id[winner].head_to_head += 1


def prepare_teams_for_groups(
    encounters: typing.Sequence[StageEncounter],
    *,
    seed_team_ids: typing.Sequence[int] | None = None,
    bye_counts: dict[int, int] | None = None,
    bye_points: float = 1.0,
    win_points: float = 1.0,
    draw_points: float = 0.5,
    loss_points: float = 0.0,
    tiebreak_order: list[str] | None = None,
) -> list[RankedStageTeam]:
    """Rank one group's teams from the encounters they played.

    A result is a PLACE inside the encounter: the team alone in first won, teams
    sharing first drew, everyone else lost -- for a duel and for a group whose
    encounters seat more than two alike. ``score_differential`` is a difference
    between TWO numbers and is therefore only summed for two-seat encounters.
    """
    completed_encounters = _completed_encounters_in_finished_rounds(encounters)
    team_cache: dict[int, RankedStageTeam] = {}

    for team_id in seed_team_ids or []:
        team_cache.setdefault(team_id, RankedStageTeam(team_id=team_id))

    for encounter in completed_encounters:
        seats = encounter.seats
        for seat in seats:
            team_cache.setdefault(seat.team_id, RankedStageTeam(team_id=seat.team_id))
        places = encounter.places()
        drawn = sum(1 for place in places.values() if place == 1) > 1
        for seat in seats:
            team = team_cache[seat.team_id]
            team.matches += 1
            team.opponents.extend(other.team_id for other in seats if other is not seat)
            if encounter.is_duel:
                opponent = next(other for other in seats if other is not seat)
                team.score_differential += int(seat.score) - int(opponent.score)
            if places[seat.team_id] != 1:
                team.loses += 1
                team.points += loss_points
            elif drawn:
                team.draws += 1
                team.points += draw_points
            else:
                team.wins += 1
                team.points += win_points

    for team_id, bye_count in (bye_counts or {}).items():
        team_cache.setdefault(team_id, RankedStageTeam(team_id=team_id))
        team_cache[team_id].points += max(0, bye_count) * bye_points

    _calculate_buchholz(team_cache)
    _calculate_head_to_head(team_cache, completed_encounters)
    # Normalized here too: a caller passing a raw stage order (tests, the Swiss
    # pairing preview) must rank by the same list the stored standings did.
    order = normalize_tiebreak_order(tiebreak_order or RULE_PRESET_DEFAULTS["bracket_default"])
    ordered = _sort_ranked_teams(list(team_cache.values()), tiebreak_order=order)
    assign_tie_groups(ordered, tiebreak_order=order)
    return ordered


def _participants(encounters: typing.Sequence[StageEncounter]) -> list[int]:
    """Every team that played one of these encounters, in first-seen order."""
    return list(dict.fromkeys(seat.team_id for encounter in encounters for seat in encounter.seats))


def _loser_ids(encounter: StageEncounter) -> list[int]:
    """Everyone this encounter did NOT hand first place to.

    A drawn elimination match has no winner and therefore no loser -- it is a
    result the bracket cannot advance either, which is why nothing here invents
    one from the slot order.
    """
    winner = encounter.winner()
    return [] if winner is None else [seat.team_id for seat in encounter.seats if seat.team_id != winner]


def prepare_teams_for_playoffs_double_elimination(
    encounters: typing.Sequence[StageEncounter],
) -> list[schemas.StandingTeamDataWithRanking]:
    logger.info("Preparing teams for double elimination playoffs")
    completed_encounters = _completed_encounters_in_finished_rounds(encounters)
    participants = _participants(completed_encounters)
    data: dict[int, dict[str, float | int]] = {
        participant: {"win": 0, "lose": 0, "placement": 0} for participant in participants
    }

    _assign_final_round_placements(encounters, data)

    for encounter in completed_encounters:
        winner = encounter.winner()
        if winner is not None:
            data[winner]["win"] += 1
        for loser in _loser_ids(encounter):
            data[loser]["lose"] += 1

    lower_bracket_games: dict[int, list[StageEncounter]] = {}
    # Every team of the bracket, not just those that finished a match: a lower
    # seed can be knocked out before an upper one has played.
    global_placement = len(_participants(encounters))

    for encounter in [encounter for encounter in completed_encounters if encounter.round < 0]:
        lower_bracket_games.setdefault(encounter.round, []).append(encounter)

    for matches in lower_bracket_games.values():
        losers: list[int] = []
        for match in matches:
            losers.extend(_loser_ids(match))

        global_placement -= len(losers) - 1
        for loser in losers:
            data[loser]["placement"] = global_placement
        global_placement -= 1

    output: list[schemas.StandingTeamDataWithRanking] = []
    for team_id, team_data in data.items():
        output.append(
            schemas.StandingTeamDataWithRanking(
                id=team_id,
                wins=int(team_data["win"]),
                loses=int(team_data["lose"]),
                draws=0,
                points=0,
                ranking=team_data["placement"],
                opponents=[],
                matches=int(team_data["win"]) + int(team_data["lose"]),
            )
        )
    return output


def prepare_teams_for_playoffs_single_elimination(
    encounters: typing.Sequence[StageEncounter],
) -> list[schemas.StandingTeamDataWithRanking]:
    logger.info("Preparing teams for single elimination playoffs")
    completed_encounters = _completed_encounters_in_finished_rounds(encounters)
    participants = _participants(completed_encounters)

    data: dict[int, dict[str, float | int]] = {
        participant: {"win": 0, "lose": 0, "placement": 0} for participant in participants
    }
    round_of_loss: dict[int, int | None] = dict.fromkeys(participants)

    for encounter in completed_encounters:
        winner = encounter.winner()
        if winner is not None:
            data[winner]["win"] += 1
        for loser_id in _loser_ids(encounter):
            data[loser_id]["lose"] += 1
            if round_of_loss[loser_id] is None:
                round_of_loss[loser_id] = encounter.round

    valid_rounds = [encounter.round for encounter in completed_encounters if encounter.round > 0]
    if not valid_rounds:
        return [
            schemas.StandingTeamDataWithRanking(
                id=team_id,
                wins=int(data[team_id]["win"]),
                loses=int(data[team_id]["lose"]),
                draws=0,
                points=0,
                ranking=0,
                opponents=[],
                matches=int(data[team_id]["win"]) + int(data[team_id]["lose"]),
            )
            for team_id in data
        ]

    _assign_final_round_placements(encounters, data)

    round_losers: dict[int, list[int]] = defaultdict(list)
    for team_id, match_round in round_of_loss.items():
        if match_round is not None and data[team_id]["placement"] == 0:
            round_losers[match_round].append(team_id)

    # Placed from the bottom, the way the bracket eliminates: a round's losers
    # share the best place none of the teams still alive can take. Counting down
    # from 3rd made quarter-final losers 3rd while the semis were unplayed.
    place = len(_participants(encounters)) + 1
    for match_round in sorted(round_losers):
        place -= len(round_losers[match_round])
        for team_id in round_losers[match_round]:
            data[team_id]["placement"] = place

    output: list[schemas.StandingTeamDataWithRanking] = []
    for team_id, stats in data.items():
        output.append(
            schemas.StandingTeamDataWithRanking(
                id=team_id,
                wins=int(stats["win"]),
                loses=int(stats["lose"]),
                draws=0,
                points=0,
                ranking=stats["placement"],
                opponents=[],
                matches=int(stats["win"]) + int(stats["lose"]),
            )
        )
    return output


PLAYOFF_CALCULATORS: dict[
    StageType,
    Callable[
        [typing.Sequence[StageEncounter]],
        list[schemas.StandingTeamDataWithRanking],
    ],
] = {
    StageType.SINGLE_ELIMINATION: prepare_teams_for_playoffs_single_elimination,
    StageType.DOUBLE_ELIMINATION: prepare_teams_for_playoffs_double_elimination,
}


def _infer_stage_type_from_encounters(
    encounters: typing.Sequence[StageEncounter],
) -> StageType:
    has_negative = any(encounter.round < 0 for encounter in encounters)
    return StageType.DOUBLE_ELIMINATION if has_negative else StageType.SINGLE_ELIMINATION


def _stage_item_team_ids(stage_item: models.StageItem | None) -> list[int]:
    if stage_item is None:
        return []

    team_ids: list[int] = []
    seen: set[int] = set()
    for stage_input in sorted(stage_item.inputs, key=lambda item: item.slot):
        if stage_input.team_id is None or stage_input.team_id in seen:
            continue
        team_ids.append(stage_input.team_id)
        seen.add(stage_input.team_id)
    return team_ids


def rank_group(
    tournament: models.Tournament,
    stage: models.Stage,
    stage_item: models.StageItem | None,
    encounters: typing.Sequence[StageEncounter],
    *,
    bye_counts: typing.Mapping[int, int] = _EMPTY,
) -> list[RankedStageTeam]:
    """One group's ranking on its results, before any pin.

    What the stored table is built from, and what a Swiss round is paired on:
    pairing must read real results, and must read them from the same snapshot
    that found the previous round closed -- never the stored table, which the
    standings job may have ranked a moment before that round's last result.
    """
    win_points, draw_points, loss_points = _scoring(stage, tournament)
    return prepare_teams_for_groups(
        encounters,
        seed_team_ids=_stage_item_team_ids(stage_item),
        bye_counts=dict(bye_counts) if stage.stage_type == StageType.SWISS else {},
        bye_points=win_points if stage.swiss_bye_points is None else stage.swiss_bye_points,
        win_points=win_points,
        draw_points=draw_points,
        loss_points=loss_points,
        tiebreak_order=_tiebreak_order(stage),
    )


def _build_group_stage_standings(
    tournament: models.Tournament,
    stage: models.Stage,
    stage_item: models.StageItem | None,
    encounters: typing.Sequence[StageEncounter],
    *,
    pins: typing.Mapping[int, int] = _EMPTY,
    bye_counts: typing.Mapping[int, int] = _EMPTY,
) -> list[models.Standing]:
    if not encounters and not _stage_item_team_ids(stage_item):
        return []

    tiebreak_order = _tiebreak_order(stage)
    thresholds = SwissThresholds.of(stage) if stage.stage_type == StageType.SWISS else SwissThresholds()
    teams = rank_group(tournament, stage, stage_item, encounters, bye_counts=bye_counts)
    # Pinned after ranking, never inside ``rank_group``: that one also feeds the
    # Swiss pairing, which must pair on real results.
    teams, pinned = _pin_group_table(teams, pins, tiebreak_order=tiebreak_order)

    standings: list[models.Standing] = []
    for position, team in enumerate(teams, 1):
        standings.append(
            models.Standing(
                tournament_id=tournament.id,
                team_id=team.team_id,
                stage_id=stage.id,
                stage_item_id=stage_item.id if stage_item is not None else None,
                position=position,
                overall_position=0,
                matches=team.matches,
                win=team.wins,
                draw=team.draws,
                lose=team.loses,
                points=team.points,
                buchholz=team.median_buchholz,
                full_buchholz=team.buchholz,
                tie_group=team.tie_group,
                tb=team.head_to_head,
                is_pinned=team.team_id in pinned,
                swiss_status=thresholds.status(team.wins + bye_counts.get(team.team_id, 0), team.loses),
                score_differential=team.score_differential,
                stage=stage,
                stage_item=stage_item,
            )
        )
    return standings


def _ranking_stats(row: TeamTotals, rules: ScoringRules) -> dict[str, float]:
    """Column sums oriented so that more is better for every key.

    ``_metric_value`` sorts descending, so a ``better="lower"`` column (deaths,
    penalties) is negated here rather than inside the sort -- exactly what
    ``ffa_last_placement`` does, and for the same reason.
    """
    return {
        column.key: -row.stats.get(column.key, 0.0) if column.better == "lower" else row.stats.get(column.key, 0.0)
        for column in rules.columns
    }


def _build_ffa_stage_standings(
    tournament: models.Tournament,
    stage: models.Stage,
    stage_item: models.StageItem,
    participant_ids: typing.Sequence[int],
    games: typing.Sequence[typing.Sequence[GameLine]],
    *,
    pins: typing.Mapping[int, int] = _EMPTY,
) -> list[models.Standing]:
    """Rank one FFA group: its roster plus every confirmed game of its lobbies.

    The group is the table, so the roster comes from BOTH the seed inputs and
    the teams actually seated in a lobby -- a team moved into a lobby by hand
    still belongs in the standing.
    """
    seed_ids = list(dict.fromkeys([*_stage_item_team_ids(stage_item), *participant_ids]))
    if not seed_ids:
        return []

    rules = stage_rules(stage)
    totals = team_totals(seed_ids, games, rules)
    teams = [
        RankedStageTeam(
            team_id=row.team_id,
            matches=row.games,
            wins=row.wins,
            points=row.points,
            ffa_stats=_ranking_stats(row, rules),
            ffa_best_placement=row.best_placement,
            ffa_last_placement=row.last_placement,
        )
        for row in totals.values()
    ]
    order = _tiebreak_order(stage, rules=rules)
    ordered, pinned = _pin_group_table(_sort_ranked_teams(teams, tiebreak_order=order), pins, tiebreak_order=order)
    return [
        models.Standing(
            tournament_id=tournament.id,
            team_id=team.team_id,
            stage_id=stage.id,
            stage_item_id=stage_item.id,
            position=position,
            overall_position=0,
            matches=team.matches,
            win=team.wins,
            draw=0,
            lose=0,
            points=team.points,
            # Not a Buchholz: app-service and stats-service read ``buchholz IS
            # NULL`` as "playoff row" (Standing.buchholz). An ffa league is a
            # group stage, so its rows must read as group rows.
            buchholz=0.0,
            full_buchholz=None,
            tie_group=team.tie_group,
            tb=None,
            is_pinned=team.team_id in pinned,
            score_differential=None,
            stage=stage,
            stage_item=stage_item,
        )
        for position, team in enumerate(ordered, 1)
    ]


def _build_elimination_stage_standings(
    tournament: models.Tournament,
    stage: models.Stage,
    encounters: typing.Sequence[StageEncounter],
    *,
    pins: typing.Mapping[int, int] = _EMPTY,
) -> list[models.Standing]:
    seed_team_ids: list[int] = []
    seen: set[int] = set()
    for item in sorted(stage.items, key=lambda it: (it.order, it.id)):
        for inp in sorted(item.inputs, key=lambda i: i.slot):
            if inp.team_id is not None and inp.team_id not in seen:
                seed_team_ids.append(inp.team_id)
                seen.add(inp.team_id)

    if not encounters and not seed_team_ids:
        return []

    teams: list[schemas.StandingTeamDataWithRanking] = []
    if encounters:
        stage_type = stage.stage_type or _infer_stage_type_from_encounters(encounters)
        calculator = PLAYOFF_CALCULATORS.get(stage_type, prepare_teams_for_playoffs_single_elimination)
        teams = calculator(encounters)
    by_id = {team.id: team for team in teams}
    ranked = sorted(
        ((team.id, int(team.ranking)) for team in teams),
        key=lambda item: (item[1] <= 0, item[1], item[0]),
    )
    # Teams that have not played any completed match yet get a placeholder row
    # at position 0 -- unless a pin seats them (a team disqualified unplayed).
    ranked.extend((team_id, 0) for team_id in seed_team_ids if team_id not in by_id)

    standings: list[models.Standing] = []
    for team_id, position, is_pinned in apply_pins(ranked, pins):
        team = by_id.get(team_id)
        standings.append(
            models.Standing(
                tournament_id=tournament.id,
                team_id=team_id,
                stage_id=stage.id,
                stage_item_id=None,
                position=position,
                overall_position=position,
                matches=team.matches if team is not None else 0,
                win=team.wins if team is not None else 0,
                draw=team.draws if team is not None else 0,
                lose=team.loses if team is not None else 0,
                points=team.points if team is not None else 0,
                buchholz=None,
                tb=None,
                is_pinned=is_pinned,
                stage=stage,
            )
        )
    return standings


def _sort_for_overall(standings: list[models.Standing], stage_order: dict[int, int]) -> list[models.Standing]:
    """Order rows for the overall table, honouring each stage's own ranking.

    ``position`` was already computed with the stage's configured
    ``tiebreak_order``, so it — not a second, hard-coded points/tb/buchholz
    cascade — decides who is ahead inside a stage. Points/tb/buchholz only
    break ties between equal positions in *different* groups.
    """
    return sorted(
        standings,
        key=lambda standing: (
            stage_order.get(standing.stage_id or 0, 0),
            -standing.position,
            standing.points,
            standing.tb or 0,
            standing.buchholz or 0,
        ),
        reverse=True,
    )


def calculate_overall_positions(
    standings: list[models.Standing],
    stages: list[models.Stage],
) -> list[models.Standing]:
    stage_order = {stage.id: stage.order for stage in stages}

    # A standing with zero completed matches stays at the placeholder 0: ranking
    # it would fabricate a "1st place" from seed/tiebreak order alone. Gated per
    # team/stage, not on reaching a playoff stage, because league tournaments have
    # none and still need overall standings as soon as teams play. A pinned row is
    # the organizer's decision, not a result, so it ranks regardless.
    rankable = [standing for standing in standings if standing.matches > 0 or standing.is_pinned]

    playoff_standings = [
        standing
        for standing in rankable
        if standing.stage is not None and standing.stage.stage_type in ELIMINATION_STAGE_TYPES
    ]
    progressed_team_ids = {standing.team_id for standing in playoff_standings}

    if playoff_standings:
        for standing in playoff_standings:
            standing.overall_position = standing.position

        playoff_team_count = len(progressed_team_ids)

        remaining = _sort_for_overall(
            [standing for standing in rankable if standing.team_id not in progressed_team_ids],
            stage_order,
        )
        next_position = playoff_team_count + 1
        for standing in remaining:
            standing.overall_position = next_position
            next_position += 1
        return standings

    # Rank teams, not participation rows: across consecutive group stages one
    # team owns several standings, and numbering all of them lets a single team
    # occupy two podium places. Only its latest stage row represents its final
    # achievement; the earlier ones stay unranked.
    def stage_rank(standing: models.Standing) -> tuple[int, int]:
        return stage_order.get(standing.stage_id or 0, 0), standing.stage_id or 0

    latest_by_team: dict[int, models.Standing] = {}
    for standing in rankable:
        standing.overall_position = 0
        current = latest_by_team.get(standing.team_id)
        if current is None or stage_rank(standing) > stage_rank(current):
            latest_by_team[standing.team_id] = standing

    remaining = _sort_for_overall(list(latest_by_team.values()), stage_order)
    for position, standing in enumerate(remaining, start=1):
        standing.overall_position = position
    # Return every standing, not just the ranked subset: unrankable (0-match)
    # rows still need to reach the caller's write.
    return standings


def sort_matches(
    matches: typing.Sequence[StageEncounter],
) -> list[StageEncounter]:
    """Sort bracket matches with the shared helper every service uses."""
    return sort_bracket_matches(matches)


#: Everything ``calculate_for_tournament`` walks: stages, their items, and each
#: item's seed inputs.
_STANDINGS_TOURNAMENT_LOAD = (
    selectinload(models.Tournament.stages).selectinload(models.Stage.items).selectinload(models.StageItem.inputs),
)

#: A standing row's identity, the columns of ``uq_standing_tournament_stage_item_team`` within one tournament.
_STANDING_KEY = ("stage_id", "stage_item_id", "team_id")
#: Everything a recalculation writes on a row besides its identity.
_STANDING_VALUES = (
    "position",
    "overall_position",
    "matches",
    "win",
    "draw",
    "lose",
    "points",
    "buchholz",
    "full_buchholz",
    "tie_group",
    "tb",
    "score_differential",
    "is_pinned",
    "swiss_status",
)


@dataclass(slots=True)
class StandingsRecalculation:
    """One recalculation's outcome."""

    #: ``None`` when the tournament is gone.
    tournament: models.Tournament | None
    #: The computed rows (not session-bound).
    standings: list[models.Standing]
    #: Whether anything was written: a standing row or a ``Stage.is_completed`` flag.
    changed: bool
    #: Each group and elimination stage's encounters as they were ranked, by stage id.
    encounters: dict[int, list[StageEncounter]]


class StandingsService:
    def __init__(
        self,
        *,
        standing_repo: StandingRepository = StandingRepository(),
        tournament_repo: TournamentRepository = TournamentRepository(),
        encounter_repo: EncounterRepository = EncounterRepository(),
    ) -> None:
        self.standing_repo = standing_repo
        self.tournament_repo = tournament_repo
        self.encounter_repo = encounter_repo

    async def get_by_tournament(
        self, session: AsyncSession, tournament_id: int, entities: list[str]
    ) -> typing.Sequence[models.Standing]:
        query = (
            self.standing_repo.select()
            .options(*standing_entities(entities))
            .where(sa.and_(models.Standing.tournament_id == tournament_id))
            .order_by(
                models.Standing.overall_position.desc(),
                models.Standing.stage_id.asc().nullslast(),
                models.Standing.stage_item_id.asc().nullslast(),
                models.Standing.position.asc(),
            )
        )
        result = await session.execute(query)
        standings = result.scalars().all()
        logger.debug(f"Retrieved {len(standings)} standings for tournament {tournament_id}")
        return standings

    async def _seats_by_encounter(
        self, session: AsyncSession, encounter_ids: typing.Sequence[int]
    ) -> dict[int, list[Seat]]:
        """The live seats of each encounter, in slot order."""
        seats: defaultdict[int, list[Seat]] = defaultdict(list)
        if not encounter_ids:
            return seats
        rows = await session.execute(
            sa.select(models.EncounterTeam)
            .where(
                models.EncounterTeam.encounter_id.in_(tuple(encounter_ids)),
                models.EncounterTeam.active.is_(True),
                models.EncounterTeam.team_id.is_not(None),
            )
            .order_by(models.EncounterTeam.encounter_id, models.EncounterTeam.slot)
        )
        for row in rows.scalars():
            seats[row.encounter_id].append(
                Seat(team_id=row.team_id, slot=row.slot, score=row.score, placement=row.placement)
            )
        return seats

    async def load_stage_encounters(self, session: AsyncSession, stage_id: int) -> list[StageEncounter]:
        """One stage's encounters, flattened for the ranking engine.

        Three queries for the whole stage: the cards with their bracket positions,
        every live participation of them, and the upper-round cards only losers
        feed (third-place matches). The engine never touches an ORM row
        afterwards, which is what keeps it testable without a database.
        """
        rows = (
            (
                await session.execute(
                    sa.select(models.Encounter, models.BracketEncounter)
                    .join(models.BracketEncounter, models.BracketEncounter.encounter_id == models.Encounter.id)
                    .where(models.BracketEncounter.stage_id == stage_id)
                    .order_by(models.Encounter.id)
                )
            )
            .tuples()
            .all()
        )
        seats = await self._seats_by_encounter(session, [encounter.id for encounter, _position in rows])
        third_place = set(
            await session.scalars(
                sa.select(models.EncounterLink.target_encounter_id)
                .join(
                    models.BracketEncounter,
                    models.BracketEncounter.encounter_id == models.EncounterLink.target_encounter_id,
                )
                .where(models.BracketEncounter.stage_id == stage_id, models.BracketEncounter.round > 0)
                .group_by(models.EncounterLink.target_encounter_id)
                .having(sa.func.min(models.EncounterLink.source_position) > 1)
            )
        )
        return [
            StageEncounter(
                id=encounter.id,
                round=position.round,
                stage_id=position.stage_id,
                stage_item_id=position.stage_item_id,
                completed=is_completed_encounter(encounter),
                seats=tuple(seats.get(encounter.id, ())),
                third_place=encounter.id in third_place,
            )
            for encounter, position in rows
        ]

    async def get_completed_match_history_by_tournament(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> list[tuple[models.Encounter, models.BracketEncounter]]:
        """Completed encounters of *closed* rounds, for the standings history.

        Deliberately the same set the ranking engine counts
        (:func:`_completed_encounters_in_finished_rounds`): the embedded
        ``matches_history`` feeds the FORM column, which sits in the same row as
        W·D·L / points / Buchholz. Serving every completed encounter would run
        FORM a round ahead of its own row — a ``W`` chip with zero wins while the
        rest of its round has not reported.

        Open encounters are selected too (not filtered in SQL): a round is only
        closed if *none* of its playable encounters is still open, which cannot
        be seen from the completed ones alone. Rounds are scoped per
        (stage, stage_item) — the same scope ``_history_for_standing`` slices by
        — so an unfinished round in group A cannot hide group B's results.

        The bracket position rides along: the caller renders the round and the
        scope off it, and an encounter with no position (a scrim, a mix) is not
        part of any stage's history and never enters the join.
        """
        query = (
            sa.select(models.Encounter, models.BracketEncounter)
            .join(models.BracketEncounter, models.BracketEncounter.encounter_id == models.Encounter.id)
            .options(selectinload(models.Encounter.teams))
            .where(models.Encounter.tournament_id == tournament_id)
            .order_by(
                models.BracketEncounter.stage_id.asc().nullslast(),
                models.BracketEncounter.stage_item_id.asc().nullslast(),
                sa.func.abs(models.BracketEncounter.round).asc(),
                models.BracketEncounter.round.desc(),
                models.Encounter.id.asc(),
            )
        )
        rows = (await session.execute(query)).tuples().all()
        by_id = {encounter.id: (encounter, position) for encounter, position in rows}
        by_scope: defaultdict[tuple[int | None, int | None], list[StageEncounter]] = defaultdict(list)
        for encounter, position in rows:
            by_scope[(position.stage_id, position.stage_item_id)].append(
                StageEncounter(
                    id=encounter.id,
                    round=position.round,
                    stage_id=position.stage_id,
                    stage_item_id=position.stage_item_id,
                    completed=is_completed_encounter(encounter),
                    # Off the ``teams`` the query already loaded: the read path renders them too.
                    seats=tuple(
                        Seat(team_id=row.team_id, slot=row.slot, score=row.score, placement=row.placement)
                        for row in sorted(encounter.teams, key=lambda row: row.slot)
                        if row.active and row.team_id is not None
                    ),
                )
            )
        # Groups are keyed by the leading ORDER BY columns and each keeps its
        # rows' relative order, so concatenating them restores the query order.
        return [
            by_id[flat.id]
            for scope_encounters in by_scope.values()
            for flat in _completed_encounters_in_finished_rounds(scope_encounters)
        ]

    async def _write_standings(
        self, session: AsyncSession, tournament_id: int, standings: typing.Sequence[models.Standing]
    ) -> bool:
        """Make the stored table equal ``standings``; ``False`` when it already was and nothing was written.

        Rows are matched on ``uq_standing_tournament_stage_item_team``'s key: a changed row is updated in place, a
        new one inserted, a vanished one deleted. One statement each, all in the caller's transaction, so a reader
        sees the old table or the new one, never a mix. Ids survive a recalculation.
        """
        table = models.Standing
        columns = [getattr(table, name) for name in (*_STANDING_KEY, *_STANDING_VALUES)]
        result = await session.execute(sa.select(table.id, *columns).where(table.tournament_id == tournament_id))
        stored = {tuple(row[1:4]): (row[0], tuple(row[4:])) for row in result}
        inserts: list[dict[str, typing.Any]] = []
        updates: list[dict[str, typing.Any]] = []
        for standing in standings:
            key = tuple(getattr(standing, name) for name in _STANDING_KEY)
            values = {name: getattr(standing, name) for name in _STANDING_VALUES}
            old = stored.pop(key, None)
            if old is None:
                inserts.append({"tournament_id": tournament_id, **dict(zip(_STANDING_KEY, key, strict=True)), **values})
            elif old[1] != tuple(values.values()):
                updates.append({"id": old[0], **values})
        await self.standing_repo.write_diff(
            session,
            delete_ids=[row_id for row_id, _ in stored.values()],
            updates=updates,
            inserts=inserts,
        )
        return bool(stored or updates or inserts)

    async def get_tournament_for_standings(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> models.Tournament | None:
        return await self.tournament_repo.get(session, tournament_id, options=_STANDINGS_TOURNAMENT_LOAD)

    async def recalculate_for_tournament(
        self,
        session: AsyncSession,
        tournament_id: int,
        *,
        commit: bool = True,
    ) -> StandingsRecalculation:
        """Rebuild a tournament's standings atomically: readers never observe a half-written table."""
        tournament = await self.get_tournament_for_standings(session, tournament_id)
        if tournament is None:
            return StandingsRecalculation(tournament=None, standings=[], changed=False, encounters={})
        return await self.calculate_for_tournament(session, tournament, commit=commit)

    async def _update_stage_completion_flags(
        self,
        session: AsyncSession,
        tournament: models.Tournament,
        standings: typing.Sequence[models.Standing],
    ) -> bool:
        """After recalc, flip ``Stage.is_completed`` to match reality.

        A stage is considered completed when every encounter that belongs to it
        has ``status == COMPLETED``. Stages without any encounters are treated
        as not-completed (nothing to finish).

        This powers the admin UI's "Group A — 10/10 done" badge and the
        activate-and-generate warning for downstream playoff stages.

        A Swiss scope is done once its rounds are played and either
        ``max_rounds`` is reached, it ran out of pairings, or its thresholds
        left fewer than two teams undecided (read off ``standings``).

        Returns whether any flag flipped.
        """
        stages = getattr(tournament, "stages", []) or []
        if not stages:
            return False

        stage_ids = [s.id for s in stages]
        counts_result = await session.execute(
            sa.select(
                models.BracketEncounter.stage_id,
                models.BracketEncounter.stage_item_id,
                sa.func.count(models.Encounter.id).label("total"),
                sa.func.sum(
                    sa.case(
                        (
                            models.Encounter.status == enums.EncounterStatus.COMPLETED,
                            1,
                        ),
                        else_=0,
                    )
                ).label("completed"),
                sa.func.coalesce(sa.func.max(models.BracketEncounter.round), 0).label("max_round"),
            )
            .join(models.Encounter, models.Encounter.id == models.BracketEncounter.encounter_id)
            .where(models.BracketEncounter.stage_id.in_(stage_ids))
            .group_by(models.BracketEncounter.stage_id, models.BracketEncounter.stage_item_id)
        )
        rows_by_stage: dict[int, list[tuple[int | None, int, int, int]]] = defaultdict(list)
        for row in counts_result:
            rows_by_stage[row.stage_id].append(
                (
                    getattr(row, "stage_item_id", None),
                    int(row.total or 0),
                    int(row.completed or 0),
                    int(row.max_round or 0),
                )
            )
        stopped = await stopped_scopes(session, [stage.id for stage in stages if stage.stage_type == StageType.SWISS])
        undecided: defaultdict[tuple[int | None, int | None], int] = defaultdict(int)
        for row in standings:
            if row.swiss_status is None:
                undecided[(row.stage_id, row.stage_item_id)] += 1
        flipped = False
        for stage in stages:
            stage_rows = rows_by_stage.get(stage.id, [])
            if stage.stage_type == StageType.SWISS:
                rows_by_item = {
                    stage_item_id: (total, completed, max_round)
                    for stage_item_id, total, completed, max_round in stage_rows
                }
                item_scopes = [
                    (item.id, *rows_by_item.get(item.id, (0, 0, 0))) for item in (getattr(stage, "items", []) or [])
                ]
                extra_scopes = [
                    (None, total, completed, max_round)
                    for stage_item_id, total, completed, max_round in stage_rows
                    if stage_item_id is None
                ]
                scopes = item_scopes or extra_scopes
                thresholds = SwissThresholds.of(stage)
                should_be_completed = bool(scopes) and all(
                    (stage.id, stage_item_id) in stopped
                    or _swiss_scope_completed(total, completed, max_round, _stage_max_rounds(stage))
                    or (
                        bool(thresholds)
                        and total > 0
                        and completed == total
                        and undecided[(stage.id, stage_item_id)] < 2
                    )
                    for stage_item_id, total, completed, max_round in scopes
                )
            else:
                total = sum(row_total for _, row_total, _, _ in stage_rows)
                completed = sum(row_completed for _, _, row_completed, _ in stage_rows)
                should_be_completed = total > 0 and completed == total
            if stage.is_completed != should_be_completed:
                stage.is_completed = should_be_completed
                flipped = True
        return flipped

    async def get_pins_by_table(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> dict[tuple[int, int | None], dict[int, int]]:
        """Every pin of the tournament: ``(stage_id, stage_item_id) -> {team_id: position}``."""
        result = await session.execute(
            sa.select(
                models.StandingPin.stage_id,
                models.StandingPin.stage_item_id,
                models.StandingPin.team_id,
                models.StandingPin.position,
            ).where(models.StandingPin.tournament_id == tournament_id)
        )
        pins: defaultdict[tuple[int, int | None], dict[int, int]] = defaultdict(dict)
        for stage_id, stage_item_id, team_id, position in result.all():
            pins[(stage_id, stage_item_id)][team_id] = position
        return pins

    async def calculate_for_tournament(
        self,
        session: AsyncSession,
        tournament: models.Tournament,
        *,
        commit: bool = True,
    ) -> StandingsRecalculation:
        stages = sorted(getattr(tournament, "stages", []) or [], key=lambda stage: stage.order)
        pins = await self.get_pins_by_table(session, tournament.id)
        byes = await bye_counts_by_scope(session, [stage.id for stage in stages if stage.stage_type == StageType.SWISS])
        all_standings: list[models.Standing] = []
        encounters: dict[int, list[StageEncounter]] = {}

        for stage in stages:
            # Loaded per branch, not up front: an FFA stage ranks from its game
            # results, so fetching its lobbies here would be a query per stage
            # whose rows nothing reads.
            if stage.stage_type in GROUP_STAGE_TYPES:
                stage_encounters = encounters[stage.id] = sort_matches(
                    await self.load_stage_encounters(session, stage.id)
                )
                stage_items = sorted(stage.items, key=lambda item: item.order) if stage.items else []
                if stage_items:
                    for stage_item in stage_items:
                        item_encounters = [
                            encounter for encounter in stage_encounters if encounter.stage_item_id == stage_item.id
                        ]
                        all_standings.extend(
                            _build_group_stage_standings(
                                tournament,
                                stage,
                                stage_item,
                                item_encounters,
                                pins=pins.get((stage.id, stage_item.id), _EMPTY),
                                bye_counts=byes.get((stage.id, stage_item.id), _EMPTY),
                            )
                        )
                else:
                    all_standings.extend(
                        _build_group_stage_standings(
                            tournament,
                            stage,
                            None,
                            stage_encounters,
                            pins=pins.get((stage.id, None), _EMPTY),
                            bye_counts=byes.get((stage.id, None), _EMPTY),
                        )
                    )
            elif stage.stage_type in ELIMINATION_STAGE_TYPES:
                stage_encounters = encounters[stage.id] = sort_matches(
                    await self.load_stage_encounters(session, stage.id)
                )
                all_standings.extend(
                    _build_elimination_stage_standings(
                        tournament, stage, stage_encounters, pins=pins.get((stage.id, None), _EMPTY)
                    )
                )
            elif stage.stage_type in FFA_STAGE_TYPES:
                results = await ffa_encounter_service.load_stage_results(session, stage.id)
                for stage_item in sorted(stage.items or [], key=lambda item: item.order):
                    all_standings.extend(
                        _build_ffa_stage_standings(
                            tournament,
                            stage,
                            stage_item,
                            results.participant_ids(stage_item.id),
                            results.games(stage_item.id),
                            pins=pins.get((stage.id, stage_item.id), _EMPTY),
                        )
                    )

        final_standings = calculate_overall_positions(all_standings, stages)
        changed = await self._write_standings(session, tournament.id, final_standings)
        # Flip Stage.is_completed in the same transaction as the standings write.
        changed = await self._update_stage_completion_flags(session, tournament, final_standings) or changed
        if commit:
            await session.commit()
        else:
            await session.flush()
        logger.info(f"Stage-first standings calculated for tournament {tournament.id} (changed={changed})")
        return StandingsRecalculation(
            tournament=tournament, standings=final_standings, changed=changed, encounters=encounters
        )


standings_service = StandingsService()
