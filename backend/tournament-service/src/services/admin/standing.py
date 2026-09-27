"""Admin service layer for standing management"""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.repository import StandingRepository, TournamentRepository
from src import models, schemas
from src.services.admin.stage import stage_service as admin_stage_service
from src.services.computation.jobs import jobs_service
from src.services.tournament.events import RESULT_RESOURCES, publish_tournament_invalidation


class AdminStandingService:
    def __init__(
        self,
        *,
        standing_repo: StandingRepository = StandingRepository(),
        tournament_repo: TournamentRepository = TournamentRepository(),
    ) -> None:
        self.standing_repo = standing_repo
        self.tournament_repo = tournament_repo

    async def _publish_results_changed(self, session: AsyncSession, tournament_id: int) -> None:
        await publish_tournament_invalidation(session, tournament_id, RESULT_RESOURCES)

    async def get_standing(self, session: AsyncSession, standing_id: int) -> models.Standing:
        standing = await self.standing_repo.get(
            session,
            standing_id,
            options=(
                selectinload(models.Standing.team),
                selectinload(models.Standing.stage)
                .selectinload(models.Stage.items)
                .selectinload(models.StageItem.inputs),
                selectinload(models.Standing.stage_item).selectinload(models.StageItem.inputs),
                selectinload(models.Standing.tournament),
            ),
        )

        if not standing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Standing not found",
            )

        return standing

    async def update_standing(
        self, session: AsyncSession, standing_id: int, data: schemas.StandingUpdate
    ) -> models.Standing:
        """Update standing fields"""
        standing = await self.get_standing(session, standing_id)

        # Update fields
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(standing, field, value)

        await self._publish_results_changed(session, standing.tournament_id)
        await session.commit()
        return await self.get_standing(session, standing.id)

    async def delete_standing(self, session: AsyncSession, standing_id: int) -> None:
        """Delete standing"""
        standing = await self.standing_repo.get(session, standing_id)

        if not standing:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Standing not found")

        await self._publish_results_changed(session, standing.tournament_id)
        await self.standing_repo.delete(session, standing)
        await session.commit()

    async def recalculate_standings(
        self,
        session: AsyncSession,
        tournament_id: int,
        *,
        requested_by_user_id: int | None = None,
    ) -> models.TournamentComputationJob:
        """Schedule a durable standings recalculation without exposing empty data."""
        # Verify tournament exists
        tournament = await self.tournament_repo.get(session, tournament_id)

        if not tournament:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")

        job = await jobs_service.request_standings_recalculation(
            session,
            tournament_id,
            requested_by_user_id=requested_by_user_id,
        )
        await session.commit()
        return job

    async def get_pins(self, session: AsyncSession, stage_id: int, stage_item_id: int | None) -> dict[int, int]:
        """One table's pins, ``team_id -> position``."""
        result = await session.execute(
            sa.select(models.StandingPin.team_id, models.StandingPin.position).where(
                models.StandingPin.stage_id == stage_id,
                models.StandingPin.stage_item_id.is_not_distinct_from(stage_item_id),
            )
        )
        return dict(result.tuples().all())

    async def set_pins(
        self,
        session: AsyncSession,
        stage: models.Stage,
        data: schemas.StandingPinsUpdate,
        *,
        requested_by_user_id: int | None = None,
    ) -> models.TournamentComputationJob:
        """Replace one table's pins and schedule the recalculation that applies them.

        The table's current rows are the authority on who is in it and how many
        places it has. Once a playoff seeded from this group is under way, only
        places below its qualification cut may change: anything that could move
        a team across the cut would leave the playoff playing a team that no
        longer qualified (the same rule ``assert_source_correction_allowed``
        applies to result corrections). Unpinning is refused there outright --
        where the team falls back to is only known after the recalculation.
        Commits.
        """
        # Serializes concurrent edits of one stage's tables: each replaces a whole
        # table, so two interleaved replaces would collide on the unique indexes.
        await session.execute(sa.select(models.Stage.id).where(models.Stage.id == stage.id).with_for_update())
        result = await session.execute(
            self.standing_repo.select().where(
                models.Standing.stage_id == stage.id,
                models.Standing.stage_item_id.is_not_distinct_from(data.stage_item_id),
            )
        )
        rows = result.scalars().all()
        if not rows:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="This stage has no standings table for that group; recalculate standings first",
            )
        position_by_team = {row.team_id: row.position for row in rows}
        wanted = {pin.team_id: pin.position for pin in data.pins}
        strangers = sorted(set(wanted) - set(position_by_team))
        if strangers:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Teams {strangers} are not in this standings table",
            )
        beyond = sorted(team_id for team_id, position in wanted.items() if position > len(rows))
        if beyond:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"The table has {len(rows)} places; teams {beyond} are pinned past its end",
            )

        # A pin of a team that has since left the table is dropped, not diffed.
        current = {
            team_id: position
            for team_id, position in (await self.get_pins(session, stage.id, data.stage_item_id)).items()
            if team_id in position_by_team
        }
        if data.stage_item_id is not None and wanted != current:
            cut = await admin_stage_service.started_qualification_cut(session, data.stage_item_id)
            if cut is not None:
                changed = {
                    team_id for team_id in current.keys() | wanted.keys() if current.get(team_id) != wanted.get(team_id)
                }
                if any(
                    team_id not in wanted or position_by_team[team_id] <= cut or wanted[team_id] <= cut
                    for team_id in changed
                ):
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            f"A playoff seeded from places 1-{cut} of this group is already under way; "
                            f"only places below {cut} can be pinned, and no pin can be removed"
                        ),
                    )

        await session.execute(
            sa.delete(models.StandingPin).where(
                models.StandingPin.stage_id == stage.id,
                models.StandingPin.stage_item_id.is_not_distinct_from(data.stage_item_id),
            )
        )
        session.add_all(
            models.StandingPin(
                tournament_id=stage.tournament_id,
                stage_id=stage.id,
                stage_item_id=data.stage_item_id,
                team_id=team_id,
                position=position,
            )
            for team_id, position in wanted.items()
        )
        job = await jobs_service.request_standings_recalculation(
            session,
            stage.tournament_id,
            requested_by_user_id=requested_by_user_id,
        )
        await session.commit()
        return job


standing_service = AdminStandingService()
