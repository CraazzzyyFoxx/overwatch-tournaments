"""The LoL rank collector: Riot API polls of every in-scope Riot account into ``rank.*`` (``discipline='lol'``).

The Overwatch collector's design (``shared/disciplines/overwatch/collector``), keyed ``lol_rank:*``: a 60 s leader-locked
tick claims due ``rank.account_state`` rows and publishes one fetch per account to this module's queues; a consumer runs
the Riot calls with no DB transaction open, writes only changed queue rows and reschedules the account (ok -> interval,
not_found -> 8x, transient -> exponential backoff capped at 6 h, permanent -> ``disabled`` after
``max_consecutive_failures``; a 429 sets a global cooldown of ``Retry-After``, else 60 s). LoL has no ``private`` status.
``rate_limit_per_minute`` counts Riot requests, not accounts: every outbound request takes one slot of a shared
per-minute Redis window, and a fetch that finds the window full stops, keeps the PUUID and platform it confirmed, and
resumes from there in a later window.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import httpx
import sqlalchemy as sa
from faststream.rabbit import RabbitQueue
from loguru import logger
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.clients.circuit_breaker import CircuitBreakerOpen
from shared.core import enums
from shared.core.social import SocialProvider, display_social_handle
from shared.core.tournament_state import FINISHED_STATUSES
from shared.disciplines.lol import riot
from shared.disciplines.lol.ladder import DIVISIONAL_TIERS, QUEUES, division_number, rank_value
from shared.disciplines.lol.ranks import DISCIPLINE
from shared.messaging.config import PLAYER_REFRESH_REQUESTED_ROUTING_KEY
from shared.observability import observe_scheduled_job, publish_message
from shared.observability.broker import require_broker
from shared.repository.ranks import (
    RankAccountStateRepository,
    RankFetchLogRepository,
    RankSnapshotRepository,
    compute_per_tick,
    jittered_interval,
    workspace_account_ids,
)
from shared.schemas.events import PlayerRefreshRequestedEvent
from shared.schemas.settings import RankCollectionConfig, RankCollectionScope
from shared.services.distributed_lock import (
    DistributedLockUnavailable,
    acquire_distributed_lock,
    release_distributed_lock,
)
from shared.services.scheduler import IntervalScheduler
from shared.services.settings_provider import settings_provider
from shared.services.social_identity import SocialHandleConflict, social_identity_service

__all__ = (
    "COOLDOWN_KEY",
    "DISCIPLINE",
    "FETCH_PRIORITY_QUEUE",
    "FETCH_QUEUE",
    "INVALID_RIOT_ID_ERROR",
    "OWNED_DLQS",
    "PLAYER_REFRESH_QUEUE",
    "SETTINGS_KEY",
    "LolFetchRequest",
    "LolRankCollectionConfig",
    "QueueRank",
    "changed_queue_ranks",
    "collection_config",
    "configure",
    "enqueue_fetch",
    "ensure_state",
    "handle_player_refresh",
    "mark_failure",
    "mark_not_found",
    "mark_ok",
    "process_fetch",
    "queue_ranks",
    "rank_client",
    "run_collection_tick",
    "shutdown_scheduler",
    "start_scheduler",
    "trigger_collection",
)

SETTINGS_KEY = "lol.rank_collection"
TICK_SECONDS = 60
LEADER_LOCK_KEY = "lol_rank:scheduler:leader"
COOLDOWN_KEY = "lol_rank:cooldown"
PENDING_TTL_SECONDS = 15 * 60
INFLIGHT_TTL_SECONDS = 180
NOT_FOUND_INTERVAL_FACTOR = 8
MAX_BACKOFF_SECONDS = 6 * 60 * 60
MANUAL_PRIORITY_TIER = 2
FETCH_LOG_RETENTION = timedelta(days=7)
INVALID_RIOT_ID_ERROR = "invalid riot id"
#: Riot requests of a resolved account's fetch (account-v1 by-puuid + league-v4 entries): the tick's pacing unit.
REQUESTS_PER_FETCH = 2
_INACTIVE_TOURNAMENT_STATUSES = tuple(sorted(status.value for status in FINISHED_STATUSES))


def _queue(name: str, routing_key: str | None = None) -> RabbitQueue:
    arguments = {"x-dead-letter-exchange": "dlx", "x-dead-letter-routing-key": f"{name}.dlq", "x-message-ttl": 600000}
    if routing_key is None:
        return RabbitQueue(name, durable=True, arguments=arguments)
    return RabbitQueue(name, durable=True, routing_key=routing_key, arguments=arguments)


FETCH_QUEUE = _queue("lol_rank_fetch")
FETCH_PRIORITY_QUEUE = _queue("lol_rank_fetch_priority")
PLAYER_REFRESH_QUEUE = _queue("lol_rank_player_refresh", PLAYER_REFRESH_REQUESTED_ROUTING_KEY)
#: Every queue the module consumes dead-letters; nothing else would declare or bind these.
OWNED_DLQS = tuple(
    RabbitQueue(f"{queue.name}.dlq", durable=True)
    for queue in (FETCH_QUEUE, FETCH_PRIORITY_QUEUE, PLAYER_REFRESH_QUEUE)
)

_states = RankAccountStateRepository()
_logs = RankFetchLogRepository()
_snapshots = RankSnapshotRepository()
rank_client = riot.api_client()


class LolRankCollectionConfig(RankCollectionConfig):
    """The OverFast collector's shape with League's defaults: off, every 6 h, 50 requests/min, every Riot account.

    At least ``REQUESTS_PER_FETCH`` requests a minute: below that a resolved account's fetch never fits one window.
    """

    enabled: bool = False
    interval_seconds: int = Field(default=21_600, ge=60, le=86_400)
    rate_limit_per_minute: int = Field(default=50, ge=REQUESTS_PER_FETCH, le=6000)
    scope: RankCollectionScope = "all"


async def collection_config(session: AsyncSession) -> LolRankCollectionConfig:
    raw = await settings_provider.get_setting_value(session, SETTINGS_KEY)
    try:
        return LolRankCollectionConfig.model_validate(raw)
    except ValidationError as exc:
        logger.warning("invalid {} settings, using defaults: {}", SETTINGS_KEY, exc)
        return LolRankCollectionConfig()


# -------------------------------------------------------------------------------------------------- process wiring

_session_factory: Any | None = None
_redis: Any | None = None
_broker: Any | None = None


def configure(*, session_factory: Any, redis: Any, broker: Any | None = None) -> None:
    global _session_factory, _redis, _broker
    _session_factory, _redis = session_factory, redis
    if broker is not None:
        _broker = broker


def _sessions() -> Any:
    if _session_factory is None:
        raise RuntimeError("LoL rank collector is not configured: the worker must call the module's jobs hooks first")
    return _session_factory


def _redis_client() -> Any:
    if _redis is None:
        raise RuntimeError("LoL rank collector is not configured: the worker must call the module's jobs hooks first")
    return _redis


def _now() -> datetime:
    return datetime.now(UTC)


# -------------------------------------------------------------------------------------------------- pure decisions


@dataclass(frozen=True, slots=True)
class QueueRank:
    queue: str
    division: str | None
    tier: int | None
    lp: int | None
    wins: int | None
    losses: int | None
    rank_value: int | None
    is_ranked: bool


def queue_ranks(entries: Sequence[Mapping[str, Any]]) -> dict[str, QueueRank]:
    """league-v4 entries -> one ranked row per tracked queue (Solo/Duo, Flex); other queues are ignored."""
    out: dict[str, QueueRank] = {}
    for entry in entries:
        queue = QUEUES.get(str(entry.get("queueType")))
        if queue is None:
            continue
        tier = str(entry.get("tier") or "").upper()
        lp = int(entry.get("leaguePoints") or 0)
        out[queue] = QueueRank(
            queue=queue,
            division=tier,
            tier=division_number(entry.get("rank")) if tier in DIVISIONAL_TIERS else None,
            lp=lp,
            wins=int(entry.get("wins") or 0),
            losses=int(entry.get("losses") or 0),
            rank_value=rank_value(tier, entry.get("rank"), lp),
            is_ranked=True,
        )
    return out


def changed_queue_ranks(observed: Mapping[str, QueueRank], latest: Mapping[str, QueueRank]) -> list[QueueRank]:
    """Rows to append: every queue that differs from its last row, and one unranked row for a queue that lost its rank."""
    rows = [rank for queue, rank in sorted(observed.items()) if latest.get(queue) != rank]
    rows += [
        QueueRank(queue, None, None, None, None, None, None, False)
        for queue, last in sorted(latest.items())
        if last.is_ranked and queue not in observed
    ]
    return rows


def mark_ok(state: Any, *, now: datetime, config: RankCollectionConfig) -> None:
    state.status = enums.RankCollectionStatus.ok.value
    state.last_checked_at = state.last_success_at = now
    state.consecutive_failures = 0
    state.last_error = None
    state.next_eligible_at = now + timedelta(seconds=jittered_interval(config.interval_seconds, config.jitter_fraction))


def mark_not_found(state: Any, *, now: datetime, config: RankCollectionConfig) -> None:
    state.status = enums.RankCollectionStatus.not_found.value
    state.last_checked_at = now
    state.consecutive_failures = 0
    state.last_error = None
    state.next_eligible_at = now + timedelta(
        seconds=jittered_interval(config.interval_seconds * NOT_FOUND_INTERVAL_FACTOR, config.jitter_fraction)
    )


def mark_failure(
    state: Any, *, now: datetime, config: RankCollectionConfig, status: str, error: str | None, transient: bool
) -> None:
    """Exponential backoff; only a permanent failure (a malformed Riot ID) counts toward ``disabled``."""
    state.last_checked_at = now
    state.last_error = (error or "")[:2000] or None
    state.consecutive_failures = (state.consecutive_failures or 0) + 1
    if not transient and state.consecutive_failures >= config.max_consecutive_failures:
        state.status = enums.RankCollectionStatus.disabled.value
        state.next_eligible_at = None
        return
    # Capped exponent: a transient outage drives the count arbitrarily high and never disables.
    backoff = min(config.backoff_base_seconds * (2 ** min(state.consecutive_failures - 1, 16)), MAX_BACKOFF_SECONDS)
    state.status = str(status)
    state.next_eligible_at = now + timedelta(seconds=backoff)


# -------------------------------------------------------------------------------------------------- DB helpers


async def ensure_state(
    session: AsyncSession, social_account_id: int, handle: str, *, priority_tier: int = 0
) -> models.RankAccountState:
    state = await _states.get_by_social_account_id(session, social_account_id)
    if state is None:
        return await _states.create_for_account(
            session,
            discipline=DISCIPLINE,
            social_account_id=social_account_id,
            handle=handle,
            external_id=None,
            priority_tier=priority_tier,
        )
    return await _states.bump_priority(session, state, priority_tier)


@dataclass(frozen=True, slots=True)
class _Target:
    social_account_id: int
    user_id: int
    handle: str
    puuid: str | None
    region: str | None


def _verified_subject() -> sa.ColumnElement[str | None]:
    """The RSO subject (the PUUID) of a verified Riot account; a hand-typed Riot ID has none."""
    acc = models.SocialAccount
    return sa.case((acc.is_verified.is_(True), acc.provider_user_id), else_=sa.null())


async def _load_target(session: AsyncSession, social_account_id: int) -> _Target | None:
    """The account to fetch. With a cached PUUID the Riot-sourced ``state.handle`` stands; without one the social
    account's current Riot ID is the only lookup key, so an admin's handle correction is what the next fetch asks for."""
    acc, state = models.SocialAccount, models.RankAccountState
    row = (
        await session.execute(
            sa.select(acc.user_id, acc.username, _verified_subject(), state.handle, state.external_id, state.region)
            .outerjoin(state, state.social_account_id == acc.id)
            .where(acc.id == social_account_id, acc.provider == SocialProvider.RIOT)
        )
    ).first()
    if row is None:
        return None
    user_id, username, subject, handle, external_id, region = row
    handle = (handle if external_id else None) or display_social_handle(SocialProvider.RIOT, username)
    return _Target(social_account_id, user_id, handle, external_id or subject, region)


async def _latest_queue_ranks(session: AsyncSession, social_account_id: int) -> dict[str, QueueRank]:
    snap = models.UserRankSnapshot
    rows = await session.execute(
        sa.select(
            snap.queue, snap.division, snap.tier, snap.lp, snap.wins, snap.losses, snap.rank_value, snap.is_ranked
        )
        .where(snap.discipline == DISCIPLINE, snap.social_account_id == social_account_id)
        .ext(distinct_on(snap.queue))
        .order_by(snap.queue, snap.captured_at.desc(), snap.id.desc())
    )
    return {row[0]: QueueRank(*row) for row in rows.all()}


async def _rename(session: AsyncSession, target: _Target, riot_id: str) -> bool:
    """Follow a Riot ID change onto ``players.social_account`` (normalised by the identity service); a clash with
    another of the player's accounts skips the rename."""
    try:
        await social_identity_service.update(
            session, account_id=target.social_account_id, user_id=target.user_id, username=riot_id
        )
    except SocialHandleConflict:
        logger.warning("Riot ID rename skipped for social account {}: {} collides", target.social_account_id, riot_id)
        return False
    return True


