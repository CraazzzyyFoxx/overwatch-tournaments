from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any, Literal

from loguru import logger
from sqlalchemy import event
from sqlalchemy.orm import Session

from shared.models.platform.realtime import WorkspaceEvent
from shared.services import realtime_topics
from shared.services.realtime_transaction import register_realtime_update
from src.core import config
from src.services.tournament.cache_invalidation import invalidate_tournament_cache

TournamentRealtimeReason = Literal[
    "bracket_changed",
    "results_changed",
    "structure_changed",
    "registration_changed",
    "registration_form_changed",
]

_SESSION_KEY = "tournament_realtime_updates"
_BRACKET_CHANGED: TournamentRealtimeReason = "bracket_changed"
_RESULTS_CHANGED: TournamentRealtimeReason = "results_changed"
_STRUCTURE_CHANGED: TournamentRealtimeReason = "structure_changed"
_REGISTRATION_CHANGED: TournamentRealtimeReason = "registration_changed"
_FORM_CHANGED: TournamentRealtimeReason = "registration_form_changed"

# asyncio holds only a WEAK reference to a running task, so a fire-and-forget
# `create_task` whose result nobody keeps can be collected mid-flight and take
# the cache invalidation with it, silently. Anchoring the handles here until
# they finish is the documented remedy.
_background_tasks: set[asyncio.Task[Any]] = set()


def _spawn(loop: asyncio.AbstractEventLoop, coro: Any) -> None:
    task = loop.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _normalize_reason(reason: str) -> TournamentRealtimeReason | None:
    if reason == _BRACKET_CHANGED:
        return _BRACKET_CHANGED
    if reason == _RESULTS_CHANGED:
        return _RESULTS_CHANGED
    if reason == _STRUCTURE_CHANGED:
        return _STRUCTURE_CHANGED
    if reason == _REGISTRATION_CHANGED:
        return _REGISTRATION_CHANGED
    if reason == _FORM_CHANGED:
        return _FORM_CHANGED
    return None


def _merge_updates(
    updates: Iterable[tuple[int, TournamentRealtimeReason]],
) -> list[tuple[int, TournamentRealtimeReason]]:
    reasons_by_tournament: dict[int, set[TournamentRealtimeReason]] = {}
    for tournament_id, reason in updates:
        reasons_by_tournament.setdefault(tournament_id, set()).add(reason)

    merged: list[tuple[int, TournamentRealtimeReason]] = []
    for tournament_id, reasons in sorted(reasons_by_tournament.items()):
        if _STRUCTURE_CHANGED in reasons:
            merged.append((tournament_id, _STRUCTURE_CHANGED))
        elif _RESULTS_CHANGED in reasons:
            merged.append((tournament_id, _RESULTS_CHANGED))
        elif _BRACKET_CHANGED in reasons:
            merged.append((tournament_id, _BRACKET_CHANGED))
        # registration_changed's invalidation plan (registration/registrationsList/
        # registrationForm) is disjoint from the bracket-family plans above, not a
        # subset of them — fold it into the chain only where structure_changed
        # already supersedes it (its plan includes the registration keys too);
        # otherwise it needs its own event or its invalidation would be dropped.
        if _REGISTRATION_CHANGED in reasons and _STRUCTURE_CHANGED not in reasons:
            merged.append((tournament_id, _REGISTRATION_CHANGED))
        # The FORM is admin configuration, not participant data: its plan is
        # disjoint from every other reason's, including structure_changed's, so
        # it is never folded away. Before this reason existed the form key rode
        # along with registration_changed, which meant every signup made every
        # open tab re-read a config that changes a couple of times per event.
        if _FORM_CHANGED in reasons:
            merged.append((tournament_id, _FORM_CHANGED))
    return merged


