"""The qualification lock: trim the balancer pool to the qualifiers and open the playoff draft."""

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
from src.services.admin.tournament import tournament_service
from src.services.individual_swiss.pins import refuse
from src.services.individual_swiss.reads import role_order, to_player_standing_read
from src.services.individual_swiss.standings import recalculate_individual_stage
from src.services.registration._common import EXCLUDED_BALANCER_STATUS
from src.services.registration.lifecycle import lifecycle_service
from src.services.registration.realtime import emit_balancer_registrations_changed
from src.services.standings.service import standings_service

__all__ = ("NOT_QUALIFIED_REASON", "IndividualSwissQualificationService", "qualification_service")

NOT_QUALIFIED_REASON = "not_qualified"

_stages = StageRepository()
_tournaments = TournamentRepository()


class IndividualSwissQualificationService:
    async def lock(
        self, session: AsyncSession, stage: models.Stage, *, actor_user_id: int | None = None
    ) -> swiss_schemas.QualificationLockRead:
        """Exclude every non-qualified player of the stage from the balancer pool, then move LIVE -> DRAFT.

        Under the tournament and stage locks the personal table is first recalculated from the current results and
        pins (a pin saved a moment ago is still only queued for the worker), then ``qualification_locked_at`` freezes
        the qualifier and captain flags. The marker, the refreshed table and the exclusions commit together. The
        draft pool is what the balancer still counts in, so afterwards it is exactly the qualifiers. Commits.

        # shortcut: the exclusions and the status change commit one after the other (both services commit); when
        # the status change fails the marker is cleared again, so the same call can be repeated. Upgrade to one
        # transaction if the status change ever gains a way to fail late.
        """
        if stage.stage_type != enums.StageType.INDIVIDUAL_SWISS:
            raise refuse(status.HTTP_409_CONFLICT, "not_individual_swiss", "Это не этап личной швейцарки")
        # The tournament row serializes two organizers locking at once: the loser sees DRAFT and is refused. The
        # order (tournament, then stage) is the bracket worker's; the pin writer takes the stage row alone.
        tournament = await _tournaments.get(
            session,
            stage.tournament_id,
            for_update=True,
            populate_existing=True,
            options=[selectinload(models.Tournament.stages).selectinload(models.Stage.items)],
        )
        await session.execute(sa.select(models.Stage.id).where(models.Stage.id == stage.id).with_for_update())
        stage = await _stages.get(session, stage.id, populate_existing=True) or stage
        if (
            tournament is None
            or tournament.status != enums.TournamentStatus.LIVE
            or stage.qualification_locked_at is not None
        ):
            raise refuse(
                status.HTTP_409_CONFLICT,
                "qualification_not_live",
                "Квалификацию можно закрепить только пока турнир идёт (LIVE), и только один раз",
            )
        # The lock completes the stage node (Task 5), the worker never does: the standings rule is read here.
        if stage.id not in await standings_service._completed_stage_ids(session, tournament, []):
            raise refuse(
                status.HTTP_409_CONFLICT,
                "stage_not_completed",
                "Этап ещё не завершён: сыграйте все туры личной швейцарки",
            )
        if DraftFormatSettings.model_validate(tournament.draft_format_json or {}).format is not DraftFormat.SNAKE:
            raise refuse(
                status.HTTP_409_CONFLICT,
                "draft_format_not_snake",
                "Плей-офф после личной швейцарки играется змейкой: переключите формат драфта турнира на «змейка»",
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
        dropped = [row.registration_id for row in rows if not row.is_qualified and row.registration_id is not None]
        if dropped:
            await lifecycle_service.bulk_set_balancer_status(
                session,
                stage.tournament_id,
                dropped,
                balancer_status=EXCLUDED_BALANCER_STATUS,
                exclude_reason=NOT_QUALIFIED_REASON,
            )
            await emit_balancer_registrations_changed(session, stage.tournament_id, actor_user_id=actor_user_id)
        await session.commit()
        try:
            await tournament_service.transition_status(session, stage.tournament_id, enums.TournamentStatus.DRAFT)
        except Exception:
            await session.rollback()
            stage.qualification_locked_at = None
            await session.commit()
            raise

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
