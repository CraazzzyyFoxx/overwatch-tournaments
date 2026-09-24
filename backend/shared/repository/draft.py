from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.strategy_options import _AbstractLoad

from shared import models
from shared.core.enums import DraftPickStatus, DraftStatus
from shared.repository.base import BaseRepository

# One active draft per tournament: SETUP/READY/LIVE/PAUSED. Single source of
# truth for a tuple that used to be duplicated byte-for-byte in
# balancer-service's ``services/draft/lifecycle.py`` (``_ACTIVE_STATUSES``) and
# ``services/draft/board.py`` (``_ACTIVE``).
ACTIVE_DRAFT_STATUSES = (
    DraftStatus.SETUP.value,
    DraftStatus.READY.value,
    DraftStatus.LIVE.value,
    DraftStatus.PAUSED.value,
)


class DraftSessionRepository(BaseRepository[models.DraftSession]):
    def __init__(self) -> None:
        super().__init__(models.DraftSession)

    async def get_for_update(self, session: AsyncSession, id: int) -> models.DraftSession | None:
        """Pessimistic row lock, no eager-load: the ``_seed`` RPC handler's guard read."""
        result = await session.execute(self.select().where(self.model.id == id).with_for_update())
        return result.scalar_one_or_none()

    async def delete_by_id(self, session: AsyncSession, id: int) -> None:
        """Bulk ``DELETE ... WHERE id = :id``, no ORM cascade.

        Every child row (teams, players, roles, heroes, picks, audit events)
        hangs off the session with ``ON DELETE CASCADE`` at the DB level, so
        loading them for an ORM-level ``session.delete()`` cascade would only
        buy hundreds of round-trips for a session lifecycle service already
        planning to ``session.expunge()`` its in-memory copy.
        """
        await session.execute(sa.delete(self.model).where(self.model.id == id))

    async def exists_active_for_tournament(self, session: AsyncSession, tournament_id: int) -> bool:
        result = await session.scalar(
            sa.select(self.model.id).where(
                self.model.tournament_id == tournament_id,
                self.model.status.in_(ACTIVE_DRAFT_STATUSES),
            )
        )
        return result is not None

    async def get_active_for_tournament(self, session: AsyncSession, tournament_id: int) -> models.DraftSession | None:
        return await session.scalar(
            self.select()
            .where(self.model.tournament_id == tournament_id, self.model.status.in_(ACTIVE_DRAFT_STATUSES))
            .order_by(self.model.id.desc())
            .limit(1)
        )

    async def get_latest_for_tournament(self, session: AsyncSession, tournament_id: int) -> models.DraftSession | None:
        return await session.scalar(
            self.select().where(self.model.tournament_id == tournament_id).order_by(self.model.id.desc()).limit(1)
        )

    async def list_by_tournament(self, session: AsyncSession, tournament_id: int) -> Sequence[models.DraftSession]:
        result = await session.scalars(
            self.select().where(self.model.tournament_id == tournament_id).order_by(self.model.id.desc())
        )
        return result.all()

    async def list_live_ids(self, session: AsyncSession) -> Sequence[int]:
        result = await session.scalars(sa.select(self.model.id).where(self.model.status == DraftStatus.LIVE.value))
        return result.all()

    async def get_workspace_id(self, session: AsyncSession, id: int) -> int | None:
        return await session.scalar(sa.select(self.model.workspace_id).where(self.model.id == id))


class DraftTeamRepository(BaseRepository[models.DraftTeam]):
    def __init__(self) -> None:
        super().__init__(models.DraftTeam)

    async def list_by_session(
        self,
        session: AsyncSession,
        session_id: int,
        *,
        options: Sequence[_AbstractLoad] | None = None,
    ) -> Sequence[models.DraftTeam]:
        query = self._apply_options(
            self.select().where(self.model.session_id == session_id).order_by(self.model.draft_position.asc()),
            options,
        )
        result = await session.execute(query)
        return result.unique().scalars().all()

    async def delete_by_session(self, session: AsyncSession, session_id: int) -> None:
        await session.execute(sa.delete(self.model).where(self.model.session_id == session_id))


class DraftPlayerRepository(BaseRepository[models.DraftPlayer]):
    def __init__(self) -> None:
        super().__init__(models.DraftPlayer)

    async def list_by_session(
        self,
        session: AsyncSession,
        session_id: int,
        *,
        options: Sequence[_AbstractLoad] | None = None,
    ) -> Sequence[models.DraftPlayer]:
        query = self._apply_options(
            self.select().where(self.model.session_id == session_id).order_by(self.model.id.asc()), options
        )
        result = await session.execute(query)
        return result.unique().scalars().all()

    async def list_drafted_captains(
        self,
        session: AsyncSession,
        session_id: int,
    ) -> Sequence[models.DraftPlayer]:
        """Captains a team has drafted (``resync_pick_order``'s captain-rank seed)."""
        result = await session.scalars(
            self.select().where(
                self.model.session_id == session_id,
                self.model.is_captain.is_(True),
                self.model.drafted_by_team_id.isnot(None),
            )
        )
        return result.unique().all()

    async def get_for_update(
        self,
        session: AsyncSession,
        id: int,
        *,
        session_id: int | None = None,
        options: Sequence[_AbstractLoad] | None = None,
    ) -> models.DraftPlayer | None:
        filters: list[Any] = [self.model.id == id]
        if session_id is not None:
            filters.append(self.model.session_id == session_id)
        query = self._apply_options(self.select().where(*filters), options).with_for_update()
        result = await session.execute(query)
        return result.unique().scalar_one_or_none()

    async def delete_by_session(self, session: AsyncSession, session_id: int) -> None:
        await session.execute(sa.delete(self.model).where(self.model.session_id == session_id))


