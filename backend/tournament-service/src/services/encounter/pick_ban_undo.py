"""Undo the last pick-ban action, once BOTH captains have agreed to it.

A captain who banned the wrong hero used to have one way out: ask an organizer
to reset the session, scrapping the whole round. This is the captains' own,
surgical alternative -- and it is deliberately a two-sided consent rather than a
unilateral take-back, because the last action is information the opponent has
already acted on. Same shape as the two other agreements this room runs on
(``EncounterReadiness``, ``EncounterMapReport``): one side records its consent,
the other side's matching call is what applies it.

What "the last action" means -- and when there is none -- is
``pick_ban_engine.undoable_entries``: the newest committed entry plus any
``decider`` the engine resolved off the back of it, refused outright once the
round has been played or a later round has opened.

Reverting is the exact inverse of ``pick_ban_action.apply_pick_ban_action``:
the entries go back to ``available`` with their action bookkeeping cleared, a
ban's cross-round ledger row is deleted, a completed session reopens, and the
restored turn gets a fresh timer -- without that last part
``auto_resolve_timeout`` would re-take the action at random on the very next
read, the clock having long since run out on the step being restored.
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import http_status as status
from shared.core.enums import MapPoolEntryStatus, MapVetoSessionStatus, PickBanKind
from shared.core.errors import BaseAPIException as HTTPException
from shared.models.tournament.pick_ban import EncounterPickBanLedger, PickBanEntry, PickBanSession
from shared.repository import EncounterPickBanLedgerRepository, PickBanEntryRepository
from shared.services import pick_ban_engine as engine
from src.services.encounter.pick_ban_session import PickBanSessionService, pick_ban_session_service
from src.services.encounter.realtime_commit import emit_pick_ban_update


def clear_undo_request(pick_ban: PickBanSession) -> None:
    """Drop any open request. Called on every new action as well as after an
    undo lands: a consent is given for ONE specific action, so it must never
    outlive the pool state it was read against."""
    pick_ban.undo_requested_by = None
    pick_ban.undo_target_index = None


def undo_state(pick_ban: PickBanSession | None, pool: list[PickBanEntry]) -> dict:
    """The room's undo block: what an undo would revert right now, and who has
    already agreed to it.

    ``item_ids`` empty means nothing is undoable -- the single signal the UI
    needs to decide whether the affordance exists at all. ``requested_by`` is
    reported only while it still matches the action in play; a request left
    behind by a since-superseded action reads as no request, exactly as the
    consent check itself treats it.
    """
    entries = engine.undoable_entries(pool)
    if not entries:
        return {"requested_by": None, "item_ids": [], "action": None, "side": None}
    primary = entries[-1]
    requested_by = (
        pick_ban.undo_requested_by
        if pick_ban is not None and pick_ban.undo_target_index == entries[0].action_index
        else None
    )
    return {
        "requested_by": requested_by,
        # Play order, so the UI lists them the way they were committed.
        "item_ids": [entry.item_id for entry in reversed(entries)],
        "action": _action_of(primary),
        "side": primary.picked_by or primary.protected_by,
    }


def _action_of(entry: PickBanEntry) -> str:
    if entry.status == MapPoolEntryStatus.BANNED.value:
        return "ban"
    if entry.status == MapPoolEntryStatus.PROTECTED.value:
        return "protect"
    return "pick"


def ledger_keys(entries: list[PickBanEntry]) -> list[tuple[int, str]]:
    """``(item_id, side)`` per undone action that wrote cross-round ban memory.

    Read BEFORE ``apply_undo``, which clears the very fields this reads. Only
    bans are in the ledger at all (a protect is round-local, by design), and a
    decider pick never wrote one.
    """
    return [
        (entry.item_id, entry.picked_by)
        for entry in entries
        if entry.status == MapPoolEntryStatus.BANNED.value and entry.picked_by is not None
    ]


def apply_undo(pick_ban: PickBanSession, entries: list[PickBanEntry], *, now: datetime) -> None:
    """Pure step: revert `entries` and reopen the step that produced them."""
    for entry in entries:
        entry.status = MapPoolEntryStatus.AVAILABLE.value
        entry.picked_by = None
        entry.protected_by = None
        entry.action_index = None
    clear_undo_request(pick_ban)
    # A completed session ran out of sequence, which an undo puts back -- a
    # cancelled one is a different thing entirely and never gets here.
    if pick_ban.status == MapVetoSessionStatus.COMPLETED.value:
        pick_ban.status = MapVetoSessionStatus.ACTIVE.value
    pick_ban.current_step_started_at = now


class PickBanUndoService:
    def __init__(
        self,
        *,
        entry_repo: PickBanEntryRepository = PickBanEntryRepository(),
        ledger_repo: EncounterPickBanLedgerRepository = EncounterPickBanLedgerRepository(),
        sessions: PickBanSessionService = pick_ban_session_service,
    ) -> None:
        self.entry_repo = entry_repo
        self.ledger_repo = ledger_repo
        self.sessions = sessions

    async def perform_undo(
        self,
        session: AsyncSession,
        encounter_id: int,
        kind: PickBanKind,
        captain_side: str,
        *,
        consent: bool = True,
    ) -> dict:
        """Record ``captain_side``'s consent to undo the last action, applying it
        the moment both sides have given it. ``consent=False`` withdraws an open
        request (either side may: the asker changes their mind, or the opponent
        refuses).

        Returns the resulting undo block, so the caller renders the outcome without
        a second read.
        """
        # Same lock every committing path takes: an undo REMOVES a committed entry,
        # which moves the step cursor exactly as taking one does, and the consent
        # it reads (`undo_target_index`) is compared against the pool it loads
        # below (see `pick_ban_session.get_pick_ban_session`).
        pick_ban = await self.sessions.get_pick_ban_session(session, encounter_id, kind, for_update=True)
        if pick_ban is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Pick-ban session is not initialized")
        if pick_ban.status == MapVetoSessionStatus.CANCELLED.value:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Pick-ban session is cancelled")

        pool = await self._load_pool(session, pick_ban.id, refresh=True)
        entries = engine.undoable_entries(pool)
        if not entries:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="There is no action left to undo")
        target_index = entries[0].action_index
        if kind == PickBanKind.MAP:
            await self._assert_hero_round_unstarted(session, encounter_id, entries[-1].round)

        if not consent:
            clear_undo_request(pick_ban)
        else:
            # A request standing against a DIFFERENT action is stale, not an
            # agreement -- this call then opens a fresh one instead of applying it.
            pending_side = pick_ban.undo_requested_by if pick_ban.undo_target_index == target_index else None
            if pending_side is None or pending_side == captain_side:
                pick_ban.undo_requested_by = captain_side
                pick_ban.undo_target_index = target_index
            else:
                keys = ledger_keys(entries)
                apply_undo(pick_ban, entries, now=datetime.now(UTC))
                await self._forget_ledger_rows(session, encounter_id, kind, keys)

        await emit_pick_ban_update(session, encounter_id, kind=kind.value)
        await session.commit()
        return undo_state(pick_ban, pool)

    async def _load_pool(self, session: AsyncSession, pick_ban_id: int, *, refresh: bool = False) -> list[PickBanEntry]:
        """The session's entries; ``refresh`` discards a pre-lock snapshot already
        sitting in the identity map."""
        return list(
            await self.entry_repo.list_by_session(session, pick_ban_id, ordered=True, populate_existing=refresh)
        )

    async def _assert_hero_round_unstarted(
        self, session: AsyncSession, encounter_id: int, round_number: int | None
    ) -> None:
        """Refuse to undo a MAP action once heroes have been banned for that round.

        A hero round opens off the map pick (``sync_hero_rounds``) and is never
        withdrawn, so taking the pick back with bans already committed against it
        would leave those bans attached to a map nobody has picked. The captains'
        way through is the composable one: undo the hero actions first (they are the
        last actions of THEIR session), then the map pick — reverted hero entries no
        longer count as committed, so this releases on its own.
        """
        hero_session = await self.sessions.get_pick_ban_session(session, encounter_id, PickBanKind.HERO)
        if hero_session is None:
            return
        # Grouped count with a conditional round predicate, not a CRUD read: stays
        # here rather than becoming a repository method.
        committed = await session.scalar(
            select(sa.func.count())
            .select_from(PickBanEntry)
            .where(
                PickBanEntry.session_id == hero_session.id,
                PickBanEntry.action_index.is_not(None),
                PickBanEntry.round == round_number if round_number is not None else sa.true(),
            )
        )
        if committed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Undo this round's hero bans first — they were made for the map you are taking back",
            )

    async def _forget_ledger_rows(
        self, session: AsyncSession, encounter_id: int, kind: PickBanKind, keys: list[tuple[int, str]]
    ) -> None:
        """Delete the cross-round ban memory the undone bans wrote.

        Ledger rows are keyed by ``(encounter, kind, item_id, banned_by_side)`` --
        the same tuple the reverted entry carried -- so this removes exactly what
        those actions added and nothing an earlier round put there. A ledger-less
        config (``no_repeat_scope=none``) simply has no matching row.
        """
        for item_id, side in keys:
            await self.ledger_repo.delete_for_encounter(
                session,
                encounter_id=encounter_id,
                kind=kind,
                filters=[
                    EncounterPickBanLedger.item_id == item_id,
                    EncounterPickBanLedger.banned_by_side == side,
                ],
            )


pick_ban_undo_service = PickBanUndoService()