def _log(
    session: AsyncSession,
    *,
    social_account_id: int,
    handle: str,
    status: str,
    source: str,
    error: str | None = None,
    written: int = 0,
) -> None:
    _logs.add(
        session,
        models.RankFetchLog(
            discipline=DISCIPLINE,
            social_account_id=social_account_id,
            handle=handle,
            status=str(status),
            source=source,
            error=error[:2000] if error else None,
            snapshots_written=written,
        ),
    )


# -------------------------------------------------------------------------------------------------- fetch


class LolFetchRequest(BaseModel):
    social_account_id: int
    source: Literal["scheduled", "registration", "manual"] = "scheduled"


def _pending_key(social_account_id: int) -> str:
    return f"lol_rank:fetch:pending:{social_account_id}"


def _inflight_key(social_account_id: int) -> str:
    return f"lol_rank:fetch:inflight:{social_account_id}"


async def _reserve_slot(redis: Any, limit: int) -> int:
    """Fixed-window per-minute limiter (``lol_rank:rl:<minute>``); 0 = go, else seconds until the window resets."""
    if limit <= 0:
        return 0
    now = _now().timestamp()
    key = f"lol_rank:rl:{int(now // 60)}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 70)
    return 0 if count <= limit else max(1, int(60 - (now % 60)))


