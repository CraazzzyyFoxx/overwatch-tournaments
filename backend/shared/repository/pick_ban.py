"""Pick/ban CRUD: config, session, entry, submission, readiness."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.strategy_options import _AbstractLoad

from shared import models
from shared.repository.base import BaseRepository

# Both pool shapes must be loaded before an async caller reads candidates.
CONFIG_POOL_LOAD = (
    selectinload(models.PickBanConfig.items),
    selectinload(models.PickBanConfig.slots).selectinload(models.PickBanConfigSlot.items),
)

# What a room plays: the same pool without the mode items a map pool may name (they restrict ingested logs, never a
# veto), so a pool of only modes reads as a rules template. Loader criteria apply to a collection when it is loaded:
# a config already loaded whole in the same session keeps its modes, so room paths never share a session with the
# editor's CONFIG_POOL_LOAD.
CONFIG_ROOM_LOAD = (
    selectinload(
        models.PickBanConfig.items.and_(
            models.PickBanConfigItem.item_id.not_in(
                sa.select(models.CatalogEntity.id).where(models.CatalogEntity.kind == "mode")
            )
        )
    ),
    selectinload(models.PickBanConfig.slots).selectinload(models.PickBanConfigSlot.items),
)


class PickBanConfigRepository(BaseRepository[models.PickBanConfig]):
    def __init__(self) -> None:
        super().__init__(models.PickBanConfig)

    async def find_for_stage_round(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        kind: Any,
        stage_id: int | None,
        round: int | None,
        third_place: bool = False,
        options: Sequence[_AbstractLoad] | None = None,
    ) -> models.PickBanConfig | None:
        """Exact-scope lookup: the config bound to this (stage, round, third_place) triple.

        ``stage_id``/``round`` are matched with ``IS NULL`` semantics rather than
        ``= NULL`` so a tournament-wide config (both columns NULL) is findable.
        """
        query = self._apply_options(
            self.select().where(
                models.PickBanConfig.tournament_id == tournament_id,
                models.PickBanConfig.kind == kind,
                models.PickBanConfig.stage_id.is_(stage_id)
                if stage_id is None
                else models.PickBanConfig.stage_id == stage_id,
                models.PickBanConfig.round.is_(round) if round is None else models.PickBanConfig.round == round,
                models.PickBanConfig.third_place == third_place,
            ),
            options,
        )
        result = await session.execute(query)
        return result.unique().scalars().first()

    async def list_for_stages(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        kind: Any,
        stage_ids: Sequence[int],
        options: Sequence[_AbstractLoad] | None = None,
    ) -> Sequence[models.PickBanConfig]:
        """Every config bound to any of these stages, ignoring ``round`` entirely.

        Distinct from :meth:`find_for_stage_round` on purpose: stage merging must see
        *all* configs on a stage (the caller asserts there is at most one and raises 409
        otherwise), so adding a ``round`` predicate here would silently narrow the
        conflict check and let a duplicate through the merge.
        """
        if not stage_ids:
            return []
        query = self._apply_options(
            self.select().where(
                models.PickBanConfig.tournament_id == tournament_id,
                models.PickBanConfig.kind == kind,
                models.PickBanConfig.stage_id.in_(tuple(stage_ids)),
            ),
            options,
        )
        result = await session.execute(query)
        return result.unique().scalars().all()

    async def list_by_tournament(
        self,
        session: AsyncSession,
        tournament_id: int,
        *,
        kind: Any | None = None,
        options: Sequence[_AbstractLoad] | None = None,
    ) -> Sequence[models.PickBanConfig]:
        filters: list[sa.ColumnElement[bool]] = [models.PickBanConfig.tournament_id == tournament_id]
        if kind is not None:
            filters.append(models.PickBanConfig.kind == kind)
        query = self._apply_options(self.select().where(*filters), options)
        result = await session.execute(query)
        return result.unique().scalars().all()


class PickBanConfigItemRepository(BaseRepository[models.PickBanConfigItem]):
    def __init__(self) -> None:
        super().__init__(models.PickBanConfigItem)


class PickBanConfigSlotRepository(BaseRepository[models.PickBanConfigSlot]):
    def __init__(self) -> None:
        super().__init__(models.PickBanConfigSlot)


class PickBanConfigSlotItemRepository(BaseRepository[models.PickBanConfigSlotItem]):
    def __init__(self) -> None:
        super().__init__(models.PickBanConfigSlotItem)


class PickBanSessionRepository(BaseRepository[models.PickBanSession]):
    def __init__(self) -> None:
        super().__init__(models.PickBanSession)

    def add(self, session: AsyncSession, row: models.PickBanSession) -> models.PickBanSession:
        """Stage a new session. No flush: a duplicate ``(encounter, kind)`` must surface
        at the caller's commit, which treats it as a lost creation race."""
        session.add(row)
        return row

    async def get_for_encounter(
        self,
        session: AsyncSession,
        *,
        encounter_id: int,
        kind: Any,
        options: Sequence[_AbstractLoad] | None = None,
        for_update: bool = False,
    ) -> models.PickBanSession | None:
        """The pick/ban session for one (encounter, kind).

        ``for_update`` is THE step lock: every action that advances the sequence takes
        it so two concurrent picks cannot both read the same step as current.
        ``populate_existing`` rides with the lock deliberately — without it the locked
        row would be served from the identity map at whatever version this session
        first loaded, defeating the point of taking the lock.
        """
        query = self._apply_options(
            self.select().where(
                models.PickBanSession.encounter_id == encounter_id,
                models.PickBanSession.kind == kind,
            ),
            options,
        )
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        result = await session.execute(query)
        return result.unique().scalars().first()

    async def lock_by_id(
        self,
        session: AsyncSession,
        session_id: int,
        *,
        options: Sequence[_AbstractLoad] | None = None,
    ) -> models.PickBanSession | None:
        """Same lock as ``get_for_encounter(for_update=True)``, keyed by session id.

        Used where the caller already holds the session row and needs to re-acquire it
        under lock (round advance), rather than resolving it from the encounter.
        """
        query = self._apply_options(self.select().where(models.PickBanSession.id == session_id), options)
        query = query.with_for_update().execution_options(populate_existing=True)
        result = await session.execute(query)
        return result.unique().scalars().first()

    async def delete_by_id(self, session: AsyncSession, session_id: int) -> None:
        """Statement delete — children cascade at the DB level.

        ``BaseRepository.delete`` would ORM-load every ``PickBanEntry`` of the
        session first; the FK is ``ON DELETE CASCADE``, so one statement is enough.
        """
        await session.execute(sa.delete(models.PickBanSession).where(models.PickBanSession.id == session_id))


