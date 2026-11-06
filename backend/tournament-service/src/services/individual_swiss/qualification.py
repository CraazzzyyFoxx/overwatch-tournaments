"""The qualification lock: freeze the qualifiers and complete the stage node."""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.core import enums
from shared.core import http_status as status
from shared.core.enums import DraftFormat
from shared.repository import StageRepository, TournamentRepository
from shared.schemas.draft_format import DraftFormatSettings
from src.schemas import individual_swiss as swiss_schemas
from src.services.flow.lifecycle import flow_node_service
from src.services.individual_swiss.pins import refuse
from src.services.individual_swiss.reads import role_order, to_player_standing_read
from src.services.individual_swiss.standings import recalculate_individual_stage
from src.services.standings.service import standings_service

__all__ = ("IndividualSwissQualificationService", "qualification_service")

_stages = StageRepository()
_tournaments = TournamentRepository()


class IndividualSwissQualificationService:
    async def lock(
        self, session: AsyncSession, stage: models.Stage, *, actor_user_id: int | None = None
    ) -> swiss_schemas.QualificationLockRead:
        """Freeze the stage's qualifiers and complete its node (``live`` -> ``completed``).

        Under the tournament and stage locks the personal table is first recalculated from the current results and
        pins (a pin saved a moment ago is still only queued for the worker), then ``qualification_locked_at`` freezes
        the qualifier and captain flags. The marker, the refreshed table and the node move commit together; the
        tournament status follows the nodes. Who plays on is the downstream filter's business, not the lock's. Commits.
        """
        if stage.stage_type != enums.StageType.INDIVIDUAL_SWISS:
            raise refuse(status.HTTP_409_CONFLICT, "not_individual_swiss", "Это не этап личной швейцарки")
        # The tournament row serializes two organizers locking at once: the loser sees the node completed and is
        # refused. The order (tournament, then stage) is the bracket worker's; the pin writer takes the stage row alone.
        tournament = await _tournaments.get(
            session,
            stage.tournament_id,
            for_update=True,
            populate_existing=True,
            options=[selectinload(models.Tournament.stages).selectinload(models.Stage.items)],
        )
        await session.execute(sa.select(models.Stage.id).where(models.Stage.id == stage.id).with_for_update())
        stage = await _stages.get(session, stage.id, populate_existing=True) or stage
        node = await session.scalar(
            sa.select(models.FlowNode)
            .where(models.FlowNode.stage_id == stage.id)
            .execution_options(populate_existing=True)
        )
        if (
            tournament is None
            or node is None
            or node.status != enums.FlowNodeStatus.LIVE
            or stage.qualification_locked_at is not None
        ):
            raise refuse(
                status.HTTP_409_CONFLICT,
                "qualification_not_live",
                "Квалификацию можно закрепить только пока этап идёт (LIVE), и только один раз",
            )
        # The lock completes this node, the standings worker never does: the standings rule is read here.
        if stage.id not in await standings_service._completed_stage_ids(session, tournament, []):
            raise refuse(
                status.HTTP_409_CONFLICT,
                "stage_not_completed",
                "Этап ещё не завершён: сыграйте все туры личной швейцарки",
            )
        draft_formats = await session.scalars(
            sa.select(models.FlowNode.config["draft_format"]).where(
                models.FlowNode.tournament_id == tournament.id,
                models.FlowNode.kind == enums.FlowNodeKind.FORMATION,
                models.FlowNode.config["mode"].astext == "draft",
            )
        )
        if any(DraftFormatSettings.model_validate(raw or {}).format is not DraftFormat.SNAKE for raw in draft_formats):
            raise refuse(
                status.HTTP_409_CONFLICT,
                "draft_format_not_snake",
                "Плей-офф после личной швейцарки играется змейкой: переключите формат драфта на «змейка»",
            )

        await recalculate_individual_stage(session, stage, tournament)
        rows = list(
            (
                await session.execute(
                    sa.select(models.PlayerStanding)
                    .where(models.PlayerStanding.stage_id == stage.id)
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        if not any(row.is_qualified for row in rows):
            raise refuse(status.HTTP_409_CONFLICT, "no_qualifiers", "В таблице этапа нет квалифицировавшихся игроков")

        stage.qualification_locked_at = datetime.now(UTC)
        await flow_node_service.transition(session, node.id, enums.FlowNodeStatus.COMPLETED, actor=None)
        await session.commit()

        roles = await role_order(session, stage.tournament_id)
        qualified = sorted(
            (row for row in rows if row.is_qualified),
            key=lambda row: (roles.get(row.role, len(roles)), row.role, row.position is None, row.position or 0),
        )
        captains = sorted((row for row in qualified if row.is_captain), key=lambda row: -row.rank)
        return swiss_schemas.QualificationLockRead(
            qualified=[to_player_standing_read(row) for row in qualified],
            captains=[to_player_standing_read(row) for row in captains],
        )


qualification_service = IndividualSwissQualificationService()
