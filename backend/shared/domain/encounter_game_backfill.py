"""Plan the one-time conversion of legacy per-map results into encounter_game rows.

Inputs are the legacy shapes as they exist BEFORE migration ``encgame01``:
``encounter_map_report(encounter_id, map_id, map_index, team_id, …)`` and
``matches.match`` rows with ``source='captain_report'``. Output is a plan the
migration applies verbatim. Rules (spec §13B): explicit ``map_index>0`` is the
position; legacy index 0 / NULL rows are ordered by creation time AFTER every
explicit position, one game per distinct map; the same map twice without a
position is a conflict that aborts the migration; a ``captain_report`` match is
an accepted result, so it confirms its position whatever the surviving reports
say; nothing is guessed.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class EncounterSides:
    home_team_id: int | None
    away_team_id: int | None


@dataclass(frozen=True)
class LegacyReport:
    id: int
    encounter_id: int
    map_id: int
    map_index: int
    team_id: int
    home_score: int
    away_score: int
    created_at: datetime


@dataclass(frozen=True)
class LegacyCaptainMatch:
    id: int
    encounter_id: int
    map_id: int
    map_index: int | None
    home_score: int
    away_score: int
    created_at: datetime


@dataclass
class PlannedGame:
    key: tuple[int, int]  # (encounter_id, position) — the migration maps it to the new id
    encounter_id: int
    position: int
    map_id: int
    state: str
    accepted_home_score: int | None = None
    accepted_away_score: int | None = None
    confirmed_at: datetime | None = None


@dataclass
class BackfillPlan:
    games: list[PlannedGame] = field(default_factory=list)
    report_keys: dict[int, tuple[tuple[int, int], str]] = field(default_factory=dict)
    orphan_report_ids: list[int] = field(default_factory=list)
    deleted_match_ids: list[int] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)


@dataclass
class _Group:
    """Everything the legacy data says about one series position."""

    map_id: int
    reports: dict[str, LegacyReport] = field(default_factory=dict)  # side -> report
    matches: list[LegacyCaptainMatch] = field(default_factory=list)


def plan_games(
    reports: Sequence[LegacyReport],
    captain_matches: Sequence[LegacyCaptainMatch],
    encounters: Mapping[int, EncounterSides],
) -> BackfillPlan:
    """Map legacy per-map rows onto ``encounter_game`` positions.

    Ambiguity is never resolved by guessing: it lands in ``conflicts`` and the
    migration aborts so an operator can set ``map_index`` by hand.
    """
    plan = BackfillPlan()

    # 1. Side resolution. A report whose team is no longer either side of its
    #    encounter (or whose encounter is gone) has no game to belong to.
    sided: dict[int, list[tuple[LegacyReport, str]]] = defaultdict(list)
    for report in reports:
        side = _side_of(report, encounters.get(report.encounter_id))
        if side is None:
            plan.orphan_report_ids.append(report.id)
            continue
        sided[report.encounter_id].append((report, side))

    matches_by_encounter: dict[int, list[LegacyCaptainMatch]] = defaultdict(list)
    for match in captain_matches:
        matches_by_encounter[match.encounter_id].append(match)

    for encounter_id in sorted(set(sided) | set(matches_by_encounter)):
        groups = _group_encounter(
            encounter_id,
            sided.get(encounter_id, ()),
            matches_by_encounter.get(encounter_id, ()),
            plan.conflicts,
        )
        for position in sorted(groups):
            group = groups[position]
            game = _plan_game(encounter_id, position, group, plan.conflicts)
            plan.games.append(game)
            for side, report in group.reports.items():
                plan.report_keys[report.id] = (game.key, side)
            plan.deleted_match_ids.extend(match.id for match in group.matches)

    plan.orphan_report_ids.sort()
    plan.deleted_match_ids.sort()
    return plan


def _side_of(report: LegacyReport, sides: EncounterSides | None) -> str | None:
    if sides is None:
        return None
    if report.team_id == sides.home_team_id:
        return "home"
    if report.team_id == sides.away_team_id:
        return "away"
    return None


def _group_encounter(
    encounter_id: int,
    sided_reports: Sequence[tuple[LegacyReport, str]],
    matches: Sequence[LegacyCaptainMatch],
    conflicts: list[str],
) -> dict[int, _Group]:
    """One ``_Group`` per series position of this encounter."""
    groups: dict[int, _Group] = {}

    # 2. Explicit positions: map_index is the position, verbatim.
    position_maps: dict[int, set[int]] = defaultdict(set)
    for report, side in sided_reports:
        if report.map_index > 0:
            position_maps[report.map_index].add(report.map_id)
    for match in matches:
        if match.map_index is not None and match.map_index > 0:
            position_maps[match.map_index].add(match.map_id)
    for position in sorted(position_maps):
        map_ids = position_maps[position]
        if len(map_ids) > 1:
            conflicts.append(f"encounter {encounter_id}: position {position} names maps {sorted(map_ids)}")
            continue
        groups[position] = _Group(map_id=next(iter(map_ids)))

    explicit_maps = {group.map_id for group in groups.values()}
    max_explicit = max(groups, default=0)

    for report, side in sided_reports:
        if report.map_index > 0 and report.map_index in groups:
            _add_report(encounter_id, report.map_index, groups[report.map_index], report, side, conflicts)
    for match in matches:
        if match.map_index is not None and match.map_index > 0 and match.map_index in groups:
            groups[match.map_index].matches.append(match)

    # 3. Legacy rows: no position of their own, so creation order is the only
    #    evidence. One game per distinct map, in first-seen order, after every
    #    explicit position. A map that reappears once another map has started —
    #    or that an explicit position already claimed — is not orderable.
    legacy: list[tuple[datetime, int, LegacyReport | None, str | None, LegacyCaptainMatch | None]] = []
    for report, side in sided_reports:
        if report.map_index <= 0:
            legacy.append((report.created_at, report.id, report, side, None))
    for match in matches:
        if match.map_index is None or match.map_index <= 0:
            legacy.append((match.created_at, match.id, None, None, match))
    legacy.sort(key=lambda item: (item[0], item[1]))

    legacy_groups: dict[int, _Group] = {}
    order: list[int] = []
    current_map: int | None = None
    twice: set[int] = set()
    for _created, _row_id, report, side, match in legacy:
        map_id = report.map_id if report is not None else match.map_id  # type: ignore[union-attr]
        if map_id in explicit_maps or (map_id != current_map and map_id in legacy_groups):
            if map_id not in twice:
                twice.add(map_id)
                conflicts.append(
                    f"encounter {encounter_id}: legacy rows play map {map_id} twice; set map_index by hand"
                )
            continue
        if map_id not in legacy_groups:
            legacy_groups[map_id] = _Group(map_id=map_id)
            order.append(map_id)
        current_map = map_id
        group = legacy_groups[map_id]
        if report is not None and side is not None:
            if side in group.reports:
                # Two claims from one side for one map with nothing to separate
                # them: the same map was played twice, unpositioned.
                if map_id not in twice:
                    twice.add(map_id)
                    conflicts.append(
                        f"encounter {encounter_id}: legacy rows play map {map_id} twice; set map_index by hand"
                    )
                continue
            group.reports[side] = report
        elif match is not None:
            group.matches.append(match)

    for offset, map_id in enumerate(order, start=1):
        groups[max_explicit + offset] = legacy_groups[map_id]
    return groups


def _add_report(
    encounter_id: int,
    position: int,
    group: _Group,
    report: LegacyReport,
    side: str,
    conflicts: list[str],
) -> None:
    if side in group.reports:
        conflicts.append(f"encounter {encounter_id}: position {position} has two {side} reports")
        return
    group.reports[side] = report


def _plan_game(encounter_id: int, position: int, group: _Group, conflicts: list[str]) -> PlannedGame:
    """4. State from the evidence.

    A ``captain_report`` match IS an accepted result (spec §13B) -- the old
    reconciliation only ever wrote one once a result was agreed -- so wherever
    one exists it confirms the game, whatever the surviving reports say. A lone
    report that disagrees stays attached as that side's claim and changes
    nothing; only BOTH sides agreeing on a different score is a contradiction
    worth aborting for. With no match: agreement confirms, disagreement
    disputes, a lone claim waits.
    """
    game = PlannedGame(
        key=(encounter_id, position),
        encounter_id=encounter_id,
        position=position,
        map_id=group.map_id,
        state="awaiting_result",
    )
    home = group.reports.get("home")
    away = group.reports.get("away")
    agreed: tuple[int, int] | None = None
    if home is not None and away is not None and (home.home_score, home.away_score) == (
        away.home_score,
        away.away_score,
    ):
        agreed = (home.home_score, home.away_score)

    if group.matches:
        match = min(group.matches, key=lambda m: (m.created_at, m.id))
        for other in group.matches:
            if (other.home_score, other.away_score) != (match.home_score, match.away_score):
                conflicts.append(
                    f"encounter {encounter_id}: position {position} has captain matches {match.id} and "
                    f"{other.id} with different scores"
                )
        if agreed is not None and agreed != (match.home_score, match.away_score):
            conflicts.append(
                f"encounter {encounter_id}: position {position} captain match {match.id} says "
                f"{match.home_score}-{match.away_score} but both captains agreed {agreed[0]}-{agreed[1]}"
            )
        game.state = "confirmed"
        game.accepted_home_score = match.home_score
        game.accepted_away_score = match.away_score
        game.confirmed_at = match.created_at
    elif agreed is not None:
        game.state = "confirmed"
        game.accepted_home_score = agreed[0]
        game.accepted_away_score = agreed[1]
        game.confirmed_at = max(home.created_at, away.created_at)  # type: ignore[union-attr]
    elif home is not None and away is not None:
        game.state = "disputed"
    return game
