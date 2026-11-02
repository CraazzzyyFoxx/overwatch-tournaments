"""The qualification lock: trim the balancer pool to the qualifiers and open the playoff draft."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums
from shared.core import http_status as status
from shared.repository import StageRepository, TournamentRepository
from src.schemas import individual_swiss as swiss_schemas
from src.services.admin.tournament import tournament_service
from src.services.individual_swiss.pins import refuse
from src.services.individual_swiss.reads import role_order, to_player_standing_read
from src.services.registration._common import EXCLUDED_BALANCER_STATUS
from src.services.registration.lifecycle import lifecycle_service
from src.services.registration.realtime import emit_balancer_registrations_changed

__all__ = ("NOT_QUALIFIED_REASON", "IndividualSwissQualificationService", "qualification_service")

NOT_QUALIFIED_REASON = "not_qualified"

_stages = StageRepository()
_tournaments = TournamentRepository()


class IndividualSwissQualificationService:
    async def lock(
        self, session: AsyncSession, stage: models.Stage, *, actor_user_id: int | None = None
    ) -> swiss_schemas.QualificationLockRead:
        """Exclude every non-qualified player of the stage from the balancer pool, then move LIVE -> DRAFT.

        The draft pool is what the balancer still counts in, so after this it is exactly the qualifiers. Commits.

        # shortcut: the exclusion and the status change commit one after the other (both services commit);
        # a failure between them leaves the pool trimmed in LIVE, and the same call finishes it. Upgrade to one
        # transaction if the status change ever gains a way to fail late.
        """
        if stage.stage_type != enums.StageType.INDIVIDUAL_SWISS:
            raise refuse(status.HTTP_409_CONFLICT, "not_individual_swiss", "Это не этап личной швейцарки")
        # The tournament row serializes two organizers locking at once: the loser sees DRAFT and is refused.
        tournament = await _tournaments.get(session, stage.tournament_id, for_update=True, populate_existing=True)
        stage = await _stages.get(session, stage.id, populate_existing=True) or stage
        if tournament is None or tournament.status != enums.TournamentStatus.LIVE:
            raise refuse(
                status.HTTP_409_CONFLICT,
                "qualification_not_live",
                "Квалификацию можно закрепить только пока турнир идёт (LIVE), и только один раз",
            )
        if not stage.is_completed:
            raise refuse(
                status.HTTP_409_CONFLICT,
                "stage_not_completed",
                "Этап ещё не завершён: сыграйте все туры личной швейцарки",
            )
        rows = list(
            (await session.execute(sa.select(models.PlayerStanding).where(models.PlayerStanding.stage_id == stage.id)))
            .scalars()
            .all()
        )
        if not any(row.is_qualified for row in rows):
            raise refuse(status.HTTP_409_CONFLICT, "no_qualifiers", "В таблице этапа нет квалифицировавшихся игроков")

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
        await tournament_service.transition_status(session, stage.tournament_id, enums.TournamentStatus.DRAFT)

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
