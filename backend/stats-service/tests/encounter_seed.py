"""Seed an encounter with its participations for the real-Postgres read-model suites.

An encounter seats ``slot_count`` participations (``encounter.team``); its result
is the ``score`` / ``placement`` those rows carry, so a test states the series
score per team and the placements follow (competition ranking, equal scores
share a place).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa

from shared import models
from shared.core import enums
from shared.models.encounter import Encounter, EncounterGame, EncounterGameTeam, EncounterTeam, ScoringRule
from shared.models.tournament import Team, Tournament
from shared.models.tournament.bracket_encounter import BracketEncounter

WINS_END = "games >= best_of or max_wins * 2 > best_of"


async def seed_scoring_rule(session: Any, workspace_id: int, preset: str = "wins") -> int:
    rule = ScoringRule(workspace_id=workspace_id, preset=preset, game_formula="win", end_formula=WINS_END)
    session.add(rule)
    await session.flush()
    return rule.id


async def seed_encounter(
    session: Any,
    tournament: Tournament,
    scoring_rule_id: int,
    seats: Sequence[tuple[Team | None, float]],
    *,
    name: str,
    completed: bool = True,
    round_: int | None = 1,
    **columns: Any,
) -> Encounter:
    """One encounter, one active participation per ``(team, score)`` in slot order.

    ``completed`` writes the confirmed result (admin source, placements from the
    scores); otherwise the encounter is open and nobody has a place yet.
    """
    encounter = Encounter(
        workspace_id=tournament.workspace_id,
        discipline=tournament.discipline,
        tournament_id=tournament.id,
        scoring_rule_id=scoring_rule_id,
        name=name,
        slot_count=len(seats),
        status=enums.EncounterStatus.COMPLETED if completed else enums.EncounterStatus.OPEN,
        result_status=enums.EncounterResultStatus.CONFIRMED if completed else enums.EncounterResultStatus.NONE,
        result_source="admin" if completed else None,
        **columns,
    )
    session.add(encounter)
    await session.flush()
    if round_ is not None:
        session.add(BracketEncounter(encounter_id=encounter.id, tournament_id=tournament.id, round=round_))
    scores = [score for _team, score in seats]
    for slot, (team, score) in enumerate(seats, 1):
        session.add(
            EncounterTeam(
                encounter_id=encounter.id,
                tournament_id=tournament.id,
                slot=slot,
                team_id=team.id if team is not None else None,
                name=team.name if team is not None else f"Seat {slot}",
                score=score,
                placement=1 + sum(1 for other in scores if other > score) if completed else None,
            )
        )
    await session.flush()
    return encounter


def _duel_rows(
    *,
    encounter_id: int,
    tournament_id: int,
    workspace_id: int,
    scoring_rule_id: int,
    name: str,
    seats: Sequence[tuple[int, float]],
    round_: int = 1,
    **columns: Any,
) -> list[Any]:
    """ORM rows of one completed encounter for a SYNC fixture: ``(team_id, score)`` per seat, slot order.

    Placements follow the scores (competition ranking), the result is the confirmed ``admin`` one.
    """
    scores = [score for _team_id, score in seats]
    rows: list[Any] = [
        Encounter(
            id=encounter_id,
            workspace_id=workspace_id,
            discipline="overwatch",
            tournament_id=tournament_id,
            scoring_rule_id=scoring_rule_id,
            name=name,
            slot_count=len(seats),
            status=enums.EncounterStatus.COMPLETED,
            result_status=enums.EncounterResultStatus.CONFIRMED,
            result_source="admin",
            **columns,
        ),
        BracketEncounter(encounter_id=encounter_id, tournament_id=tournament_id, round=round_),
    ]
    rows.extend(
        EncounterTeam(
            encounter_id=encounter_id,
            tournament_id=tournament_id,
            slot=slot,
            team_id=team_id,
            name=f"Seat {slot}",
            score=score,
            placement=1 + sum(1 for other in scores if other > score),
        )
        for slot, (team_id, score) in enumerate(seats, 1)
    )
    return rows


def add_duel(db: Any, **kwargs: Any) -> None:
    """Add one completed encounter to a SYNC session (see :func:`_duel_rows`): the encounter is flushed
    before its bracket row and seats, which carry no relationship to order them by."""
    encounter, *rest = _duel_rows(**kwargs)
    db.add(encounter)
    db.flush()
    db.add_all(rest)
    db.flush()


async def seed_confirmed_games(
    session: Any, encounter: Encounter, games: Sequence[Sequence[int]], *, scored: bool = False
) -> None:
    """One confirmed game per entry; an entry lists each seat's placement in the game, in slot order -- or, when
    ``scored``, its raw score with no placement entered (the place is then derived from the scores)."""
    seats = (
        await session.scalars(
            sa.select(EncounterTeam).where(EncounterTeam.encounter_id == encounter.id).order_by(EncounterTeam.slot)
        )
    ).all()
    for position, values in enumerate(games, 1):
        game = EncounterGame(
            encounter_id=encounter.id,
            position=position,
            state=enums.EncounterGameState.CONFIRMED,
            result_source=enums.EncounterGameResultSource.ADMIN,
            confirmed_at=datetime.now(UTC),
        )
        session.add(game)
        await session.flush()
        session.add_all(
            EncounterGameTeam(
                game_id=game.id,
                encounter_id=encounter.id,
                encounter_team_id=seat.id,
                placement=None if scored else value,
                score=value if scored else None,
            )
            for seat, value in zip(seats, values, strict=True)
        )
    await session.flush()


def add_observed_game(
    db: Any,
    *,
    match_id: int | None = None,
    encounter_id: int,
    map_entity_id: int,
    position: int,
    duration_s: float,
    scores: Sequence[float],
    observations: Sequence[tuple[int, int, int | None, enums.LogStatsName, float]],
) -> None:
    """Seed native facts; observations are (member, slot, character, stat, value)."""
    encounter = db.get(Encounter, encounter_id)
    assert encounter is not None
    seats = db.scalars(
        sa.select(EncounterTeam)
        .where(
            EncounterTeam.encounter_id == encounter_id,
        )
        .order_by(EncounterTeam.slot)
    ).all()
    by_slot = {seat.slot: seat for seat in seats}
    assert len(scores) == len(seats)
    game = EncounterGame(encounter_id=encounter_id, position=position, map_id=map_entity_id)
    db.add(game)
    db.flush()
    db.add_all(
        EncounterGameTeam(
            game_id=game.id,
            encounter_id=encounter_id,
            encounter_team_id=seat.id,
        )
        for seat in seats
    )
    match = models.StatsMatch(
        id=match_id,
        workspace_id=encounter.workspace_id,
        discipline=encounter.discipline,
        encounter_id=encounter_id,
        encounter_game_id=game.id,
        map_entity_id=map_entity_id,
        duration_s=duration_s,
    )
    db.add(match)
    db.flush()
    match_id = match.id
    db.add_all(
        models.StatsMatchTeam(
            match_id=match_id,
            encounter_id=encounter_id,
            encounter_team_id=seat.id,
            source_position=seat.slot,
        )
        for seat in seats
    )
    for member_id, slot in sorted({(member, slot) for member, slot, *_ in observations}):
        member = db.get(models.WorkspaceMember, member_id)
        assert member is not None and member.workspace_id == encounter.workspace_id
        player = db.get(models.User, member.player_id)
        assert player is not None
        db.add(
            models.StatsMatchPlayer(
                match_id=match_id,
                workspace_member_id=member_id,
                encounter_team_id=by_slot[slot].id,
                handle_snapshot=player.name,
            )
        )
    db.flush()
    stat_ids = dict(
        db.execute(
            sa.select(models.StatDef.code, models.StatDef.id).where(
                models.StatDef.discipline == encounter.discipline,
            )
        ).all()
    )
    facts = [
        {
            "match_id": match_id,
            "segment": 0,
            "encounter_team_id": seat.id,
            "workspace_member_id": None,
            "entity_id": None,
            "entity_kind": "character",
            "stat_id": stat_ids["score"],
            "value": score,
        }
        for seat, score in zip(seats, scores, strict=True)
    ]
    facts.extend(
        {
            "match_id": match_id,
            "segment": 0,
            "encounter_team_id": by_slot[slot].id,
            "workspace_member_id": member,
            "entity_id": entity_id,
            "entity_kind": "character",
            "stat_id": stat_ids[stat.value],
            "value": value,
        }
        for member, slot, entity_id, stat, value in observations
    )
    db.execute(models.StatsFact.__table__.insert(), facts)
