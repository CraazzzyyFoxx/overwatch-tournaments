"""Shared state and primitives of the stage admin service: repositories, loads, locks, the write epilogue."""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.repository import (
    EncounterGameTeamRepository,
    EncounterRepository,
    PickBanConfigRepository,
    StageItemInputRepository,
    StageItemRepository,
    StageRepository,
    StandingRepository,
    TeamRepository,
    TournamentRepository,
)
from src.services.tournament.events import (
    STRUCTURE_RESOURCES,
    enqueue_tournament_recalculation,
    publish_tournament_invalidation,
)


class StageServiceBase:
    def __init__(
        self,
        *,
        stage_repo: StageRepository = StageRepository(),
        stage_item_repo: StageItemRepository = StageItemRepository(),
        stage_item_input_repo: StageItemInputRepository = StageItemInputRepository(),
        encounter_repo: EncounterRepository = EncounterRepository(),
        standing_repo: StandingRepository = StandingRepository(),
        team_repo: TeamRepository = TeamRepository(),
        tournament_repo: TournamentRepository = TournamentRepository(),
        pick_ban_config_repo: PickBanConfigRepository = PickBanConfigRepository(),
        result_repo: EncounterGameTeamRepository = EncounterGameTeamRepository(),
    ) -> None:
        self.stage_repo = stage_repo
        self.stage_item_repo = stage_item_repo
        self.stage_item_input_repo = stage_item_input_repo
        self.encounter_repo = encounter_repo
        self.standing_repo = standing_repo
        self.team_repo = team_repo
        self.tournament_repo = tournament_repo
        self.pick_ban_config_repo = pick_ban_config_repo
        self.result_repo = result_repo

    async def _publish_structure_changed(self, session: AsyncSession, tournament_id: int) -> None:
        """Announce that this tournament's set of page sections moved.

        Every stage write reaches here, and every one of them creates, removes or
        re-shapes a stage — which is exactly ``tournament.structure``: the
        overview (and the section rail derived from it) goes stale along with the
        bracket reads.
        """
        await publish_tournament_invalidation(session, tournament_id, STRUCTURE_RESOURCES)

    async def get_stage(self, session: AsyncSession, stage_id: int, *, populate_existing: bool = False) -> models.Stage:
        stage = await self.stage_repo.get(
            session,
            stage_id,
            options=[selectinload(models.Stage.items).selectinload(models.StageItem.inputs)],
            populate_existing=populate_existing,
        )
        if not stage:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stage not found")
        return stage

    async def get_tournament_id(self, session: AsyncSession, stage_id: int) -> int:
        tournament_id = await self.stage_repo.get_tournament_id(session, stage_id)
        if tournament_id is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stage not found")
        return tournament_id

    async def _lock_stage(self, session: AsyncSession, stage_id: int) -> None:
        """Serialize the writers that race over one stage's bracket: a template
        swap and a generation job must not interleave around their "does this
        stage have encounters yet" check, nor two seed moves around one item's
        slot numbering. Lock order is stage → encounters
        everywhere (``computation.bracket_worker`` takes tournament → stage first)."""
        await session.execute(select(models.Stage.id).where(models.Stage.id == stage_id).with_for_update())

    async def _count_stage_encounters(self, session: AsyncSession, stage_id: int, **filters: Any) -> int:
        """How many encounters sit in this stage. One count over
        ``tournament.bracket_encounter``, which is where a stage's encounters
        are listed; ``filters`` are extra ``Encounter`` column equals."""
        query = (
            select(func.count())
            .select_from(models.BracketEncounter)
            .where(models.BracketEncounter.stage_id == stage_id)
        )
        if filters:
            query = query.join(models.Encounter, models.Encounter.id == models.BracketEncounter.encounter_id).where(
                *(getattr(models.Encounter, column) == value for column, value in filters.items())
            )
        return int(await session.scalar(query) or 0)

    async def _assert_no_encounters(self, session: AsyncSession, stage_id: int) -> None:
        if await self._count_stage_encounters(session, stage_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This stage already has generated matches. Delete them first to edit the bracket.",
            )

    async def get_stage_item(self, session: AsyncSession, stage_item_id: int) -> models.StageItem:
        item = await self.stage_item_repo.get(session, stage_item_id, options=[selectinload(models.StageItem.inputs)])
        if not item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Stage item not found",
            )
        return item

    async def get_stages_by_tournament(self, session: AsyncSession, tournament_id: int) -> list[models.Stage]:
        return list(
            await self.stage_repo.list_by_tournament(
                session,
                tournament_id,
                options=[selectinload(models.Stage.items).selectinload(models.StageItem.inputs)],
            )
        )

    async def _finish_structure_write(
        self,
        session: AsyncSession,
        stage: models.Stage,
        *,
        notify: bool,
        commit: bool,
        schedule_standings: bool,
    ) -> None:
        if schedule_standings:
            await enqueue_tournament_recalculation(session, stage.tournament_id)
        if notify:
            await self._publish_structure_changed(session, stage.tournament_id)
        if commit:
            await session.commit()
        else:
            await session.flush()
