"""Public reads of an ``individual_swiss`` stage: the personal table and the rounds with their seats."""

from __future__ import annotations

import typing
from collections import defaultdict

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.repository import StageRepository
from shared.services.cache_generations import versioned
from shared.services.team_format import tournament_slot_shape
from src.core import config
from src.schemas import individual_swiss as swiss_schemas
from src.services.tournament.cache_resources import STANDINGS, tournament_generations

__all__ = ("IndividualSwissReadsService", "reads_service", "role_order", "to_player_standing_read")

_stages = StageRepository()


def to_player_standing_read(row: models.PlayerStanding) -> swiss_schemas.PlayerStandingRead:
    fields = {name: getattr(row, name) for name in swiss_schemas.PlayerStandingRead.model_fields if hasattr(row, name)}
    return swiss_schemas.PlayerStandingRead(**fields, map_diff=row.maps_won - row.maps_lost)


async def role_order(session: AsyncSession, tournament_id: int) -> dict[str, int]:
    """Role code -> its place in the roster shape; a role outside the shape sorts after all of them."""
    shape = await tournament_slot_shape(session, tournament_id)
    return {code: index for index, (code, _) in enumerate(shape.entries)}


class IndividualSwissReadsService:
    async def player_standings(
        self, session: AsyncSession, tournament_id: int
    ) -> list[swiss_schemas.PlayerStandingRead]:
        """Every ``individual_swiss`` stage's table: by stage order, role (shape order), position."""
        result = await session.execute(
            sa.select(models.PlayerStanding, models.Stage.order)
            .join(models.Stage, models.Stage.id == models.PlayerStanding.stage_id)
            .where(
                models.PlayerStanding.tournament_id == tournament_id,
                models.Stage.stage_type == enums.StageType.INDIVIDUAL_SWISS,
            )
        )
        rows = result.tuples().all()
        roles = await role_order(session, tournament_id)
        rows = sorted(
            rows,
            key=lambda pair: (
                pair[1],
                pair[0].stage_id,
                roles.get(pair[0].role, len(roles)),
                pair[0].role,
                pair[0].position is None,
                pair[0].position or 0,
                pair[0].id,
            ),
        )
        return [to_player_standing_read(row) for row, _ in rows]

    async def rounds(
        self, session: AsyncSession, tournament_id: int, stage_id: int
    ) -> list[swiss_schemas.IndividualRoundRead]:
        """The stage's encounters grouped by round, each seat with its roster snapshot."""
        stage = await _stages.get(session, stage_id)
        if (
            stage is None
            or stage.tournament_id != tournament_id
            or stage.stage_type != enums.StageType.INDIVIDUAL_SWISS
        ):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stage not found")

        placed = (
            (
                await session.execute(
                    sa.select(models.BracketEncounter.round, models.Encounter)
                    .join(models.Encounter, models.Encounter.id == models.BracketEncounter.encounter_id)
                    .where(models.BracketEncounter.stage_id == stage_id)
                    .order_by(models.BracketEncounter.round, models.Encounter.id)
                )
            )
            .tuples()
            .all()
        )
        encounter_ids = [encounter.id for _, encounter in placed]
        seats = (
            (
                await session.execute(
                    sa.select(models.EncounterTeam)
                    .where(models.EncounterTeam.encounter_id.in_(encounter_ids), models.EncounterTeam.active)
                    .order_by(models.EncounterTeam.encounter_id, models.EncounterTeam.slot)
                )
            )
            .scalars()
            .all()
        )
        members = (
            (
                await session.execute(
                    sa.select(models.EncounterTeamMember).where(
                        models.EncounterTeamMember.encounter_id.in_(encounter_ids), models.EncounterTeamMember.active
                    )
                )
            )
            .scalars()
            .all()
        )
        # The stage's frozen pool is the one place a player's role is kept apart from the seat snapshots.
        pool_roles = dict(
            (
                await session.execute(
                    sa.select(models.PlayerStanding.workspace_member_id, models.PlayerStanding.role).where(
                        models.PlayerStanding.stage_id == stage_id
                    )
                )
            )
            .tuples()
            .all()
        )
        roles = await role_order(session, tournament_id)

        members_by_seat: defaultdict[int, list[models.EncounterTeamMember]] = defaultdict(list)
        for member in members:
            members_by_seat[member.encounter_team_id].append(member)
        seats_by_encounter: defaultdict[int, list[models.EncounterTeam]] = defaultdict(list)
        for seat in seats:
            seats_by_encounter[seat.encounter_id].append(seat)

        def seat_read(seat: models.EncounterTeam) -> swiss_schemas.IndividualRoundSeatRead:
            roster = sorted(
                members_by_seat[seat.id],
                key=lambda m: (
                    roles.get(pool_roles.get(m.workspace_member_id, ""), len(roles)),
                    -(m.rank or 0),
                    m.display_name_snapshot,
                ),
            )
            return swiss_schemas.IndividualRoundSeatRead(
                participation_id=seat.id,
                slot=seat.slot,
                name=seat.name,
                score=seat.score,
                placement=seat.placement,
                members=[
                    swiss_schemas.IndividualRoundSeatMemberRead(
                        workspace_member_id=m.workspace_member_id,
                        display_name=m.display_name_snapshot,
                        role=pool_roles.get(m.workspace_member_id),
                        rank=m.rank,
                        is_captain=m.is_captain,
                    )
                    for m in roster
                ],
            )

        by_round: dict[int, list[swiss_schemas.IndividualRoundEncounterRead]] = {}
        for round_number, encounter in placed:
            by_round.setdefault(round_number, []).append(
                swiss_schemas.IndividualRoundEncounterRead(
                    encounter_id=encounter.id,
                    status=encounter.status,
                    result_status=encounter.result_status,
                    best_of=encounter.best_of,
                    seats=[seat_read(seat) for seat in seats_by_encounter[encounter.id]],
                )
            )
        return [swiss_schemas.IndividualRoundRead(round=number, encounters=by_round[number]) for number in by_round]

    # Wire dicts, like ``StandingsFlowsService.get_by_tournament``: a hit is a plain unpickle, and a wire change bumps the
    # version. STANDINGS carries the standings job's write and every encounter/structure change, which is all these embed.
    @versioned(
        generations=tournament_generations("{tournament_id}", STANDINGS),
        ttl=config.settings.standings_cache_ttl,
        key="individual_swiss_standings:v1:{tournament_id}",
        prefix="fastapi:",
    )
    async def get_player_standings(self, session: AsyncSession, tournament_id: int) -> list[dict[str, typing.Any]]:
        return [row.model_dump(mode="json") for row in await self.player_standings(session, tournament_id)]

    @versioned(
        generations=tournament_generations("{tournament_id}", STANDINGS),
        ttl=config.settings.standings_cache_ttl,
        key="individual_swiss_rounds:v1:{tournament_id}:{stage_id}",
        prefix="fastapi:",
    )
    async def get_rounds(self, session: AsyncSession, tournament_id: int, stage_id: int) -> list[dict[str, typing.Any]]:
        return [row.model_dump(mode="json") for row in await self.rounds(session, tournament_id, stage_id)]


reads_service = IndividualSwissReadsService()