class _OverBudget(Exception):
    """The shared per-minute request window is full: the fetch stops, the account waits for the next window."""

    def __init__(self, retry_after: int) -> None:
        super().__init__(f"Riot request budget spent, next window in {retry_after}s")
        self.retry_after = retry_after


def _request_budget(redis: Any, limit: int) -> Callable[[], Awaitable[None]]:
    """``fetch_account``'s ``acquire``: one ``lol_rank:rl:<minute>`` slot per outbound request, shared by every fetch."""

    async def acquire() -> None:
        retry_after = await _reserve_slot(redis, limit)
        if retry_after:
            raise _OverBudget(retry_after)

    return acquire


async def enqueue_fetch(
    request: LolFetchRequest,
    *,
    priority: bool = False,
    force: bool = False,
    broker: Any | None = None,
    redis: Any | None = None,
) -> bool:
    """Publish a fetch once per account (Redis-deduped); ``force`` bypasses the dedup (admin "collect now")."""
    redis_client = redis or _redis_client()
    pending = _pending_key(request.social_account_id)
    if force:
        await redis_client.set(pending, "1", ex=PENDING_TTL_SECONDS)
    elif not await redis_client.set(pending, "1", nx=True, ex=PENDING_TTL_SECONDS):
        return False
    try:
        await publish_message(
            require_broker(broker or _broker),
            request.model_dump(),
            FETCH_PRIORITY_QUEUE if priority else FETCH_QUEUE,
            logger=logger.bind(social_account_id=request.social_account_id, source=request.source),
        )
    except Exception:
        await redis_client.delete(pending)
        raise
    return True


