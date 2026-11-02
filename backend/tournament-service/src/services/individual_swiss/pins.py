"""The organizer's manual places in an ``individual_swiss`` stage's personal table."""

from __future__ import annotations

from collections import Counter

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums
from shared.core import http_status as status
from shared.core.errors import ApiExc, ApiHTTPException
from shared.repository import PlayerStandingPinRepository
from src.schemas import individual_swiss as swiss_schemas
from src.services.computation.jobs import jobs_service

__all__ = ("IndividualSwissPinsService", "pins_service", "refuse")

#: Once the tournament has left the Swiss day the qualifier list is frozen, so a pin could only contradict it.
_LOCKED_STATUSES = frozenset(
    {
        enums.TournamentStatus.DRAFT,
        enums.TournamentStatus.PLAYOFFS,
        enums.TournamentStatus.COMPLETED,
        enums.TournamentStatus.ARCHIVED,
    }
)


def refuse(http_status: int, code: str, message: str) -> ApiHTTPException:
    """The error shape the frontend's ``parseApiError`` reads: one coded item with the organizer's sentence."""
    return ApiHTTPException(status_code=http_status, detail=[ApiExc(code=code, msg=message)])


class IndividualSwissPinsService:
    def __init__(self, *, pin_repo: PlayerStandingPinRepository = PlayerStandingPinRepository()) -> None:
        self.pin_repo = pin_repo

    async def get_pins(self, session: AsyncSession, stage_id: int) -> dict[int, int]:
        """``workspace_member_id -> position``."""
        result = await session.execute(
            sa.select(models.PlayerStandingPin.workspace_member_id, models.PlayerStandingPin.position).where(
                models.PlayerStandingPin.stage_id == stage_id
            )
        )
        return dict(result.tuples().all())

    async def set_pins(
        self,
        session: AsyncSession,
        stage: models.Stage,
        data: swiss_schemas.PlayerStandingPinsUpdate,
        *,
        requested_by_user_id: int | None = None,
    ) -> swiss_schemas.PlayerStandingPinsRead:
        """Replace every pin of the stage and schedule the recalculation that applies them. Commits.

        A position is a place inside the player's role, so it is unique per role and cannot pass the role's size;
        the frozen pool (``PlayerStanding``) is the authority on who is in the stage and in which role.
        """
        if stage.stage_type != enums.StageType.INDIVIDUAL_SWISS:
            raise refuse(status.HTTP_422_UNPROCESSABLE_ENTITY, "not_individual_swiss", "Это не этап личной швейцарки")
        # Serializes concurrent edits of one stage: each replaces the whole set, so two interleaved replaces would
        # collide on the unique index.
        await session.execute(sa.select(models.Stage.id).where(models.Stage.id == stage.id).with_for_update())
        locked_at = await session.scalar(
            sa.select(models.Stage.qualification_locked_at)
            .where(models.Stage.id == stage.id)
            .execution_options(populate_existing=True)
        )
        tournament_status = await session.scalar(
            sa.select(models.Tournament.status).where(models.Tournament.id == stage.tournament_id)
        )
        if locked_at is not None or tournament_status in _LOCKED_STATUSES:
            raise refuse(status.HTTP_409_CONFLICT, "qualification_locked", "Квалификация уже закреплена")

        result = await session.execute(
            sa.select(models.PlayerStanding.workspace_member_id, models.PlayerStanding.role).where(
                models.PlayerStanding.stage_id == stage.id
            )
        )
        role_of = dict(result.tuples().all())
        if not role_of:
            raise refuse(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "no_player_table", "Таблица этапа ещё не создана: запустите этап"
            )

        members = [pin.workspace_member_id for pin in data.pins]
        repeated = sorted(member for member, count in Counter(members).items() if count > 1)
        if repeated:
            raise refuse(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "pin_duplicate_player", f"Игроки {repeated} закреплены дважды"
            )
        strangers = sorted(set(members) - role_of.keys())
        if strangers:
            raise refuse(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "pin_unknown_player", f"Игроков {strangers} нет в таблице этапа"
            )
        role_size = Counter(role_of.values())
        for pin in data.pins:
            role = role_of[pin.workspace_member_id]
            if pin.position > role_size[role]:
                raise refuse(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "pin_position_out_of_range",
                    f"В роли {role} {role_size[role]} мест, а игрок {pin.workspace_member_id} закреплён на {pin.position}",
                )
        taken = Counter((role_of[pin.workspace_member_id], pin.position) for pin in data.pins)
        clash = sorted(f"{role} #{position}" for (role, position), count in taken.items() if count > 1)
        if clash:
            raise refuse(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "pin_duplicate_position",
                f"Одно место закреплено за несколькими игроками: {', '.join(clash)}",
            )

        await self.pin_repo.replace(
            session,
            stage_id=stage.id,
            pins=[
                models.PlayerStandingPin(
                    stage_id=stage.id, workspace_member_id=pin.workspace_member_id, position=pin.position
                )
                for pin in data.pins
            ],
        )
        await jobs_service.request_standings_recalculation(
            session, stage.tournament_id, requested_by_user_id=requested_by_user_id
        )
        await session.commit()
        return swiss_schemas.PlayerStandingPinsRead(
            pins=[swiss_schemas.PlayerStandingPinRead(**pin.model_dump()) for pin in data.pins]
        )


pins_service = IndividualSwissPinsService()
