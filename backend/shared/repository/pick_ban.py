"""Pick/ban CRUD: config, session, entry, ledger, readiness."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.strategy_options import _AbstractLoad

from shared import models
from shared.repository.base import BaseRepository


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
        options: Sequence[_AbstractLoad] | None = None,
    ) -> models.PickBanConfig | None:
        """Exact-scope lookup: the config bound to this (stage, round) pair.

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

    async def delete_for_config(self, session: AsyncSession, config_id: int) -> None:
        await session.execute(
            sa.delete(models.PickBanConfigItem).where(models.PickBanConfigItem.pick_ban_config_id == config_id)
        )


class PickBanConfigSlotRepository(BaseRepository[models.PickBanConfigSlot]):
    def __init__(self) -> None:
        super().__init__(models.PickBanConfigSlot)

    async def delete_for_config(self, session: AsyncSession, config_id: int) -> None:
        await session.execute(
            sa.delete(models.PickBanConfigSlot).where(models.PickBanConfigSlot.pick_ban_config_id == config_id)
        )


class PickBanConfigSlotItemRepository(BaseRepository[models.PickBanConfigSlotItem]):
    def __init__(self) -> None:
        super().__init__(models.PickBanConfigSlotItem)


class PickBanSessionRepository(BaseRepository[models.PickBanSession]):
    def __init__(self) -> None:
        super().__init__(models.PickBanSession)

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

    async def list_by_status(
        self,
        session: AsyncSession,
        session_id: int,
        statuses: Sequence[Any],
        *,
        options: Sequence[_AbstractLoad] | None = None,
    ) -> Sequence[models.PickBanEntry]:
        query = self._apply_options(
            self.select().where(
                models.PickBanEntry.session_id == session_id,
                models.PickBanEntry.status.in_(tuple(statuses)),
            ),
            options,
        )
        result = await session.execute(query)
        return result.unique().scalars().all()

    async def list_rounds(self, session: AsyncSession, session_id: int) -> Sequence[int | None]:
        result = await session.execute(
            sa.select(models.PickBanEntry.round).where(models.PickBanEntry.session_id == session_id)
        )
        return result.scalars().all()

    async def list_order_tuples(
        self, session: AsyncSession, session_id: int
    ) -> Sequence[sa.Row[tuple[int, int | None, int]]]:
        result = await session.execute(
            sa.select(
                models.PickBanEntry.order,
                models.PickBanEntry.action_index,
                models.PickBanEntry.item_id,
            ).where(models.PickBanEntry.session_id == session_id)
        )
        return result.all()

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


class EncounterPickBanLedgerRepository(BaseRepository[models.EncounterPickBanLedger]):
    """``encounter_pick_ban_ledger`` — cross-round already-banned memory."""

    def __init__(self) -> None:
        super().__init__(models.EncounterPickBanLedger)

    async def list_for_encounter(
        self,
        session: AsyncSession,
        *,
        encounter_id: int,
        kind: Any,
    ) -> Sequence[models.EncounterPickBanLedger]:
        result = await session.execute(
            self.select().where(
                models.EncounterPickBanLedger.encounter_id == encounter_id,
                models.EncounterPickBanLedger.kind == kind,
            )
        )
        return result.scalars().all()

    async def list_item_ids(
        self,
        session: AsyncSession,
        *,
        encounter_id: int,
        kind: Any,
        filters: Sequence[sa.ColumnElement[bool]] | None = None,
    ) -> Sequence[int]:
        query = sa.select(models.EncounterPickBanLedger.item_id).where(
            models.EncounterPickBanLedger.encounter_id == encounter_id,
            models.EncounterPickBanLedger.kind == kind,
        )
        query = self._apply_filters(query, filters)
        result = await session.execute(query)
        return result.scalars().all()

    async def delete_for_encounter(
        self,
        session: AsyncSession,
        *,
        encounter_id: int,
        kind: Any,
        filters: Sequence[sa.ColumnElement[bool]] | None = None,
    ) -> None:
        statement = sa.delete(models.EncounterPickBanLedger).where(
            models.EncounterPickBanLedger.encounter_id == encounter_id,
            models.EncounterPickBanLedger.kind == kind,
        )
        if filters:
            statement = statement.where(*filters)
        await session.execute(statement)


class EncounterReadinessRepository(BaseRepository[models.EncounterReadiness]):
    def __init__(self) -> None:
        super().__init__(models.EncounterReadiness)

    async def list_sides(self, session: AsyncSession, encounter_id: int) -> Sequence[str]:
        result = await session.execute(
            sa.select(models.EncounterReadiness.side).where(models.EncounterReadiness.encounter_id == encounter_id)
        )
        return result.scalars().all()

    async def get_for_side(
        self, session: AsyncSession, *, encounter_id: int, side: str
    ) -> models.EncounterReadiness | None:
        return await self.get_by(session, encounter_id=encounter_id, side=side)

    async def delete_for_encounter(self, session: AsyncSession, encounter_id: int) -> None:
        await session.execute(
            sa.delete(models.EncounterReadiness).where(models.EncounterReadiness.encounter_id == encounter_id)
        )


__all__ = (
    "EncounterPickBanLedgerRepository",
    "EncounterReadinessRepository",
    "PickBanConfigItemRepository",
    "PickBanConfigRepository",
    "PickBanConfigSlotItemRepository",
    "PickBanConfigSlotRepository",
    "PickBanEntryRepository",
    "PickBanSessionRepository",
)