def register_tournament_realtime_update(
    session: Any,
    tournament_id: int,
    reason: TournamentRealtimeReason | str,
) -> None:
    normalized_reason = _normalize_reason(str(reason))
    if normalized_reason is None:
        logger.warning(
            "Ignoring tournament realtime update with unsupported reason",
            tournament_id=tournament_id,
            reason=reason,
        )
        return

    sync_session = getattr(session, "sync_session", None)
    info = getattr(sync_session or session, "info", None)
    if info is None:
        return

    updates = info.setdefault(_SESSION_KEY, set())
    updates.add((int(tournament_id), normalized_reason))

    # `register_realtime_update` dedups by key alone (last write wins), but this
    # module needs to MERGE every reason registered for this tournament so far
    # this transaction into the single strongest one (`_merge_updates`), not
    # just take the latest call's. Re-resolving that merge from the full
    # accumulated set on every call and re-registering under the SAME stable
    # key achieves it: each call's closure is a complete, self-sufficient
    # answer that supersedes the previous one, not an increment of it -- so a
    # later `structure_changed` correctly replaces an earlier `results_changed`
    # registration instead of firing alongside it, while a genuinely disjoint
    # pair (`results_changed` + `registration_changed`) still yields both rows.
    this_tournament_id = int(tournament_id)
    merged = _merge_updates((tid, r) for tid, r in updates if tid == this_tournament_id)
    register_realtime_update(
        session,
        key=(this_tournament_id, "tournament"),
        build_event=lambda events=[_build_realtime_event(tid, r) for tid, r in merged]: events,
        redis_url=str(config.settings.redis_url),
    )


def pop_registered_tournament_realtime_updates(
    session: Any,
) -> list[tuple[int, TournamentRealtimeReason]]:
    sync_session = getattr(session, "sync_session", None)
    info = getattr(sync_session or session, "info", None)
    if info is None:
        return []

    updates = info.pop(_SESSION_KEY, set())
    return _merge_updates(updates)


async def publish_tournament_realtime_updates(
    updates: Iterable[tuple[int, TournamentRealtimeReason]],
) -> None:
    from src.services.tournament.realtime_pubsub import publish_tournament_update

    for tournament_id, reason in updates:
        try:
            await invalidate_tournament_cache(tournament_id, reason)
            await publish_tournament_update(tournament_id, reason)
        except Exception:
            logger.exception(
                "Failed to publish tournament realtime update",
                tournament_id=tournament_id,
                reason=reason,
            )


def _build_realtime_event(tournament_id: int, reason: TournamentRealtimeReason) -> WorkspaceEvent:
    return WorkspaceEvent(
        topic=realtime_topics.bracket(tournament_id),
        event_type="tournament.updated",
        tournament_id=int(tournament_id),
        schema_version=1,
        payload={
            "tournament_id": int(tournament_id),
            "reason": reason,
        },
    )


async def _invalidate_cache(tournament_id: int, reason: TournamentRealtimeReason) -> None:
    try:
        await invalidate_tournament_cache(tournament_id, reason)
    except Exception:
        logger.exception(
            "Failed to invalidate tournament cache after a realtime update",
            tournament_id=tournament_id,
            reason=reason,
        )


@event.listens_for(Session, "after_commit")
def _invalidate_cache_after_commit(session: Session) -> None:
    # Cache invalidation is tournament-specific business logic, not part of the
    # shared realtime-staging factory (`register_realtime_update` only persists
    # and publishes) -- kept as its own listener so it fires for every merged
    # reason regardless of whether the shared factory's own `before_flush`
    # actually ran this transaction (it is skipped entirely when nothing else in
    # the session is new/dirty/deleted).
    updates = pop_registered_tournament_realtime_updates(session)
    if not updates:
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("Cannot invalidate tournament cache without a running event loop")
        return

    for tournament_id, reason in updates:
        _spawn(loop, _invalidate_cache(tournament_id, reason))


@event.listens_for(Session, "after_rollback")
def _clear_registered_updates_after_rollback(session: Session) -> None:
    # The shared factory clears its OWN staged builders on rollback; this
    # module's raw (tournament_id, reason) accumulation is a distinct piece of
    # session state it knows nothing about, so it still needs its own cleanup —
    # otherwise a session reused for a later transaction after a rollback would
    # carry stale reasons into that transaction's merge.
    pop_registered_tournament_realtime_updates(session)