async def _failure(exc: BaseException, redis: Any, social_account_id: int) -> tuple[str, str | None, bool]:
    """``(status, error, transient)`` of a failed fetch; anything unexpected propagates (the message dead-letters)."""
    if isinstance(exc, riot.RiotRateLimited):
        await redis.set(COOLDOWN_KEY, "1", ex=int(exc.retry_after or 60))
        return enums.RankCollectionStatus.rate_limited.value, "429 rate limited", True
    if isinstance(exc, riot.RiotNotFound):
        return enums.RankCollectionStatus.not_found.value, None, False
    if isinstance(exc, riot.InvalidRiotId):
        return enums.RankCollectionStatus.error.value, INVALID_RIOT_ID_ERROR, False
    if isinstance(exc, riot.RiotStalePuuid):
        return enums.RankCollectionStatus.error.value, "stale PUUID (400)", True
    if isinstance(exc, (riot.RiotError, CircuitBreakerOpen, httpx.HTTPError)):
        logger.warning("Riot fetch failed for social account {}: {}", social_account_id, type(exc).__name__)
        return enums.RankCollectionStatus.error.value, str(exc)[:500] or type(exc).__name__, True
    raise exc


async def _fetch_and_record(
    target: _Target, source: str, config: RankCollectionConfig, *, redis: Any, http: Any, sessions: Any
) -> None:
    now = _now()
    status, error, transient, fetched, stale, deferred = (
        enums.RankCollectionStatus.ok.value,
        None,
        False,
        None,
        False,
        0,
    )
    progress = riot.RiotProgress()
    try:
        fetched = await riot.fetch_account(
            http,
            riot_id=target.handle,
            puuid=target.puuid,
            region=target.region,
            acquire=_request_budget(redis, config.rate_limit_per_minute),
            progress=progress,
        )
    except Exception as exc:
        # A cached PUUID answered 400 and its re-resolve failed: forget the PUUID and its platform whatever the
        # re-resolve answered (``__cause__``), so the next fetch starts from the Riot ID.
        stale = isinstance(exc, riot.RiotStalePuuid)
        cause = exc.__cause__ if stale and exc.__cause__ is not None else exc
        if isinstance(cause, _OverBudget):
            deferred = cause.retry_after
        else:
            status, error, transient = await _failure(cause, redis, target.social_account_id)

    async with sessions() as session:
        state = await ensure_state(session, target.social_account_id, target.handle)
        state.handle = target.handle
        if stale:
            state.external_id = state.region = None
        if deferred:
            # Self-throttling is not an upstream failure: no fetch_log row, no failure count, no backoff. The PUUID and
            # platform confirmed before the budget ran out are kept, so the next window resumes from there.
            if progress.puuid is not None:
                if progress.puuid != state.external_id:
                    state.external_id, state.region = progress.puuid, None
                state.region = progress.region or state.region
            state.next_eligible_at = now + timedelta(seconds=deferred)
            await session.commit()
            return
        written = 0
        if fetched is not None:
            state.external_id, state.region = fetched.puuid, fetched.region
            if fetched.riot_id != state.handle and await _rename(session, target, fetched.riot_id):
                state.handle = fetched.riot_id
            rows = changed_queue_ranks(
                queue_ranks(fetched.entries), await _latest_queue_ranks(session, target.social_account_id)
            )
            _snapshots.add_many(
                session,
                [
                    models.UserRankSnapshot(
                        discipline=DISCIPLINE,
                        user_id=target.user_id,
                        social_account_id=target.social_account_id,
                        handle=state.handle,
                        queue=row.queue,
                        division=row.division,
                        tier=row.tier,
                        lp=row.lp,
                        wins=row.wins,
                        losses=row.losses,
                        rank_value=row.rank_value,
                        is_ranked=row.is_ranked,
                        captured_at=now,
                        source=source,
                    )
                    for row in rows
                ],
            )
            written = len(rows)
            mark_ok(state, now=now, config=config)
        elif status == enums.RankCollectionStatus.not_found.value:
            mark_not_found(state, now=now, config=config)
        else:
            mark_failure(state, now=now, config=config, status=status, error=error, transient=transient)
        _log(
            session,
            social_account_id=target.social_account_id,
            handle=state.handle,
            status=status,
            source=source,
            error=error,
            written=written,
        )
        await session.commit()