class DraftPickRepository(BaseRepository[models.DraftPick]):
    def __init__(self) -> None:
        super().__init__(models.DraftPick)

    async def list_by_session(
        self,
        session: AsyncSession,
        session_id: int,
        *,
        options: Sequence[_AbstractLoad] | None = None,
    ) -> Sequence[models.DraftPick]:
        query = self._apply_options(
            self.select().where(self.model.session_id == session_id).order_by(self.model.overall_no.asc()),
            options,
        )
        result = await session.execute(query)
        return result.unique().scalars().all()

    async def list_by_round(self, session: AsyncSession, session_id: int, round_no: int) -> Sequence[models.DraftPick]:
        result = await session.scalars(
            self.select()
            .where(self.model.session_id == session_id, self.model.round_no == round_no)
            .order_by(self.model.overall_no.asc())
        )
        return result.all()

    async def list_resolved(self, session: AsyncSession, session_id: int) -> Sequence[models.DraftPick]:
        """Picks that resolved to a player (completed or autopicked) — the frozen ``target_*`` fields are set."""
        result = await session.scalars(
            self.select().where(
                self.model.session_id == session_id,
                self.model.status.in_([DraftPickStatus.COMPLETED.value, DraftPickStatus.AUTOPICKED.value]),
            )
        )
        return result.all()

    async def first_upcoming(self, session: AsyncSession, session_id: int) -> models.DraftPick | None:
        return await session.scalar(
            self.select()
            .where(self.model.session_id == session_id, self.model.status == DraftPickStatus.UPCOMING.value)
            .order_by(self.model.overall_no.asc())
            .limit(1)
        )

    async def next_upcoming_locked(self, session: AsyncSession, session_id: int) -> models.DraftPick | None:
        """The next UPCOMING pick, row-locked (``skip_locked``) for the advance step."""
        return await session.scalar(
            self.select()
            .where(self.model.session_id == session_id, self.model.status == DraftPickStatus.UPCOMING.value)
            .order_by(self.model.overall_no.asc())
            .with_for_update(skip_locked=True)
            .limit(1)
        )

    async def seed_counts(self, session: AsyncSession, session_id: int) -> int:
        return (
            await session.scalar(
                sa.select(sa.func.count()).select_from(self.model).where(self.model.session_id == session_id)
            )
            or 0
        )

    async def finalize_if_on_clock(
        self,
        session: AsyncSession,
        pick_id: int,
        *,
        expected_version: int,
        status: DraftPickStatus,
        player_id: int | None,
        picked_by_member_id: int | None,
        is_autopick: bool,
        is_admin_override: bool,
    ) -> bool:
        """Atomic conditional finalize. Returns True iff this writer won the race.

        The WHERE (id, version, status='on_clock') guard plus the rowcount check
        IS the entire concurrency-safety mechanism for pick resolution — do not
        replace this with a generic ``update()`` that drops the guard or the
        rowcount-based winner determination.
        """
        result = await session.execute(
            sa.update(self.model)
            .where(
                self.model.id == pick_id,
                self.model.version == expected_version,
                self.model.status == DraftPickStatus.ON_CLOCK.value,
            )
            .values(
                status=status.value,
                picked_player_id=player_id,
                picked_by_workspace_member_id=picked_by_member_id,
                is_autopick=is_autopick,
                is_admin_override=is_admin_override,
                version=self.model.version + 1,
            )
            # Explicitly sync the identity-mapped pick in Python so callers can
            # read the finalized fields without a refresh round-trip afterwards.
            .execution_options(synchronize_session="evaluate")
        )
        return result.rowcount == 1

    async def delete_by_session(self, session: AsyncSession, session_id: int) -> None:
        await session.execute(sa.delete(self.model).where(self.model.session_id == session_id))

    async def get_workspace_id(self, session: AsyncSession, id: int) -> int | None:
        return await session.scalar(
            sa.select(models.DraftSession.workspace_id)
            .join(self.model, self.model.session_id == models.DraftSession.id)
            .where(self.model.id == id)
        )


class DraftAuditEventRepository(BaseRepository[models.DraftAuditEvent]):
    def __init__(self) -> None:
        super().__init__(models.DraftAuditEvent)

    async def list_with_actor(
        self, session: AsyncSession, session_id: int, *, limit: int
    ) -> Sequence[tuple[models.DraftAuditEvent, str | None]]:
        """The organizer journal: newest first, each row with its actor's name.

        LEFT OUTER, never INNER: a system/clock action has no actor at all, and a
        deleted account must not erase the row that says what it did.
        """
        result = await session.execute(
            sa.select(self.model, models.AuthUser.username)
            .outerjoin(models.AuthUser, models.AuthUser.id == self.model.actor_auth_user_id)
            .where(self.model.session_id == session_id)
            .order_by(self.model.created_at.desc(), self.model.id.desc())
            .limit(limit)
        )
        return result.tuples().all()
