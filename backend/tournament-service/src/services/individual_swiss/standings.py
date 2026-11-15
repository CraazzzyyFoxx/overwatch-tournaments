"""The personal table of an ``individual_swiss`` stage: totals from the confirmed rounds, order inside each role,
the qualification cut.

Reads the stage's frozen ``PlayerStanding`` pool and the participations' snapshot rosters (a round team has no
``tournament.team``); writes only the rows whose values moved.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums
from shared.repository.player_standing import PlayerStandingRepository
from shared.services.team_format import tournament_slot_shape
from src.domain.individual_swiss import (
    MatchResult,
    PoolPlayer,
    SeatResult,
    StandingLine,
    compute_totals,
    order_role,
    pick_captains,
    qualify,
)

__all__ = ("DEFAULT_PLAYOFF_TEAMS", "order_by_role", "recalculate_individual_stage", "stage_pins", "stage_players")

#: Mirrors the default the stage write path stores; a row from before it was set reads the same.
DEFAULT_PLAYOFF_TEAMS = 4

_players = PlayerStandingRepository()


async def stage_players(session: AsyncSession, stage_id: int) -> list[models.PlayerStanding]:
    return await _players.for_stage(session, stage_id)


async def stage_pins(session: AsyncSession, stage_id: int) -> dict[int, int]:
    """``workspace_member_id -> position`` (inside the member's role)."""
    rows = await session.execute(
        sa.select(models.PlayerStandingPin.workspace_member_id, models.PlayerStandingPin.position).where(
            models.PlayerStandingPin.stage_id == stage_id
        )
    )
    return dict(rows.all())


def order_by_role(
    lines: Sequence[StandingLine], pins: Mapping[int, int], shape: Mapping[str, int]
) -> dict[str, list[int]]:
    """Member ids per role, best first. Every role of the shape is present, even with nobody in it."""
    by_role: dict[str, list[StandingLine]] = defaultdict(list)
    for line in lines:
        by_role[line.role].append(line)
    return {role: order_role(by_role.get(role, []), pins) for role in {*shape, *by_role}}


def _places(seats: Sequence[tuple[float, int | None]]) -> list[int]:
    """The writer's placements, else competition ranking by score (a drawn series shares first place)."""
    if all(placement is not None for _, placement in seats):
        return [int(placement) for _, placement in seats]  # type: ignore[arg-type]
    best = max(score for score, _ in seats)
    return [1 if score == best else 2 for score, _ in seats]


async def _confirmed_results(session: AsyncSession, stage_id: int, pool: set[int]) -> list[MatchResult]:
    """One ``MatchResult`` per completed two-seat encounter of the stage; seat members outside the pool are dropped."""
    seat_rows = (
        await session.execute(
            sa.select(
                models.EncounterTeam.id,
                models.EncounterTeam.encounter_id,
                models.EncounterTeam.score,
                models.EncounterTeam.placement,
            )
            .join(models.Encounter, models.Encounter.id == models.EncounterTeam.encounter_id)
            .join(models.BracketEncounter, models.BracketEncounter.encounter_id == models.Encounter.id)
            .where(
                models.BracketEncounter.stage_id == stage_id,
                models.Encounter.status == enums.EncounterStatus.COMPLETED,
                models.EncounterTeam.active.is_(True),
            )
            .order_by(models.EncounterTeam.encounter_id, models.EncounterTeam.slot)
        )
    ).all()
    if not seat_rows:
        return []
    members: dict[int, list[int]] = defaultdict(list)
    member_rows = await session.execute(
        sa.select(models.EncounterTeamMember.encounter_team_id, models.EncounterTeamMember.workspace_member_id)
        .where(
            models.EncounterTeamMember.encounter_team_id.in_([row.id for row in seat_rows]),
            models.EncounterTeamMember.active.is_(True),
        )
        .order_by(models.EncounterTeamMember.id)
    )
    for seat_id, member_id in member_rows:
        if member_id in pool:
            members[seat_id].append(member_id)
    by_encounter: dict[int, list] = defaultdict(list)
    for row in seat_rows:
        by_encounter[row.encounter_id].append(row)
    results = []
    for seats in by_encounter.values():
        if len(seats) != 2:
            continue
        places = _places([(seat.score, seat.placement) for seat in seats])
        first, second = (
            SeatResult(members=tuple(members[seat.id]), score=seat.score, placement=place)
            for seat, place in zip(seats, places, strict=True)
        )
        results.append(MatchResult(seats=(first, second)))
    return results


async def recalculate_individual_stage(
    session: AsyncSession, stage: models.Stage, tournament: models.Tournament
) -> bool:
    """Rebuild the stage's personal table from its confirmed encounters; whether any row changed.

    A stage that was never started (no pool rows) has nothing to compute. ``rank`` is derived like every total:
    ``start_rank`` moved by the stage's per-result deltas, never below 1 (a rank of 0 or less means "unranked").
    """
    # Imported here: ``standings.service`` imports this module for its stage-type branch.
    from src.services.standings.service import _scoring

    rows = await stage_players(session, stage.id)
    if not rows:
        return False
    shape = (await tournament_slot_shape(session, tournament.id)).slots
    win, draw, loss = _scoring(stage)
    totals = compute_totals(
        [row.workspace_member_id for row in rows],
        await _confirmed_results(session, stage.id, {row.workspace_member_id for row in rows}),
        win=win,
        draw=draw,
        loss=loss,
    )
    win_delta, loss_delta = stage.rank_win_delta or 0, stage.rank_loss_delta or 0
    ranks = {
        row.workspace_member_id: max(
            1,
            row.start_rank
            + totals[row.workspace_member_id].wins * win_delta
            - totals[row.workspace_member_id].losses * loss_delta,
        )
        for row in rows
    }
    pins = await stage_pins(session, stage.id)
    lines = [
        StandingLine(
            row.workspace_member_id,
            row.role,
            ranks[row.workspace_member_id],
            totals[row.workspace_member_id].points,
            totals[row.workspace_member_id].map_diff,
            totals[row.workspace_member_id].buchholz,
        )
        for row in rows
    ]
    order = order_by_role(lines, pins, shape)
    k = stage.playoff_team_count or DEFAULT_PLAYOFF_TEAMS
    qualified = qualify(order, shape, k)
    pool = [
        PoolPlayer(
            row.workspace_member_id, row.registration_id, row.display_name, row.role, ranks[row.workspace_member_id]
        )
        for row in rows
        if row.workspace_member_id in qualified
    ]
    captains = set(pick_captains(pool, k))
    position = {member_id: place for ids in order.values() for place, member_id in enumerate(ids, 1)}

    # Once the qualification is locked the pool is frozen: points and places keep following the results, but who is
    # a qualifier or a captain is what the lock decided.
    frozen = stage.qualification_locked_at is not None
    changed = False
    for row in rows:
        member_id = row.workspace_member_id
        total = totals[member_id]
        wanted = {
            "rank": ranks[member_id],
            "points": total.points,
            "wins": total.wins,
            "draws": total.draws,
            "losses": total.losses,
            "matches_played": total.matches_played,
            "maps_won": total.maps_won,
            "maps_lost": total.maps_lost,
            "buchholz": total.buchholz,
            "position": position[member_id],
            "is_pinned": member_id in pins,
        }
        if not frozen:
            wanted["is_qualified"] = member_id in qualified
            wanted["is_captain"] = member_id in captains
        for attribute, value in wanted.items():
            if getattr(row, attribute) != value:
                setattr(row, attribute, value)
                changed = True
    await session.flush()
    return changed