async def process_fetch(
    data: dict[str, Any], *, redis: Any | None = None, http: Any | None = None, session_factory: Any | None = None
) -> None:
    """One fetch: in-flight lock and the 429 cooldown (an active one defers the account), then the Riot calls with no
    transaction open, each charged to the shared per-minute budget, then one write transaction."""
    request = LolFetchRequest.model_validate(data)
    redis_client = redis or _redis_client()
    sessions = session_factory or _sessions()
    inflight = _inflight_key(request.social_account_id)
    if not await redis_client.set(inflight, "1", nx=True, ex=INFLIGHT_TTL_SECONDS):
        return
    try:
        async with sessions() as session:
            config = await collection_config(session)
            # Self-throttling is not an upstream failure: deferred, never written to fetch_log.
            if await redis_client.get(COOLDOWN_KEY):
                await _states.defer(
                    session,
                    social_account_id=request.social_account_id,
                    delay_seconds=config.backoff_base_seconds,
                    now=_now(),
                )
                await session.commit()
                return
            target = await _load_target(session, request.social_account_id)
        if target is not None:
            await _fetch_and_record(
                target, request.source, config, redis=redis_client, http=http or rank_client, sessions=sessions
            )
    finally:
        await redis_client.delete(inflight, _pending_key(request.social_account_id))


