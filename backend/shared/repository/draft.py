from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.strategy_options import _AbstractLoad

from shared import models
from shared.core.enums import DraftPickStatus, DraftPlayerStatus, DraftStatus
from shared.repository.base import BaseRepository

# One active draft per tournament: SETUP/READY/LIVE/PAUSED.
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

    async def exists_active_for_formation_node(self, session: AsyncSession, formation_node_id: int) -> bool:
        result = await session.scalar(
            sa.select(self.model.id).where(
                self.model.formation_node_id == formation_node_id,
                self.model.status.in_(ACTIVE_DRAFT_STATUSES),
            )
        )
        return result is not None

    async def get_active_for_formation_node(
        self, session: AsyncSession, formation_node_id: int
    ) -> models.DraftSession | None:
        return await session.scalar(
            self.select()
            .where(self.model.formation_node_id == formation_node_id, self.model.status.in_(ACTIVE_DRAFT_STATUSES))
            .order_by(self.model.id.desc())
            .limit(1)
        )

    async def get_latest_for_formation_node(
        self, session: AsyncSession, formation_node_id: int
    ) -> models.DraftSession | None:
        return await session.scalar(
            self.select()
            .where(self.model.formation_node_id == formation_node_id)
            .order_by(self.model.id.desc())
            .limit(1)
        )

    async def list_by_formation_node(
        self, session: AsyncSession, formation_node_id: int
    ) -> Sequence[models.DraftSession]:
        result = await session.scalars(
            self.select().where(self.model.formation_node_id == formation_node_id).order_by(self.model.id.desc())
        )
        return result.all()

    async def list_live_ids(self, session: AsyncSession) -> Sequence[int]:
        result = await session.scalars(sa.select(self.model.id).where(self.model.status == DraftStatus.LIVE.value))
        return result.all()

    async def active_for_custom_game(self, session: AsyncSession, custom_game_id: int) -> Sequence[models.DraftSession]:
        """Every active draft of a mix, one per lobby at most."""
        result = await session.scalars(
            self.select().where(
                self.model.custom_game_id == custom_game_id, self.model.status.in_(ACTIVE_DRAFT_STATUSES)
            )
        )
        return result.all()

    async def active_lobby_pools(
        self, session: AsyncSession, custom_game_id: int
    ) -> dict[int, tuple[int, str, frozenset[int]]]:
        """Each drafting lobby of a mix: its session, that session's status and the members its draft holds.

        The one definition of draft membership (spec §9.2, §9.5) every "who is in which lobby" read uses: every seat
        but an unpicked one whose player stepped away -- they left the pool -- while a picked seat stays history.
        """
        player = models.DraftPlayer
        row = models.CustomGamePlayer
        rows = (
            await session.execute(
                sa.select(self.model.lobby_index, self.model.id, self.model.status, player.workspace_member_id)
                .join(player, player.session_id == self.model.id, isouter=True)
                .join(
                    row,
                    sa.and_(
                        row.custom_game_id == self.model.custom_game_id,
                        row.workspace_member_id == player.workspace_member_id,
                    ),
                    isouter=True,
                )
                .where(self.model.custom_game_id == custom_game_id, self.model.status.in_(ACTIVE_DRAFT_STATUSES))
                .where(
                    sa.or_(
                        player.status.is_(None),
                        player.status != DraftPlayerStatus.AVAILABLE.value,
                        row.away.is_not(True),
                    )
                )
            )
        ).all()
        found: dict[int, tuple[int, str, set[int]]] = {}
        for lobby_index, session_id, status, member_id in rows:
            entry = found.setdefault(lobby_index, (session_id, status, set()))
            if member_id is not None:
                entry[2].add(member_id)
        return {
            index: (session_id, status, frozenset(members)) for index, (session_id, status, members) in found.items()
        }

    async def first_clock_starts(self, session: AsyncSession, session_ids: Sequence[int]) -> dict[int, datetime]:
        """When each of these drafts went live: its first pick's clock start. A draft not started yet has none."""
        pick = models.DraftPick
        rows = await session.execute(
            sa.select(pick.session_id, pick.clock_started_at).where(
                pick.session_id.in_(session_ids), pick.overall_no == 1, pick.clock_started_at.is_not(None)
            )
        )
        return dict(rows.tuples().all())

    async def get_workspace_id_in_tournament(self, session: AsyncSession, id: int, *, tournament_id: int) -> int | None:
        """The session's workspace, or ``None`` unless the session exists AND belongs to ``tournament_id``."""
        return await session.scalar(
            sa.select(self.model.workspace_id).where(self.model.id == id, self.model.tournament_id == tournament_id)
        )

    async def seed_row_counts(self, session: AsyncSession, session_id: int) -> tuple[int, int, int]:
        """``(teams, players, picks)`` row counts of a session, as three scalar subqueries in one round trip."""
        row = (
            await session.execute(
                sa.select(
                    *(
                        sa.select(sa.func.count())
                        .select_from(model)
                        .where(model.session_id == session_id)
                        .scalar_subquery()
                        for model in (models.DraftTeam, models.DraftPlayer, models.DraftPick)
                    )
                )
            )
        ).one()
        return int(row[0] or 0), int(row[1] or 0), int(row[2] or 0)


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
        query = self._apply_options(self.select().where(*filters), options).with_for_update(of=self.model)
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
            .with_for_update(skip_locked=True, of=self.model)
            .limit(1)
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

    async def last_resolved(self, session: AsyncSession, session_id: int) -> models.DraftPick | None:
        """The most recent pick that resolved: completed, autopicked or skipped."""
        return await session.scalar(
            self.select()
            .where(
                self.model.session_id == session_id,
                self.model.status.in_(
                    [
                        DraftPickStatus.COMPLETED.value,
                        DraftPickStatus.AUTOPICKED.value,
                        DraftPickStatus.SKIPPED.value,
                    ]
                ),
            )
            .order_by(self.model.overall_no.desc())
            .limit(1)
        )

    async def list_from(self, session: AsyncSession, session_id: int, overall_no: int) -> Sequence[models.DraftPick]:
        """Picks at ``overall_no`` and after, in pick order."""
        result = await session.scalars(
            self.select()
            .where(self.model.session_id == session_id, self.model.overall_no >= overall_no)
            .order_by(self.model.overall_no.asc())
        )
        return result.all()


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
