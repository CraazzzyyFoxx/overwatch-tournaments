"""Server-authoritative draft clock (runs in the FastStream worker).

A single owner per LIVE session (Redis token lock + heartbeat renewal) sleeps
until the on-clock pick's absolute ``clock_expires_at`` and then fires autopick.
The clock is DB-resumable: on owner failover the new owner reads
``clock_expires_at`` from the DB and resumes/fires accordingly — no time is lost
or double-counted. A manual REST pick/pause publishes to ``draft:{id}:control``
to cancel the pending autopick wake instantly.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from datetime import UTC, datetime

import sqlalchemy as sa
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import DraftPickStatus, DraftStatus
from shared.models.balancer.draft import DraftPick, DraftSession
from shared.services.distributed_lock import (
    DistributedLockUnavailable,
    acquire_distributed_lock,
    release_distributed_lock,
    renew_distributed_lock,
)
from src.services.draft import realtime as draft_rt
from src.services.draft import selection

LOCK_TTL_SECONDS = 10
RENEW_INTERVAL_SECONDS = 3
SUPERVISOR_POLL_SECONDS = 2

SessionFactory = Callable[[], AsyncSession]


def control_channel(session_id: int) -> str:
    return f"draft:{int(session_id)}:control"


def lock_key(session_id: int) -> str:
    return f"draft:{int(session_id)}:clock_owner"


def compute_sleep_seconds(clock_expires_at: datetime | None, now: datetime) -> float:
    """Seconds to sleep before the next wake. No deadline -> idle renew interval."""
    if clock_expires_at is None:
        return float(RENEW_INTERVAL_SECONDS)
    return max(0.0, (clock_expires_at - now).total_seconds())


async def fire_autopick_if_expired(
    session_factory: SessionFactory,
    redis: Redis | None,
    session_id: int,
) -> bool:
    """If the current pick is ON_CLOCK and past its deadline, autopick it.

    Returns True if an autopick was applied. Safe to call redundantly: a manual
    pick that already finalized makes this a no-op (status/version guard).
    """
    async with session_factory() as session:
        draft = await session.get(DraftSession, session_id)
        if draft is None or draft.status != DraftStatus.LIVE.value or draft.current_pick_id is None:
            return False
        pick = await session.get(DraftPick, draft.current_pick_id)
        if pick is None or pick.status != DraftPickStatus.ON_CLOCK.value:
            return False
        now = datetime.now(UTC)
        if pick.clock_expires_at is None or pick.clock_expires_at > now:
            return False  # paused or not yet due

        try:
            result = await selection.autopick(session, draft, pick, expected_version=pick.version)
        except Exception:  # noqa: BLE001 — lost the race to a manual pick, or transient
            await session.rollback()
            return False

        if result.blocked_reason:
            await draft_rt.publish_draft_event(
                session,
                redis,
                draft_session=draft,
                event_type="draft.blocked",
                payload={
                    "session_id": draft.id,
                    "pick_id": result.pick.id,
                    "draft_team_id": result.pick.draft_team_id,
                    "reason": result.blocked_reason,
                },
            )
        else:
            await draft_rt.publish_draft_event(
                session,
                redis,
                draft_session=draft,
                event_type="draft.autopicked",
                payload={
                    "session_id": draft.id,
                    "pick_id": result.pick.id,
                    "draft_team_id": result.pick.draft_team_id,
                    "picked_player_id": result.pick.picked_player_id,
                    "reason": "timeout",
                },
            )
        if result.completed:
            await draft_rt.publish_draft_event(
                session,
                redis,
                draft_session=draft,
                event_type="draft.completed",
                payload={"session_id": draft.id, "status": draft.status},
            )
        elif result.next_pick is not None:
            await draft_rt.publish_draft_event(
                session,
                redis,
                draft_session=draft,
                event_type="draft.pick_started",
                payload={
                    "session_id": draft.id,
                    "pick_id": result.next_pick.id,
                    "draft_team_id": result.next_pick.draft_team_id,
                    "clock_expires_at": result.next_pick.clock_expires_at.isoformat()
                    if result.next_pick.clock_expires_at
                    else None,
                },
            )
        await session.commit()
        return True


async def _renewer(redis: Redis, token) -> None:
    while True:
        await asyncio.sleep(RENEW_INTERVAL_SECONDS)
        if not await renew_distributed_lock(redis, token, ttl_seconds=LOCK_TTL_SECONDS):
            return  # lost ownership


async def _read_clock_state(session_factory: SessionFactory, session_id: int) -> tuple[str, datetime | None]:
    async with session_factory() as session:
        draft = await session.get(DraftSession, session_id)
        if draft is None:
            return DraftStatus.CANCELLED.value, None
        expires = None
        if draft.status == DraftStatus.LIVE.value and draft.current_pick_id:
            pick = await session.get(DraftPick, draft.current_pick_id)
            expires = pick.clock_expires_at if pick else None
        return draft.status, expires


async def _wait_for_nudge(pubsub, timeout: float) -> bool:
    """Return True if a control nudge arrived before the timeout."""
    try:
        msg = await asyncio.wait_for(
            pubsub.get_message(ignore_subscribe_messages=True, timeout=timeout),
            timeout=timeout + 0.5,
        )
    except TimeoutError:
        return False
    return msg is not None


async def clock_loop(session_factory: SessionFactory, redis: Redis, session_id: int) -> None:
    try:
        token = await acquire_distributed_lock(
            redis, lock_key(session_id), ttl_seconds=LOCK_TTL_SECONDS, acquire_timeout_seconds=0.5
        )
    except DistributedLockUnavailable:
        return  # another worker owns this session's clock

    renew_task = asyncio.create_task(_renewer(redis, token))
    pubsub = redis.pubsub()
    await pubsub.subscribe(control_channel(session_id))
    try:
        while not renew_task.done():
            status, expires = await _read_clock_state(session_factory, session_id)
            if status in (DraftStatus.COMPLETED.value, DraftStatus.CANCELLED.value):
                break
            sleep_s = (
                float(RENEW_INTERVAL_SECONDS)
                if status == DraftStatus.PAUSED.value
                else compute_sleep_seconds(expires, datetime.now(UTC))
            )
            nudged = await _wait_for_nudge(pubsub, sleep_s)
            if nudged:
                continue  # state changed (manual pick / pause) — re-read
            if status == DraftStatus.LIVE.value and expires is not None:
                await fire_autopick_if_expired(session_factory, redis, session_id)
    except Exception:  # noqa: BLE001
        logger.exception("Draft clock loop error", session_id=session_id)
    finally:
        renew_task.cancel()
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe(control_channel(session_id))
            await pubsub.aclose()
        with contextlib.suppress(Exception):
            await release_distributed_lock(redis, token)


async def draft_clock_supervisor(session_factory: SessionFactory, redis: Redis) -> None:
    """Discover LIVE sessions and spawn a (lock-guarded) clock loop for each."""
    spawned: dict[int, asyncio.Task] = {}
    while True:
        try:
            async with session_factory() as session:
                live_ids = (
                    await session.scalars(
                        sa.select(DraftSession.id).where(DraftSession.status == DraftStatus.LIVE.value)
                    )
                ).all()
            for sid in live_ids:
                task = spawned.get(sid)
                if task is None or task.done():
                    spawned[sid] = asyncio.create_task(clock_loop(session_factory, redis, sid))
        except Exception:  # noqa: BLE001
            logger.exception("Draft clock supervisor poll failed")
        await asyncio.sleep(SUPERVISOR_POLL_SECONDS)


async def notify_clock(redis: Redis | None, session_id: int) -> None:
    """Publish a control nudge so the owner re-reads state immediately."""
    if redis is None:
        return
    with contextlib.suppress(Exception):
        await redis.publish(control_channel(session_id), "1")