class PickBanEntryRepository(BaseRepository[models.PickBanEntry]):
    def __init__(self) -> None:
        super().__init__(models.PickBanEntry)

    def add_many(self, session: AsyncSession, rows: Sequence[models.PickBanEntry]) -> None:
        """Stage entries. No flush: they ride the same flush as their staged session."""
        session.add_all(rows)

    async def list_by_session(
        self,
        session: AsyncSession,
        session_id: int,
        *,
        ordered: bool = False,
        populate_existing: bool = False,
        options: Sequence[_AbstractLoad] | None = None,
    ) -> Sequence[models.PickBanEntry]:
        query = self._apply_options(self.select().where(models.PickBanEntry.session_id == session_id), options)
        if ordered:
            query = query.order_by(models.PickBanEntry.order)
        if populate_existing:
            query = query.execution_options(populate_existing=True)
        result = await session.execute(query)
        return result.unique().scalars().all()

    async def list_rounds(self, session: AsyncSession, session_id: int) -> Sequence[int | None]:
        result = await session.execute(
            sa.select(models.PickBanEntry.round).where(models.PickBanEntry.session_id == session_id)
        )
        return result.scalars().all()

    async def delete_round_by_status(
        self,
        session: AsyncSession,
        *,
        session_id: int,
        round: int,
        statuses: Sequence[Any],
    ) -> None:
        await session.execute(
            sa.delete(models.PickBanEntry).where(
                models.PickBanEntry.session_id == session_id,
                models.PickBanEntry.round == round,
                models.PickBanEntry.status.in_(tuple(statuses)),
            )
        )

    async def delete_for_round(self, session: AsyncSession, *, session_id: int, round: int) -> None:
        """Every entry of one round, whatever its status — the admin correction's
        rebuild scraps a round wholesale, not just its leftovers."""
        await session.execute(
            sa.delete(models.PickBanEntry).where(
                models.PickBanEntry.session_id == session_id,
                models.PickBanEntry.round == round,
            )
        )


