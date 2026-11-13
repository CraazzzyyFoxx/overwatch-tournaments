"""Shared state and primitives of the stage admin service: repositories, loads, locks, the write epilogue."""

from collections.abc import Sequence
from typing import Any, cast

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.core import enums
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
from src.domain.stage.seeds import SeatSource, SeedRanking, lower_bracket_item, plan_seats
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

    async def _stage_input_rows(
        self, session: AsyncSession, stage: models.Stage
    ) -> tuple[models.FlowNode | None, list[models.FlowNodeResult]]:
        """The stage's node and the team rows wired into its ``participants`` port, in rank order (spec §5.3).

        A stage without a node (a scrim stage) or without an input edge has no rows.
        """
        node = await session.scalar(select(models.FlowNode).where(models.FlowNode.stage_id == stage.id))
        if node is None:
            return None, []
        rows = await session.scalars(
            select(models.FlowNodeResult)
            .join(
                models.FlowEdge,
                and_(
                    models.FlowEdge.source_node_id == models.FlowNodeResult.node_id,
                    models.FlowEdge.source_port == models.FlowNodeResult.port,
                ),
            )
            .where(
                models.FlowEdge.target_node_id == node.id,
                models.FlowEdge.target_port == "participants",
                models.FlowNodeResult.team_id.is_not(None),
            )
            .order_by(models.FlowNodeResult.rank, models.FlowNodeResult.id)
            # The engine rewrites result rows with core statements, so a loaded copy may be stale.
            .execution_options(populate_existing=True)
        )
        return node, list(rows)

    async def _plan_for(
        self, session: AsyncSession, stage: models.Stage, rows: Sequence[models.FlowNodeResult]
    ) -> dict[int, list[SeatSource]]:
        """Stage item id -> the input rows seated in it, in slot order (spec §5.3, plan Decisions 1-3).

        A double-elimination stage that gets lower starters gets its lower bracket item here.
        """
        double = stage.stage_type == enums.StageType.DOUBLE_ELIMINATION
        sources = [
            SeatSource(
                row.id,
                cast(int, row.team_id),
                row.stage_item_id,
                row.item_rank,
                lower=(row.breakdown or {}).get("bracket") == "lower",
            )
            for row in rows
        ]
        if double and any(one.lower for one in sources) and not lower_bracket_item(stage, list(stage.items)):
            lower = models.StageItem(
                stage_id=stage.id,
                name="Lower bracket",
                type=enums.StageItemType.BRACKET_LOWER,
                order=max((item.order for item in stage.items), default=-1) + 1,
                # Explicitly empty: an untouched collection lazy-loads once flushed, which an async session refuses.
                inputs=[],
            )
            await self.stage_item_repo.create(session, lower)
            stage.items.append(lower)
        source_item_ids = {one.stage_item_id for one in sources if one.stage_item_id is not None}
        item_orders = await session.execute(
            select(models.StageItem.id, models.StageItem.order).where(models.StageItem.id.in_(source_item_ids))
        )
        source_item_order = dict(item_orders.all())
        return plan_seats(
            sources,
            ranking=SeedRanking(stage.seed_ranking),
            target_items=stage.items,
            double_elimination=double,
            arrange_groups=stage.bracket_template is None,
            source_item_order=source_item_order,
            rng_seed=stage.id,
        )

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
