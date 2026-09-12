"""Generic pick-ban action engine: generalizes ``map_veto.py``'s
``apply_veto_action``/``perform_veto_action``/``build_map_pool_state`` to run
over a :class:`~shared.models.tournament.pick_ban.PickBanSession`, any
``kind``, with the two rule additions neither rulebook could skip:
``protect`` as a third action alongside ban/pick, and an optional
role/attribute-uniqueness check within one side's actions in the active round.

Design: docs/plans/2026-08-09-generic-pickban-engine.md §5.3-§5.4.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import http_status as status
from shared.core.enums import (
    MapPickSide,
    MapPoolEntryStatus,
    MapVetoSessionStatus,
    PickBanKind,
    PickBanNoRepeatScope,
)
from shared.core.errors import BaseAPIException as HTTPException
from shared.models.catalog.hero import Hero
from shared.models.tournament.encounter import Encounter
from shared.models.tournament.pick_ban import EncounterPickBanLedger, PickBanEntry, PickBanSession
from shared.repository import (
    EncounterMapReportRepository,
    EncounterPickBanLedgerRepository,
    EncounterRepository,
    PickBanConfigRepository,
    PickBanEntryRepository,
)
from shared.services import pick_ban_engine as engine
from src.services.encounter import pick_ban_undo
from src.services.encounter.pick_ban_session import PickBanSessionService, pick_ban_session_service
from src.services.encounter.realtime_commit import emit_pick_ban_update


def auto_complete_decider_entry(sequence: list[str], pool: list[PickBanEntry]) -> PickBanEntry | None:
    """Generalizes ``map_veto.auto_complete_decider_entry``: ``slot``/
    ``current_slot`` -> ``round``/``current_round``, ``map_id`` -> ``item_id``.
    Returns ``None`` when there is no pending decider step to resolve.

    A well-formed bracket-driven config (``build_sequence_for_best_of``) bans
    and picks the round's pool down to exactly one survivor before the
    decider step, so the common case is a single candidate. But nothing
    enforces that pool size against ``best_of`` at config-upsert time, so a
    pool oversized for its series length (e.g. the full map catalog on a Bo5)
    reaches this step with several survivors still standing. Rather than 400
    the room dead for every future read — the config's mistake, not the
    captains' — resolve it the same way ``auto_resolve_timeout`` already
    resolves an abandoned captain step: pick uniformly at random among the
    survivors. Only an EMPTY round (a genuine config/data invariant
    violation — nothing at all left to award) still raises."""
    step = engine.get_current_step(sequence, pool)
    if step is None:
        return None

    _, step_action = step
    if step_action != "decider":
        return None

    active_round = engine.current_round(pool)
    available = [
        entry
        for entry in pool
        if entry.status == MapPoolEntryStatus.AVAILABLE.value and engine.in_current_round(entry, active_round)
    ]
    if not available:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Decider step has no available item",
        )

    # CSPRNG, not ``random``: this draw decides the decider map, i.e. part of a
    # competitive result. A predictable PRNG state would let a captain compute
    # the outcome in advance.
    entry = secrets.choice(available)
    entry.action_index = sum(1 for pool_entry in pool if pool_entry.status != MapPoolEntryStatus.AVAILABLE.value)
    entry.status = MapPoolEntryStatus.PICKED.value
    entry.picked_by = MapPickSide.DECIDER.value
    # The PICKED assignment above must precede this count (mirrors
    # map_veto.py's own ordering comment): counting includes this entry, so
    # ``order`` comes out 1-based.
    entry.order = sum(1 for pool_entry in pool if pool_entry.status == MapPoolEntryStatus.PICKED.value)
    return entry


def _turn_is_abandoned(pick_ban: PickBanSession | None) -> bool:
    """Whether the step in play has outlived its turn timer. A session with no
    timer configured, or a step whose clock has not started, never has."""
    if pick_ban is None or pick_ban.status != MapVetoSessionStatus.ACTIVE.value:
        return False
    if pick_ban.turn_timer_seconds is None or pick_ban.current_step_started_at is None:
        return False
    deadline = pick_ban.current_step_started_at + timedelta(seconds=pick_ban.turn_timer_seconds)
    return datetime.now(UTC) >= deadline


def serialize_pick_ban_entry(entry: PickBanEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "item_id": entry.item_id,
        "round": entry.round,
        "order": entry.order,
        "action_index": entry.action_index,
        "picked_by": entry.picked_by,
        "protected_by": entry.protected_by,
        "status": entry.status,
        "team_id": entry.team_id,
    }


def serialize_pick_ban_session(pick_ban: PickBanSession) -> dict[str, Any]:
    return {
        "id": pick_ban.id,
        "kind": pick_ban.kind,
        "status": pick_ban.status,
        "first_side": pick_ban.first_side,
        "awaiting_choice": pick_ban.awaiting_choice,
        "pending_loser_side": pick_ban.pending_loser_side,
        "seed_source": pick_ban.seed_source,
        "home_seed": pick_ban.home_seed,
        "away_seed": pick_ban.away_seed,
        "turn_timer_seconds": pick_ban.turn_timer_seconds,
        # Passthrough of the session's reserve snapshot, string-keyed by slot
        # position, gaps and reserve-less slots omitted -- see
        # pick_ban_session.ensure_pick_ban_session's slot_reserves comment.
        # Always None for kind=hero (no reserve concept there); read by
        # `PickBanGrid`'s reserve caption via `pickBanReserveMap` for kind=map.
        "slot_reserves": pick_ban.slot_reserves_json,
        "started_at": pick_ban.started_at.isoformat() if pick_ban.started_at else None,
        "current_step_started_at": (
            pick_ban.current_step_started_at.isoformat() if pick_ban.current_step_started_at else None
        ),
    }


def build_unavailable_state(reason: str, *, readiness: dict[str, bool]) -> dict[str, Any]:
    return {
        "session": None,
        "reason": reason,
        "readiness": readiness,
        "sequence": [],
        "pool": [],
        "viewer_side": None,
        "viewer_can_act": False,
        "allowed_actions": [],
        "current_step_index": None,
        "current_step": None,
        "expected_action": None,
        "turn_side": None,
        "current_round": None,
        "is_complete": False,
        "map_reports": [],
        "repeat_banned": [],
        "unique_attribute": None,
        "undo": pick_ban_undo.undo_state(None, []),
    }


def build_pick_ban_state(
    sequence: list[str],
    pool: list[PickBanEntry],
    *,
    viewer_side: str | None,
    pick_ban: PickBanSession | None,
    readiness: dict[str, bool],
    unique_attribute: str | None = None,
) -> dict[str, Any]:
    """Pure state builder — same shape as ``map_veto.build_map_pool_state``,
    generalized to pool-agnostic ``pick_ban`` sessions with `protect` steps."""
    current_step = engine.get_current_step(sequence, pool)
    current_step_value: str | None = None
    expected_action: str | None = None
    turn_side: str | None = None
    allowed_actions: list[str] = []

    if current_step is not None:
        _, current_step_value = current_step
        if current_step_value == "decider":
            expected_action = "decider"
        else:
            parsed = engine.parse_step_token(current_step_value)
            expected_action = parsed.action
            turn_side = parsed.side

        if viewer_side is not None and turn_side == viewer_side and expected_action in {"pick", "ban", "protect"}:
            allowed_actions = [expected_action]

    return {
        "session": serialize_pick_ban_session(pick_ban) if pick_ban is not None else None,
        "readiness": readiness,
        "sequence": list(sequence),
        "pool": [serialize_pick_ban_entry(entry) for entry in pool],
        "viewer_side": viewer_side,
        "viewer_can_act": bool(allowed_actions),
        "allowed_actions": allowed_actions,
        "current_step_index": current_step[0] if current_step is not None else None,
        "current_step": current_step_value,
        "expected_action": expected_action,
        "turn_side": turn_side,
        "current_round": engine.current_round(pool),
        "is_complete": current_step is None,
        # Filled in by `get_pick_ban_state` for kind=map only; a hero session
        # has no per-map results of its own to report.
        "map_reports": [],
        # Filled in below by `get_pick_ban_state` when the config remembers bans
        # per side (`no_repeat_scope=encounter_same_side`) -- see there.
        "repeat_banned": [],
        # What both captains could agree to take back right now, and whether one
        # of them already has.
        "undo": pick_ban_undo.undo_state(pick_ban, pool),
        # The configured attribute-uniqueness rule (``role`` or nothing), so the
        # room can grey out what the side on the clock may no longer take —
        # without it the only feedback is the 400 that arrives after the click.
        "unique_attribute": unique_attribute,
    }


def apply_pick_ban_action(
    pick_ban: PickBanSession,
    pool: list[PickBanEntry],
    *,
    captain_side: str,
    item_id: int,
    action: str,
    attribute_lookup: dict[int, Any],
    unique_attribute: str | None,
    excluded_for_side: frozenset[int] = frozenset(),
    now: datetime,
) -> PickBanEntry:
    """Pure step: validate and apply one ban/pick/protect. Generalizes
    ``map_veto.apply_veto_action`` with the `protect` action, the optional
    role/attribute-uniqueness check, and ``excluded_for_side``: items this side
    may not BAN again because it already banned them earlier in the series
    (``no_repeat_scope=encounter_same_side``). That scope cannot be applied
    when a round's candidate pool is built — one pool, two sides, and only one
    of them is barred — so unlike the side-blind ``encounter`` scope it is
    enforced here, per action.

    Bans and protects never restrict each other: a protect does not spend that
    side's role budget for the round and is not remembered across rounds by the
    ledger. The only thing it blocks is a `ban` on that same item, for the rest
    of the round (``engine.is_entry_bannable``).
    """
    step = engine.get_current_step(pick_ban.resolved_sequence_json, pool)
    if step is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Pick-ban sequence is already complete")

    _, step_token = step
    parsed = engine.parse_step_token(step_token)
    if action != parsed.action:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Expected action '{parsed.action}', got '{action}'"
        )
    if parsed.side and captain_side != parsed.side:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"It's {parsed.side} team's turn, not {captain_side}"
        )

    active_round = engine.current_round(pool)
    entry = next(
        (e for e in pool if e.item_id == item_id and engine.in_current_round(e, active_round)),
        None,
    )
    if entry is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Item is not a candidate this round")
    if action == "ban" and not engine.is_entry_bannable(entry, active_round=active_round):
        reason = "protected" if entry.protected_by is not None else entry.status
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Item is {reason}")
    if action in ("pick", "protect") and entry.status != MapPoolEntryStatus.AVAILABLE.value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Item is already {entry.status}")
    if action == "ban" and item_id in excluded_for_side:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Your side already banned this item earlier in the series",
        )

    if action in ("ban", "protect") and unique_attribute is not None:
        if engine.violates_unique_attribute(
            candidate_attribute=attribute_lookup.get(item_id),
            acting_side=captain_side,
            round_number=active_round,
            # `action == parsed.action` was enforced above; the parsed one is
            # the narrowly typed twin.
            committed_this_round=engine.committed_attributes(
                pool, action=parsed.action, attribute_lookup=attribute_lookup
            ),
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Your side already {'banned' if action == 'ban' else 'protected'} "
                    "an item with this attribute this round"
                ),
            )

    entry.action_index = sum(1 for e in pool if e.status != MapPoolEntryStatus.AVAILABLE.value)
    if action == "ban":
        entry.status = MapPoolEntryStatus.BANNED.value
        entry.picked_by = captain_side
    elif action == "protect":
        entry.status = MapPoolEntryStatus.PROTECTED.value
        entry.protected_by = captain_side
    elif action == "pick":
        entry.status = MapPoolEntryStatus.PICKED.value
        entry.picked_by = captain_side
        entry.order = sum(1 for e in pool if e.status == MapPoolEntryStatus.PICKED.value)

    # Any open undo consent was given against the action that WAS last; this
    # one supersedes it, so the agreement dies with the state it was read on.
    pick_ban_undo.clear_undo_request(pick_ban)
    pick_ban.current_step_started_at = now
    if engine.get_current_step(pick_ban.resolved_sequence_json, pool) is None:
        pick_ban.status = MapVetoSessionStatus.COMPLETED.value
    return entry


class PickBanActionService:
    def __init__(
        self,
        *,
        entry_repo: PickBanEntryRepository = PickBanEntryRepository(),
        config_repo: PickBanConfigRepository = PickBanConfigRepository(),
        ledger_repo: EncounterPickBanLedgerRepository = EncounterPickBanLedgerRepository(),
        encounter_repo: EncounterRepository = EncounterRepository(),
        map_report_repo: EncounterMapReportRepository = EncounterMapReportRepository(),
        sessions: PickBanSessionService = pick_ban_session_service,
    ) -> None:
        self.entry_repo = entry_repo
        self.config_repo = config_repo
        self.ledger_repo = ledger_repo
        self.encounter_repo = encounter_repo
        self.map_report_repo = map_report_repo
        self.sessions = sessions

    async def _load_pool(self, session: AsyncSession, pick_ban_id: int, *, refresh: bool = False) -> list[PickBanEntry]:
        """The session's entries. ``refresh`` re-reads rows already in the identity
        map, which every load taken AFTER locking the session must do -- the
        pre-lock snapshot is what the lock exists to discard."""
        return list(
            await self.entry_repo.list_by_session(session, pick_ban_id, ordered=True, populate_existing=refresh)
        )

    async def get_pick_ban_pool(
        self, session: AsyncSession, pick_ban: PickBanSession, encounter_id: int, kind: PickBanKind
    ) -> list[PickBanEntry]:
        """Load the pool, resolving any pending timeout/decider step first —
        mirrors ``map_veto.get_map_pool``'s side effect so every state read
        self-heals a stalled turn the same way ``perform_pick_ban_action`` does
        after an action. Timeout resolution runs first: the random pick it
        applies can itself leave a decider current, which the following call
        then resolves in the same read.

        Both resolvers decide under their own lock against their own freshly read
        pool, so anything they commit makes the snapshot below stale -- hence the
        re-read. The extra query is paid only on the read that actually healed
        something, never on the polls that find nothing to do."""
        pool = await self._load_pool(session, pick_ban.id)
        if await self.auto_resolve_timeout(session, encounter_id, kind, pick_ban=pick_ban) is not None:
            pool = await self._load_pool(session, pick_ban.id, refresh=True)
        if await self.auto_complete_decider(session, encounter_id, kind, pick_ban=pick_ban, pool=pool) is not None:
            pool = await self._load_pool(session, pick_ban.id, refresh=True)
        return pool

    async def auto_complete_decider(
        self,
        session: AsyncSession,
        encounter_id: int,
        kind: PickBanKind,
        *,
        pick_ban: PickBanSession | None = None,
        pool: list[PickBanEntry] | None = None,
    ) -> PickBanEntry | None:
        """Resolve a pending decider step from the session snapshot, if any.
        Generalizes ``map_veto.auto_complete_decider``.

        Double-checked: the snapshot the caller already holds decides whether there
        is anything here at all (the overwhelmingly common answer on a poll is no),
        and only then is the session locked and re-read. Awarding the survivor is a
        committed step like any other, so two concurrent readers resolving it would
        consume the step twice -- see `get_pick_ban_session`.
        """
        if pick_ban is None:
            pick_ban = await self.sessions.get_pick_ban_session(session, encounter_id, kind)
        if pick_ban is None or pick_ban.status != MapVetoSessionStatus.ACTIVE.value:
            return None

        if pool is None:
            pool = await self._load_pool(session, pick_ban.id)
        hint = engine.get_current_step(pick_ban.resolved_sequence_json, pool)
        if hint is None or hint[1] != "decider":
            return None

        pick_ban = await self.sessions.get_pick_ban_session(session, encounter_id, kind, for_update=True)
        if pick_ban is None or pick_ban.status != MapVetoSessionStatus.ACTIVE.value:
            return None
        pool = await self._load_pool(session, pick_ban.id, refresh=True)

        # Re-decided against the locked state: another reader may have awarded this
        # very step while this one waited on the lock, and then there is no decider
        # step current any more.
        entry = auto_complete_decider_entry(pick_ban.resolved_sequence_json, pool)
        if entry is None:
            return None

        pick_ban.current_step_started_at = datetime.now(UTC)
        if engine.get_current_step(pick_ban.resolved_sequence_json, pool) is None:
            pick_ban.status = MapVetoSessionStatus.COMPLETED.value

        await emit_pick_ban_update(session, encounter_id, kind=kind.value)
        await session.commit()
        await session.refresh(entry)
        return entry

    async def auto_resolve_timeout(
        self,
        session: AsyncSession,
        encounter_id: int,
        kind: PickBanKind,
        *,
        pick_ban: PickBanSession | None = None,
    ) -> PickBanEntry | None:
        """Auto-resolve a captain step (ban/pick/protect) whose turn timer has
        elapsed, standing in for a captain who never acted: picks uniformly at
        random among every candidate that action would legally accept right now
        (same eligibility ``apply_pick_ban_action`` enforces, attribute
        uniqueness included) and applies it as if that side had chosen it.

        Lazy and read-triggered, like ``auto_complete_decider`` — there is no
        background scheduler, so a timed-out step only resolves the next time
        someone reads this session's state or acts on it. A session with
        ``turn_timer_seconds=None`` (no timer configured) or a fresh step
        (``current_step_started_at=None``) never times out. A ``decider`` step
        has no captain and is out of scope here; it already auto-resolves via
        ``auto_complete_decider``, called right after this in
        ``get_pick_ban_pool``/``perform_pick_ban_action``.

        Double-checked, and this is the path that most needs it: every open client
        polls the room every few seconds and all of them refetch at once on a
        realtime event, so ONE expired turn used to be resolved by every reader
        that arrived before the first committed -- each auto-action landing on the
        same side, each eating the next step. The unlocked check below is the cheap
        "is this turn even abandoned"; the decision itself is made under the lock,
        where a bumped ``current_step_started_at`` says another reader got here
        first."""
        if pick_ban is None:
            pick_ban = await self.sessions.get_pick_ban_session(session, encounter_id, kind)
        if not _turn_is_abandoned(pick_ban):
            return None

        pick_ban = await self.sessions.get_pick_ban_session(session, encounter_id, kind, for_update=True)
        if not _turn_is_abandoned(pick_ban):
            return None
        assert pick_ban is not None  # narrowed by `_turn_is_abandoned`

        now = datetime.now(UTC)
        pool = await self._load_pool(session, pick_ban.id, refresh=True)

        step = engine.get_current_step(pick_ban.resolved_sequence_json, pool)
        if step is None:
            return None
        _, step_token = step
        parsed = engine.parse_step_token(step_token)
        if parsed.side is None:  # "decider" — no captain to time out
            return None

        active_round = engine.current_round(pool)
        config = await self.config_repo.get(session, pick_ban.config_id) if pick_ban.config_id else None
        unique_attribute = config.unique_attribute_per_side_per_round if config is not None else None
        attribute_lookup = (
            await self._attribute_lookup(session, kind, [e.item_id for e in pool])
            if unique_attribute is not None
            else {}
        )
        # Ban memory is ban-only: a protect step is never barred by what this side
        # banned earlier, so it needs no ledger lookup at all.
        same_side_ban_memory = config is not None and config.no_repeat_scope == PickBanNoRepeatScope.ENCOUNTER_SAME_SIDE
        excluded_for_side = (
            await self._ledger_exclusions_for_side(session, encounter_id, kind, parsed.side)
            if parsed.action == "ban" and same_side_ban_memory
            else frozenset()
        )
        committed = engine.committed_attributes(pool, action=parsed.action, attribute_lookup=attribute_lookup)

        def eligible(entry: PickBanEntry) -> bool:
            if not engine.in_current_round(entry, active_round):
                return False
            if parsed.action == "ban":
                if entry.item_id in excluded_for_side:
                    return False
                if not engine.is_entry_bannable(entry, active_round=active_round):
                    return False
            elif entry.status != MapPoolEntryStatus.AVAILABLE.value:
                return False
            if (
                parsed.action in ("ban", "protect")
                and unique_attribute is not None
                and engine.violates_unique_attribute(
                    candidate_attribute=attribute_lookup.get(entry.item_id),
                    acting_side=parsed.side,
                    round_number=active_round,
                    committed_this_round=committed,
                )
            ):
                return False
            return True

        candidates = [entry for entry in pool if eligible(entry)]
        if not candidates:
            # No legal candidate for this side right now — a config/data
            # invariant violation elsewhere (mirrors auto_complete_decider_entry's
            # own floor check), not something a random pick can paper over. Leave
            # the step as-is; it surfaces the same way it already would.
            return None

        # CSPRNG for the same reason as in ``auto_complete_decider_entry``: this
        # stands in for a captain's match-affecting choice, so it must not be
        # predictable from PRNG state.
        chosen = secrets.choice(candidates)
        entry = apply_pick_ban_action(
            pick_ban,
            pool,
            captain_side=parsed.side,
            item_id=chosen.item_id,
            action=parsed.action,
            attribute_lookup=attribute_lookup,
            unique_attribute=unique_attribute,
            now=now,
            excluded_for_side=excluded_for_side,
        )
        if parsed.action == "ban" and config is not None and config.no_repeat_scope != "none":
            await self.ledger_repo.create(
                session,
                EncounterPickBanLedger(
                    encounter_id=encounter_id,
                    kind=kind,
                    item_id=chosen.item_id,
                    banned_by_side=parsed.side,
                    round=entry.round or 0,
                ),
            )

        await emit_pick_ban_update(session, encounter_id, kind=kind.value)
        await session.commit()
        await session.refresh(entry)
        await self.auto_complete_decider(session, encounter_id, kind, pick_ban=pick_ban, pool=pool)
        return entry

    async def _attribute_lookup(self, session: AsyncSession, kind: PickBanKind, item_ids: list[int]) -> dict[int, Any]:
        """``{item_id: attribute_value}`` for the configured
        ``unique_attribute_per_side_per_round`` (only ``"role"`` today, resolved
        against the hero catalog — a ``kind=map`` config never sets this option,
        so this is never called with `kind=map`)."""
        if kind != PickBanKind.HERO or not item_ids:
            return {}
        # Two-column projection, not a row read: stays in the service rather than
        # becoming a `HeroRepository` method. The Enum result processor usually
        # returns a HeroClass member, but a bare column select can also yield the
        # stored string — `.value` on a str 500s the timed-out state poll.
        result = await session.execute(select(Hero.id, Hero.type).where(Hero.id.in_(item_ids)))
        return {row[0]: getattr(row[1], "value", row[1]) for row in result.all() if row[1] is not None}

    async def _ledger_exclusions_for_side(
        self, session: AsyncSession, encounter_id: int, kind: PickBanKind, side: str
    ) -> frozenset[int]:
        """Items ``side`` may not ban again, under
        ``no_repeat_scope=encounter_same_side``: the ones it already banned earlier
        in this series (the opponent's earlier bans stay fair game — Doc 2's rule,
        design §5.4). Protects are not in the ledger and are neither barred by it
        nor recorded in it."""
        return frozenset(
            await self.ledger_repo.list_item_ids(
                session,
                encounter_id=encounter_id,
                kind=kind,
                filters=[EncounterPickBanLedger.banned_by_side == side],
            )
        )

    async def _map_reports(self, session: AsyncSession, encounter: Encounter) -> list[dict[str, Any]]:
        """Every per-map result claim filed for this encounter, as
        ``{map_id, map_index, side, home_score, away_score}``.

        ``map_index`` is the map's 1-based position in the series, which is what the
        room matches a claim against -- a series may play the same map twice, and
        keying on ``map_id`` alone showed the earlier play's claims on the later one.

        Read by the room's per-map result step, which is the loop's third phase
        (map picked -> heroes banned -> map played and reported -> next map): it
        needs to tell "waiting on the opponent" from "both agreed" from "the two
        disagree", and ``submit_map_report``'s own return value only ever reaches
        the captain who filed it, only until they reload.
        """
        reports: list[dict[str, Any]] = []
        for row in await self.map_report_repo.list_for_encounter(session, encounter.id):
            if row.team_id == encounter.home_team_id:
                side = MapPickSide.HOME.value
            elif row.team_id == encounter.away_team_id:
                side = MapPickSide.AWAY.value
            else:
                continue  # filed by a team this encounter no longer has assigned
            reports.append(
                {
                    "map_id": row.map_id,
                    "map_index": row.map_index,
                    "side": side,
                    "home_score": row.home_score,
                    "away_score": row.away_score,
                }
            )
        return reports

    async def get_pick_ban_state(
        self,
        session: AsyncSession,
        encounter_id: int,
        kind: PickBanKind,
        *,
        viewer_side: str | None = None,
    ) -> dict[str, Any]:
        encounter = await self.encounter_repo.get(session, encounter_id)
        if encounter is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encounter not found")

        readiness = await self.sessions.get_readiness(session, encounter_id)
        pick_ban = await self.sessions.ensure_pick_ban_session(session, encounter, kind)
        if kind == PickBanKind.HERO and pick_ban is not None:
            # Heroes are banned per map, one round at a time, and nothing pushes
            # "a map just got picked" -- so the hero session catches up with the
            # map phase here, on the read that is about to render it.
            await self.sessions.sync_hero_rounds(session, encounter)
        if pick_ban is None:
            # Mirrors veto_session.unavailable_reason's contract: names WHY, never
            # a bare 400 -- see pick_ban_session.unavailable_reason for why this
            # re-derives against PickBanConfig instead of being handed the cause.
            reason = await self.sessions.unavailable_reason(session, encounter, kind)
            state = build_unavailable_state(reason, readiness=readiness)
            if kind == PickBanKind.MAP:
                state["map_reports"] = await self._map_reports(session, encounter)
            return state

        config = await self.config_repo.get(session, pick_ban.config_id) if pick_ban.config_id else None
        pool = await self.get_pick_ban_pool(session, pick_ban, encounter_id, kind)
        state = build_pick_ban_state(
            pick_ban.resolved_sequence_json,
            pool,
            viewer_side=viewer_side,
            pick_ban=pick_ban,
            readiness=readiness,
            unique_attribute=config.unique_attribute_per_side_per_round if config is not None else None,
        )
        if kind == PickBanKind.MAP:
            state["map_reports"] = await self._map_reports(session, encounter)
        if (
            config is not None
            and config.no_repeat_scope == PickBanNoRepeatScope.ENCOUNTER_SAME_SIDE
            and state["turn_side"] is not None
        ):
            # What the side on the clock may no longer BAN because it already banned
            # it earlier in this series. Under this scope alone the item stays in the
            # pool -- one pool, two sides, and only one of them is barred -- so the
            # rule is enforced per action (`apply_pick_ban_action`) and the room had
            # no way to know before the click. The side-blind `encounter` scope needs
            # nothing here: those items never enter a later round's pool at all.
            state["repeat_banned"] = sorted(
                await self._ledger_exclusions_for_side(session, encounter_id, kind, state["turn_side"])
            )
        return state

    async def perform_pick_ban_action(
        self,
        session: AsyncSession,
        encounter_id: int,
        kind: PickBanKind,
        captain_side: str,
        item_id: int,
        action: str,
    ) -> PickBanEntry:
        # The lock comes FIRST, before anything this decision reads: the step is
        # resolved from the pool and written back as a committed entry, so two
        # overlapping requests must not both get to resolve it (see
        # `get_pick_ban_session`). Nothing is in the identity map yet, so the reads
        # below are already the post-lock truth.
        pick_ban = await self.sessions.get_pick_ban_session(session, encounter_id, kind, for_update=True)
        if pick_ban is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Pick-ban session is not initialized")
        if pick_ban.status != MapVetoSessionStatus.ACTIVE.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"Pick-ban session is {pick_ban.status}"
            )

        pool = await self._load_pool(session, pick_ban.id, refresh=True)
        config = await self.config_repo.get(session, pick_ban.config_id) if pick_ban.config_id else None
        attribute_lookup = (
            await self._attribute_lookup(session, kind, [e.item_id for e in pool])
            if config is not None and config.unique_attribute_per_side_per_round
            else {}
        )
        same_side_ban_memory = config is not None and config.no_repeat_scope == PickBanNoRepeatScope.ENCOUNTER_SAME_SIDE
        excluded_for_side = (
            await self._ledger_exclusions_for_side(session, encounter_id, kind, captain_side)
            if action == "ban" and same_side_ban_memory
            else frozenset()
        )

        entry = apply_pick_ban_action(
            pick_ban,
            pool,
            captain_side=captain_side,
            item_id=item_id,
            action=action,
            attribute_lookup=attribute_lookup,
            unique_attribute=config.unique_attribute_per_side_per_round if config else None,
            excluded_for_side=excluded_for_side,
            now=datetime.now(UTC),
        )

        # Ban memory only: a protect is round-local, so recording it here would
        # make it act as a ban on every later round (its item would be excluded
        # from their pools, or barred for this side).
        if action == "ban" and config is not None and config.no_repeat_scope != "none":
            await self.ledger_repo.create(
                session,
                EncounterPickBanLedger(
                    encounter_id=encounter_id,
                    kind=kind,
                    item_id=item_id,
                    banned_by_side=captain_side,
                    round=entry.round or 0,
                ),
            )

        await emit_pick_ban_update(session, encounter_id, kind=kind.value)
        await session.commit()
        await session.refresh(entry)
        # Resolve a decider step that becomes current as a DIRECT RESULT of this
        # action (e.g. the last ban of a Bo1 round leaving exactly one item)
        # without a second client round-trip. Mirrors map_veto.perform_veto_action.
        await self.auto_complete_decider(session, encounter_id, kind, pick_ban=pick_ban, pool=pool)
        return entry


pick_ban_action_service = PickBanActionService()