# -------------------------------------------------------------------------------------------------- scope + triggers


async def _riot_accounts_of(session: AsyncSession, user_ids: Sequence[int]) -> list[tuple[int, str]]:
    acc = models.SocialAccount
    rows = await session.execute(
        sa.select(acc.id, acc.username)
        .where(acc.provider == SocialProvider.RIOT, acc.user_id.in_(list(user_ids)))
        .order_by(acc.id)
    )
    return [(row[0], row[1]) for row in rows.all()]


async def handle_player_refresh(
    data: dict[str, Any], *, broker: Any | None = None, redis: Any | None = None, session_factory: Any | None = None
) -> int:
    """A LoL player refresh (registration approved or re-checked, mix signup): priority-fetch every Riot account of the
    player. Reference-only, like Overwatch's: the declared registration rank is never overwritten."""
    event = PlayerRefreshRequestedEvent.model_validate(data)
    if event.discipline != DISCIPLINE:
        return 0
    async with (session_factory or _sessions())() as session:
        accounts = await _riot_accounts_of(session, [event.user_id])
        for social_account_id, handle in accounts:
            await ensure_state(session, social_account_id, handle, priority_tier=MANUAL_PRIORITY_TIER)
        await session.commit()
    enqueued = 0
    for social_account_id, _ in accounts:
        request = LolFetchRequest(social_account_id=social_account_id, source="registration")
        if await enqueue_fetch(request, priority=True, broker=broker, redis=redis):
            enqueued += 1
    return enqueued


async def trigger_collection(
    session: AsyncSession,
    *,
    user_id: int | None,
    social_account_ids: Sequence[int] | None,
    workspace_id: int | None,
    broker: Any | None = None,
    redis: Any | None = None,
) -> int:
    """Admin "collect now" for a player's Riot accounts (or the given ones), inside the caller's workspace scope."""
    if not social_account_ids and user_id is None:
        return 0
    acc = models.SocialAccount
    query = sa.select(acc.id, acc.username).where(acc.provider == SocialProvider.RIOT)
    if social_account_ids:
        query = query.where(acc.id.in_(list(social_account_ids)))
    if user_id is not None:
        query = query.where(acc.user_id == user_id)
    if workspace_id is not None:
        query = query.where(acc.id.in_(workspace_account_ids(workspace_id, provider=SocialProvider.RIOT)))
    accounts = [(row[0], row[1]) for row in (await session.execute(query)).all()]
    for social_account_id, handle in accounts:
        await ensure_state(session, social_account_id, handle, priority_tier=MANUAL_PRIORITY_TIER)
    await session.commit()
    enqueued = 0
    for social_account_id, _ in accounts:
        request = LolFetchRequest(social_account_id=social_account_id, source="manual")
        if await enqueue_fetch(request, priority=True, force=True, broker=broker, redis=redis):
            enqueued += 1
    return enqueued


async def _registration_targets(session: AsyncSession) -> set[int]:
    reg, tournament, member, acc = models.Registration, models.Tournament, models.WorkspaceMember, models.SocialAccount
    registrants = (
        sa.select(member.player_id)
        .select_from(reg)
        .join(tournament, tournament.id == reg.tournament_id)
        .join(member, member.id == reg.workspace_member_id)
        .where(
            reg.deleted_at.is_(None),
            tournament.discipline == DISCIPLINE,
            tournament.status.notin_(_INACTIVE_TOURNAMENT_STATUSES),
        )
    )
    # ponytail: every Riot account of an active LoL registrant, no extra-accounts cap; add one if smurfs matter here.
    return set(
        (
            await session.scalars(
                sa.select(acc.id).where(acc.provider == SocialProvider.RIOT, acc.user_id.in_(registrants))
            )
        ).all()
    )