class PickBanSubmissionRepository(BaseRepository[models.PickBanSubmission]):
    """``pick_ban_submission`` — the action log every board state is projected from."""

    def __init__(self) -> None:
        super().__init__(models.PickBanSubmission)

    def add(self, session: AsyncSession, row: models.PickBanSubmission) -> models.PickBanSubmission:
        """Stage one submission. No flush: the caller keeps mutating it until its own flush."""
        session.add(row)
        return row

    async def list_by_session(
        self,
        session: AsyncSession,
        session_id: int,
        *,
        populate_existing: bool = False,
        options: Sequence[_AbstractLoad] | None = None,
    ) -> Sequence[models.PickBanSubmission]:
        """Every submission of the session in replay order.

        ``(step_index, attempt, encounter_team_id)`` IS the order the projection walks:
        steps in sequence order, the latest attempt last, and within one attempt the
        actors in a stable order so a blind step's duplicate merge resolves the same
        way on every recomputation. ``populate_existing`` for callers that already
        mutated rows in this transaction and must not be served the identity map's
        stale copies.
        """
        query = self._apply_options(
            self.select().where(models.PickBanSubmission.session_id == session_id),
            options,
        )
        query = query.order_by(
            models.PickBanSubmission.step_index,
            models.PickBanSubmission.attempt,
            models.PickBanSubmission.encounter_team_id,
        )
        if populate_existing:
            query = query.execution_options(populate_existing=True)
        result = await session.execute(query)
        return result.unique().scalars().all()

    async def delete_for_steps_from(self, session: AsyncSession, *, session_id: int, step_index: int) -> None:
        """Drop the log of this step and every later one.

        Used when a round is rebuilt (admin correction): the steps of the scrapped
        round are recompiled from scratch, so their submissions must go rather than
        be re-pointed at steps that may no longer mean the same thing.
        """
        await session.execute(
            sa.delete(models.PickBanSubmission).where(
                models.PickBanSubmission.session_id == session_id,
                models.PickBanSubmission.step_index >= step_index,
            )
        )


class EncounterReadinessRepository(BaseRepository[models.EncounterReadiness]):
    def __init__(self) -> None:
        super().__init__(models.EncounterReadiness)

    async def list_ready_teams(self, session: AsyncSession, encounter_id: int) -> Sequence[int]:
        """The participations that have confirmed readiness for this encounter."""
        result = await session.execute(
            sa.select(models.EncounterReadiness.encounter_team_id).where(
                models.EncounterReadiness.encounter_id == encounter_id
            )
        )
        return result.scalars().all()

    async def get_for_team(
        self, session: AsyncSession, *, encounter_id: int, encounter_team_id: int
    ) -> models.EncounterReadiness | None:
        return await self.get_by(session, encounter_id=encounter_id, encounter_team_id=encounter_team_id)

    async def delete_for_encounter(self, session: AsyncSession, encounter_id: int) -> None:
        await session.execute(
            sa.delete(models.EncounterReadiness).where(models.EncounterReadiness.encounter_id == encounter_id)
        )

    async def delete_for_team(self, session: AsyncSession, *, encounter_id: int, encounter_team_id: int) -> None:
        """Drop ONE participation's confirmation, leaving the others standing --
        the organizer's readiness override, where ``delete_for_encounter`` is
        the seat-change reset that must clear every one."""
        await session.execute(
            sa.delete(models.EncounterReadiness).where(
                models.EncounterReadiness.encounter_id == encounter_id,
                models.EncounterReadiness.encounter_team_id == encounter_team_id,
            )
        )


__all__ = (
    "EncounterReadinessRepository",
    "PickBanConfigItemRepository",
    "PickBanConfigRepository",
    "PickBanConfigSlotItemRepository",
    "PickBanConfigSlotRepository",
    "PickBanEntryRepository",
    "PickBanSessionRepository",
    "PickBanSubmissionRepository",
)