async def _seed(session: AsyncSession, config: RankCollectionConfig) -> int:
    if config.scope == "all":
        return await _states.bulk_seed_missing(
            session,
            discipline=DISCIPLINE,
            provider=SocialProvider.RIOT,
            external_id=_verified_subject(),
            interval_seconds=config.interval_seconds,
            # Every Riot account, tagged or not: a malformed Riot ID must reach the permanent-failure path.
            tagged_only=False,
        )
    targets = await _registration_targets(session)
    await _states.demote_tier1_not_in(session, targets, discipline=DISCIPLINE)
    if not targets:
        return 0
    await _states.promote_tier0_in(session, targets, discipline=DISCIPLINE)
    return await _states.bulk_seed_missing(
        session,
        discipline=DISCIPLINE,
        provider=SocialProvider.RIOT,
        external_id=_verified_subject(),
        interval_seconds=config.interval_seconds,
        target_ids=targets,
        priority_tier=1,
    )


async def _count_in_scope(session: AsyncSession, scope: str) -> int:
    """Non-disabled accounts in ``scope``: the pacing base (the whole population, not the due subset)."""
    state = models.RankAccountState
    query = (
        sa.select(sa.func.count())
        .select_from(state)
        .where(state.discipline == DISCIPLINE, state.status != enums.RankCollectionStatus.disabled.value)
    )
    if scope == "registrations_only":
        query = query.where(state.priority_tier > 0)
    return int(await session.scalar(query) or 0)


async def run_collection_tick(
    *, redis: Any | None = None, broker: Any | None = None, session_factory: Any | None = None
) -> int:
    """One scheduling pass (Redis leader lock across replicas): seed, pace, claim, enqueue. Returns the enqueued count."""
    redis_client = redis or _redis_client()
    sessions = session_factory or _sessions()
    try:
        token = await acquire_distributed_lock(
            redis_client, LEADER_LOCK_KEY, ttl_seconds=TICK_SECONDS * 2, acquire_timeout_seconds=0.5
        )
    except DistributedLockUnavailable:
        return 0
    async with observe_scheduled_job("lol_rank_collection"):
        try:
            async with sessions() as session:
                config = await collection_config(session)
                if not config.enabled:
                    return 0
                seeded = await _seed(session, config)
                total = await _count_in_scope(session, config.scope)
                limit = (
                    compute_per_tick(
                        total,
                        interval_seconds=config.interval_seconds,
                        tick_seconds=TICK_SECONDS,
                        # The budget counts requests; the claim counts fetches.
                        rate_limit_per_minute=config.rate_limit_per_minute // REQUESTS_PER_FETCH,
                        batch_size=config.batch_size,
                        max_per_tick=config.max_per_tick,
                    )
                    if config.auto_pace
                    else config.batch_size
                )
                due = await _states.claim_due(
                    session,
                    discipline=DISCIPLINE,
                    limit=limit,
                    scope=config.scope,
                    interval_seconds=config.interval_seconds,
                    jitter_fraction=config.jitter_fraction,
                    now=_now(),
                )
                ids = [state.social_account_id for state in due]
                await session.commit()
            enqueued = 0
            for social_account_id in ids:
                request = LolFetchRequest(social_account_id=social_account_id)
                if await enqueue_fetch(request, broker=broker, redis=redis_client):
                    enqueued += 1
            logger.info(
                "LoL rank tick: scope={} in_scope={} seeded={} per_tick={} due={} enqueued={}",
                config.scope,
                total,
                seeded,
                limit,
                len(ids),
                enqueued,
            )
            return enqueued
        except Exception:
            logger.exception("LoL rank collection tick failed")
            return 0
        finally:
            await release_distributed_lock(redis_client, token)


async def run_fetch_log_purge(*, session_factory: Any | None = None) -> int:
    """Drop this game's ``fetch_log`` rows past ``FETCH_LOG_RETENTION`` (no leader lock: the delete is idempotent)."""
    async with observe_scheduled_job("lol_rank_fetch_log_purge"):
        try:
            async with (session_factory or _sessions())() as session:
                deleted = await _logs.delete_older_than(session, _now() - FETCH_LOG_RETENTION, discipline=DISCIPLINE)
                await session.commit()
            return deleted
        except Exception:
            logger.exception("LoL fetch_log purge failed")
            return 0


_scheduler = IntervalScheduler(job_id="lol_rank_collection", label="LoL rank")
_purge_scheduler = IntervalScheduler(job_id="lol_rank_fetch_log_purge", label="LoL fetch-log purge")


def start_scheduler() -> None:
    _scheduler.start(run_collection_tick, seconds=TICK_SECONDS)
    _purge_scheduler.start(run_fetch_log_purge, seconds=24 * 60 * 60)


def shutdown_scheduler() -> None:
    _scheduler.shutdown()
    _purge_scheduler.shutdown()
