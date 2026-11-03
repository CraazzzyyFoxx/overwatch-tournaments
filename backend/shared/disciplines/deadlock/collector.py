"""The Deadlock rank collector: deadlock-api polls of every in-scope Steam account into ``rank.*`` (``discipline='deadlock'``).

LoL's collector (``shared/disciplines/lol/collector.py``), keyed ``deadlock_rank:*``, with a batched upstream: a 60 s
leader-locked tick claims up to ``MAX_BATCH`` due ``rank.account_state`` rows and publishes them as ONE fetch; the
consumer asks ``GET /v1/players/rank?account_ids=`` once for the whole batch with no DB transaction open, then writes
every account's outcome in one transaction. A ranked badge appends a snapshot only when it changed (ok -> interval);
badge 0, or an account the answer leaves out, is ok and unranked (a row only when a rank was lost); a handle that is no
Steam account id never resolves (``disabled`` after ``max_consecutive_failures``). A failed batch (5xx, timeout, open
circuit, 429) defers every claimed account by ``backoff_base_seconds`` with no failure count and logs the failure
against each of them; a 429 also sets a global cooldown of ``Retry-After``, else 60 s. ``rate_limit_per_minute`` counts
deadlock-api requests (batches), shared by every fetch through a per-minute Redis window. Steam account ids never
change: no PUUID, region or rename.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import httpx
import sqlalchemy as sa
from faststream.rabbit import RabbitQueue
from loguru import logger
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.clients.circuit_breaker import CircuitBreakerOpen
from shared.core import enums
from shared.core.social import SocialProvider, steam_account_id
from shared.core.tournament_state import FINISHED_STATUSES
from shared.disciplines.deadlock.client import api_key, deadlock_client
from shared.disciplines.deadlock.ladder import TIER_NAMES, rank_value_from_badge
from shared.disciplines.deadlock.ranks import DISCIPLINE
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

__all__ = (
    "COOLDOWN_KEY",
    "DISCIPLINE",
    "FETCH_PRIORITY_QUEUE",
    "FETCH_QUEUE",
    "INVALID_ACCOUNT_ID_ERROR",
    "MAX_BATCH",
    "OWNED_DLQS",
    "PLAYER_REFRESH_QUEUE",
    "SETTINGS_KEY",
    "AccountRank",
    "DeadlockFetchRequest",
    "DeadlockRankCollectionConfig",
    "account_rank",
    "collection_config",
    "configure",
    "enqueue_fetch",
    "ensure_state",
    "fetch_badges",
    "handle_player_refresh",
    "mark_invalid",
    "mark_ok",
    "process_fetch",
    "rank_client",
    "run_collection_tick",
    "shutdown_scheduler",
    "start_scheduler",
    "trigger_collection",
)

SETTINGS_KEY = "deadlock.rank_collection"
TICK_SECONDS = 60
LEADER_LOCK_KEY = "deadlock_rank:scheduler:leader"
COOLDOWN_KEY = "deadlock_rank:cooldown"
MAX_BACKOFF_SECONDS = 6 * 60 * 60
MANUAL_PRIORITY_TIER = 2
FETCH_LOG_RETENTION = timedelta(days=7)
INVALID_ACCOUNT_ID_ERROR = "invalid steam account id"
#: deadlock-api's cap on ``account_ids`` of one ``/v1/players/rank`` request: the tick's claim and a batch's size.
MAX_BATCH = 1000
#: deadlock-api's per-minute request limits by IP and with an ``X-API-KEY``.
RATE_LIMIT_ANONYMOUS, RATE_LIMIT_KEYED = 20, 100
_INACTIVE_TOURNAMENT_STATUSES = tuple(sorted(status.value for status in FINISHED_STATUSES))


def _queue(name: str, routing_key: str | None = None) -> RabbitQueue:
    arguments = {"x-dead-letter-exchange": "dlx", "x-dead-letter-routing-key": f"{name}.dlq", "x-message-ttl": 600000}
    if routing_key is None:
        return RabbitQueue(name, durable=True, arguments=arguments)
    return RabbitQueue(name, durable=True, routing_key=routing_key, arguments=arguments)


FETCH_QUEUE = _queue("deadlock_rank_fetch")
FETCH_PRIORITY_QUEUE = _queue("deadlock_rank_fetch_priority")
PLAYER_REFRESH_QUEUE = _queue("deadlock_rank_player_refresh", PLAYER_REFRESH_REQUESTED_ROUTING_KEY)
#: Every queue the module consumes dead-letters; nothing else would declare or bind these.
OWNED_DLQS = tuple(
    RabbitQueue(f"{queue.name}.dlq", durable=True)
    for queue in (FETCH_QUEUE, FETCH_PRIORITY_QUEUE, PLAYER_REFRESH_QUEUE)
)

_states = RankAccountStateRepository()
_logs = RankFetchLogRepository()
_snapshots = RankSnapshotRepository()
rank_client = deadlock_client()


def _default_rate_limit() -> int:
    return RATE_LIMIT_KEYED if api_key() else RATE_LIMIT_ANONYMOUS


class DeadlockRankCollectionConfig(RankCollectionConfig):
    """LoL's shape with Deadlock's defaults: on (no credentials needed), every 6 h, every Steam account, batches of up
    to ``MAX_BATCH``. ``rate_limit_per_minute`` counts deadlock-api requests: 20 by IP, 100 with ``DEADLOCK_API_KEY``."""

    enabled: bool = True
    interval_seconds: int = Field(default=21_600, ge=60, le=86_400)
    batch_size: int = Field(default=MAX_BATCH, ge=1, le=MAX_BATCH)
    rate_limit_per_minute: int = Field(default_factory=_default_rate_limit, ge=1, le=6000)
    scope: RankCollectionScope = "all"


async def collection_config(session: AsyncSession) -> DeadlockRankCollectionConfig:
    raw = await settings_provider.get_setting_value(session, SETTINGS_KEY)
    try:
        return DeadlockRankCollectionConfig.model_validate(raw)
    except ValidationError as exc:
        logger.warning("invalid {} settings, using defaults: {}", SETTINGS_KEY, exc)
        return DeadlockRankCollectionConfig()


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
        raise RuntimeError(
            "Deadlock rank collector is not configured: the worker must call the module's jobs hooks first"
        )
    return _session_factory


def _redis_client() -> Any:
    if _redis is None:
        raise RuntimeError(
            "Deadlock rank collector is not configured: the worker must call the module's jobs hooks first"
        )
    return _redis


def _now() -> datetime:
    return datetime.now(UTC)


# -------------------------------------------------------------------------------------------------- deadlock-api


class DeadlockRateLimited(Exception):
    def __init__(self, retry_after: float | None) -> None:
        super().__init__("deadlock-api rate limited (429)")
        self.retry_after = retry_after


class DeadlockApiError(Exception):
    """5xx or any other unexpected answer: the whole batch is deferred."""


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After", "")
    return float(raw) if raw.isdigit() else None


async def fetch_badges(http: Any, account_ids: Sequence[int]) -> dict[int, int]:
    """``account_id -> badge`` (``tier * 10 + subrank``, 0 unranked) of every account the answer names; at most
    ``MAX_BATCH`` ids per call. An account the answer leaves out has no rank: the caller reads it as badge 0."""
    response = await http.get("/v1/players/rank", params={"account_ids": ",".join(map(str, account_ids))})
    if response.status_code == 429:
        raise DeadlockRateLimited(_retry_after(response))
    if response.status_code != 200:
        raise DeadlockApiError(f"deadlock-api answered {response.status_code}")
    try:
        return {int(entry["account_id"]): int(entry.get("badge") or 0) for entry in response.json()}
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise DeadlockApiError(f"malformed /v1/players/rank answer: {type(exc).__name__}") from exc


# -------------------------------------------------------------------------------------------------- pure decisions


@dataclass(frozen=True, slots=True)
class AccountRank:
    division: str | None
    tier: int | None
    rank_value: int | None
    is_ranked: bool


UNRANKED = AccountRank(None, None, None, False)


def account_rank(badge: int) -> AccountRank:
    """A badge -> the row it stands for: ``division`` = tier name, ``tier`` = subrank; badge 0 (or any badge off the
    ladder) is unranked."""
    value = rank_value_from_badge(badge)
    if value is None:
        return UNRANKED
    tier, subrank = divmod(badge, 10)
    return AccountRank(TIER_NAMES[tier], subrank, value, True)


def changed_rank(observed: AccountRank, latest: AccountRank | None) -> AccountRank | None:
    """The row to append, if any: a rank that differs from the last row; unranked only when it ends a ranked series."""
    if observed.is_ranked:
        return observed if observed != latest else None
    return observed if latest is not None and latest.is_ranked else None


def mark_ok(state: Any, *, now: datetime, config: RankCollectionConfig) -> None:
    state.status = enums.RankCollectionStatus.ok.value
    state.last_checked_at = state.last_success_at = now
    state.consecutive_failures = 0
    state.last_error = None
    state.next_eligible_at = now + timedelta(seconds=jittered_interval(config.interval_seconds, config.jitter_fraction))


def mark_invalid(state: Any, *, now: datetime, config: RankCollectionConfig) -> None:
    """A handle that is no Steam account id: exponential backoff, ``disabled`` after ``max_consecutive_failures``."""
    state.last_checked_at = now
    state.last_error = INVALID_ACCOUNT_ID_ERROR
    state.consecutive_failures = (state.consecutive_failures or 0) + 1
    if state.consecutive_failures >= config.max_consecutive_failures:
        state.status = enums.RankCollectionStatus.disabled.value
        state.next_eligible_at = None
        return
    backoff = min(config.backoff_base_seconds * (2 ** min(state.consecutive_failures - 1, 16)), MAX_BACKOFF_SECONDS)
    state.status = enums.RankCollectionStatus.error.value
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
            external_id=handle,
            priority_tier=priority_tier,
        )
    return await _states.bump_priority(session, state, priority_tier)


@dataclass(frozen=True, slots=True)
class _Target:
    social_account_id: int
    user_id: int
    handle: str


async def _load_targets(session: AsyncSession, social_account_ids: Sequence[int]) -> list[_Target]:
    """The accounts to fetch, keyed by their current handle: an admin's handle correction is what the next fetch asks."""
    acc = models.SocialAccount
    rows = await session.execute(
        sa.select(acc.id, acc.user_id, acc.username).where(
            acc.id.in_(list(social_account_ids)), acc.provider == SocialProvider.STEAM
        )
    )
    return [_Target(*row) for row in rows.all()]


async def _latest_ranks(session: AsyncSession, social_account_ids: Sequence[int]) -> dict[int, AccountRank]:
    snap = models.UserRankSnapshot
    rows = await session.execute(
        sa.select(snap.social_account_id, snap.division, snap.tier, snap.rank_value, snap.is_ranked)
        .where(snap.discipline == DISCIPLINE, snap.social_account_id.in_(list(social_account_ids)))
        .distinct(snap.social_account_id)
        .order_by(snap.social_account_id, snap.captured_at.desc(), snap.id.desc())
    )
    return {row[0]: AccountRank(*row[1:]) for row in rows.all()}


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


class DeadlockFetchRequest(BaseModel):
    social_account_ids: list[int] = Field(min_length=1, max_length=MAX_BATCH)
    source: Literal["scheduled", "registration", "manual"] = "scheduled"


async def _reserve_slot(redis: Any, limit: int) -> int:
    """Fixed-window per-minute limiter (``deadlock_rank:rl:<minute>``); 0 = go, else seconds until the window resets."""
    if limit <= 0:
        return 0
    now = _now().timestamp()
    key = f"deadlock_rank:rl:{int(now // 60)}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 70)
    return 0 if count <= limit else max(1, int(60 - (now % 60)))


async def enqueue_fetch(
    social_account_ids: Sequence[int],
    *,
    source: Literal["scheduled", "registration", "manual"] = "scheduled",
    priority: bool = False,
    broker: Any | None = None,
) -> int:
    """Publish ``social_account_ids`` as fetches of at most ``MAX_BATCH`` accounts each; returns the account count.

    ponytail: no Redis dedupe (LoL's per-account pending/in-flight keys): a duplicate costs one request of the window
    and, in a race, one duplicate snapshot row; add per-account keys if that shows up in the history."""
    ids = list(dict.fromkeys(social_account_ids))
    for start in range(0, len(ids), MAX_BATCH):
        request = DeadlockFetchRequest(social_account_ids=ids[start : start + MAX_BATCH], source=source)
        await publish_message(
            require_broker(broker or _broker),
            request.model_dump(),
            FETCH_PRIORITY_QUEUE if priority else FETCH_QUEUE,
            logger=logger.bind(accounts=len(request.social_account_ids), source=source),
        )
    return len(ids)


async def _batch_failure(exc: BaseException, redis: Any) -> tuple[str, str]:
    """``(status, error)`` of a failed batch; anything unexpected propagates (the message dead-letters)."""
    if isinstance(exc, DeadlockRateLimited):
        await redis.set(COOLDOWN_KEY, "1", ex=int(exc.retry_after or 60))
        return enums.RankCollectionStatus.rate_limited.value, "429 rate limited"
    if isinstance(exc, (DeadlockApiError, CircuitBreakerOpen, httpx.HTTPError)):
        logger.warning("deadlock-api rank batch failed: {}", type(exc).__name__)
        return enums.RankCollectionStatus.error.value, str(exc)[:500] or type(exc).__name__
    raise exc


def _record_batch(
    session: AsyncSession,
    *,
    targets: Mapping[int, list[_Target]],
    badges: Mapping[int, int],
    latest: Mapping[int, AccountRank],
    states: Mapping[int, Any],
    source: str,
    config: RankCollectionConfig,
    now: datetime,
) -> None:
    """Every account's outcome of one answered batch: state, fetch_log row and the snapshot when the rank changed."""
    for account_id, owners in targets.items():
        # An account the answer leaves out has no rank: badge 0, so a rank it held ends with an unranked row.
        row = account_rank(badges.get(account_id, 0))
        for target in owners:
            state = states[target.social_account_id]
            state.handle = target.handle
            changed = changed_rank(row, latest.get(target.social_account_id))
            if changed is not None:
                _snapshots.add_many(
                    session,
                    [
                        models.UserRankSnapshot(
                            discipline=DISCIPLINE,
                            user_id=target.user_id,
                            social_account_id=target.social_account_id,
                            handle=target.handle,
                            division=changed.division,
                            tier=changed.tier,
                            rank_value=changed.rank_value,
                            is_ranked=changed.is_ranked,
                            captured_at=now,
                            source=source,
                        )
                    ],
                )
            mark_ok(state, now=now, config=config)
            _log(
                session,
                social_account_id=target.social_account_id,
                handle=target.handle,
                status=enums.RankCollectionStatus.ok.value,
                source=source,
                written=int(changed is not None),
            )


async def process_fetch(
    data: dict[str, Any], *, redis: Any | None = None, http: Any | None = None, session_factory: Any | None = None
) -> None:
    """One batch: the 429 cooldown and the shared request window (either defers every account), then one
    ``/v1/players/rank`` call with no transaction open, then one write transaction for every account's outcome."""
    request = DeadlockFetchRequest.model_validate(data)
    redis_client = redis or _redis_client()
    sessions = session_factory or _sessions()
    ids = request.social_account_ids
    async with sessions() as session:
        config = await collection_config(session)
        # Self-throttling is not an upstream failure: deferred, never written to fetch_log.
        if await redis_client.get(COOLDOWN_KEY):
            await _states.defer_many(session, ids, delay_seconds=config.backoff_base_seconds, now=_now())
            await session.commit()
            return
        loaded = await _load_targets(session, ids)
    if not loaded:
        return

    targets: dict[int, list[_Target]] = {}
    invalid: list[_Target] = []
    for target in loaded:
        account_id = steam_account_id(target.handle)
        if account_id is None:
            invalid.append(target)
        else:
            targets.setdefault(int(account_id), []).append(target)

    badges: dict[int, int] | None = None
    deferred, failure = 0, None
    if targets:
        deferred = await _reserve_slot(redis_client, config.rate_limit_per_minute)
        if not deferred:
            try:
                badges = await fetch_badges(http or rank_client, list(targets))
            except Exception as exc:
                failure = await _batch_failure(exc, redis_client)

    now = _now()
    async with sessions() as session:
        state = models.RankAccountState
        states = {
            row.social_account_id: row
            for row in await session.scalars(
                sa.select(state).where(state.social_account_id.in_([t.social_account_id for t in loaded]))
            )
        }
        for target in loaded:
            if target.social_account_id not in states:
                states[target.social_account_id] = await ensure_state(session, target.social_account_id, target.handle)
        for target in invalid:
            mark_invalid(states[target.social_account_id], now=now, config=config)
            _log(
                session,
                social_account_id=target.social_account_id,
                handle=target.handle,
                status=enums.RankCollectionStatus.error.value,
                source=request.source,
                error=INVALID_ACCOUNT_ID_ERROR,
            )
        claimed = [target.social_account_id for owners in targets.values() for target in owners]
        if deferred:
            # The shared request window is full: the batch waits for the next one (no fetch_log row, no failure).
            await _states.defer_many(session, claimed, delay_seconds=deferred, now=_now())
        elif failure is not None:
            # A failed batch says nothing about any one account: defer them all with no failure count, and log the
            # failure against each one so a workspace-scoped reader sees it (one row per account, like a success).
            status, error = failure
            await _states.defer_many(session, claimed, delay_seconds=config.backoff_base_seconds, now=_now())
            for owners in targets.values():
                for target in owners:
                    _log(
                        session,
                        social_account_id=target.social_account_id,
                        handle=target.handle,
                        status=status,
                        source=request.source,
                        error=error,
                    )
        elif badges is not None:
            _record_batch(
                session,
                targets=targets,
                badges=badges,
                latest=await _latest_ranks(session, claimed),
                states=states,
                source=request.source,
                config=config,
                now=now,
            )
        await session.commit()


# -------------------------------------------------------------------------------------------------- scope + triggers


async def _steam_accounts_of(session: AsyncSession, user_ids: Sequence[int]) -> list[tuple[int, str]]:
    acc = models.SocialAccount
    rows = await session.execute(
        sa.select(acc.id, acc.username)
        .where(acc.provider == SocialProvider.STEAM, acc.user_id.in_(list(user_ids)))
        .order_by(acc.id)
    )
    return [(row[0], row[1]) for row in rows.all()]


async def handle_player_refresh(
    data: dict[str, Any], *, broker: Any | None = None, session_factory: Any | None = None
) -> int:
    """A Deadlock player refresh (registration approved or re-checked, mix signup): priority-fetch every Steam account
    of the player in one batch. Reference-only, like Overwatch's: the declared registration rank is never overwritten."""
    event = PlayerRefreshRequestedEvent.model_validate(data)
    if event.discipline != DISCIPLINE:
        return 0
    async with (session_factory or _sessions())() as session:
        accounts = await _steam_accounts_of(session, [event.user_id])
        for social_account_id, handle in accounts:
            await ensure_state(session, social_account_id, handle, priority_tier=MANUAL_PRIORITY_TIER)
        await session.commit()
    return await enqueue_fetch(
        [social_account_id for social_account_id, _ in accounts], source="registration", priority=True, broker=broker
    )


async def trigger_collection(
    session: AsyncSession,
    *,
    user_id: int | None,
    social_account_ids: Sequence[int] | None,
    workspace_id: int | None,
    broker: Any | None = None,
) -> int:
    """Admin "collect now" for a player's Steam accounts (or the given ones), inside the caller's workspace scope."""
    if not social_account_ids and user_id is None:
        return 0
    acc = models.SocialAccount
    query = sa.select(acc.id, acc.username).where(acc.provider == SocialProvider.STEAM)
    if social_account_ids:
        query = query.where(acc.id.in_(list(social_account_ids)))
    if user_id is not None:
        query = query.where(acc.user_id == user_id)
    if workspace_id is not None:
        query = query.where(acc.id.in_(workspace_account_ids(workspace_id, provider=SocialProvider.STEAM)))
    accounts = [(row[0], row[1]) for row in (await session.execute(query)).all()]
    for social_account_id, handle in accounts:
        await ensure_state(session, social_account_id, handle, priority_tier=MANUAL_PRIORITY_TIER)
    await session.commit()
    return await enqueue_fetch(
        [social_account_id for social_account_id, _ in accounts], source="manual", priority=True, broker=broker
    )


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
    # ponytail: every Steam account of an active Deadlock registrant, no extra-accounts cap; add one if smurfs matter.
    return set(
        (
            await session.scalars(
                sa.select(acc.id).where(acc.provider == SocialProvider.STEAM, acc.user_id.in_(registrants))
            )
        ).all()
    )


async def _seed(session: AsyncSession, config: RankCollectionConfig) -> int:
    if config.scope == "all":
        return await _states.bulk_seed_missing(
            session,
            discipline=DISCIPLINE,
            provider=SocialProvider.STEAM,
            external_id=models.SocialAccount.username,
            interval_seconds=config.interval_seconds,
            # Every Steam account: a handle that is no account id must reach the permanent-failure path.
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
        provider=SocialProvider.STEAM,
        external_id=models.SocialAccount.username,
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
    """One scheduling pass (Redis leader lock across replicas): seed, pace, claim, publish one batch. Returns the
    claimed account count."""
    redis_client = redis or _redis_client()
    sessions = session_factory or _sessions()
    try:
        token = await acquire_distributed_lock(
            redis_client, LEADER_LOCK_KEY, ttl_seconds=TICK_SECONDS * 2, acquire_timeout_seconds=0.5
        )
    except DistributedLockUnavailable:
        return 0
    async with observe_scheduled_job("deadlock_rank_collection"):
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
                        # The tick sends one request, and one request carries a whole batch.
                        rate_limit_per_minute=MAX_BATCH * 60 // TICK_SECONDS,
                        batch_size=config.batch_size,
                        max_per_tick=config.max_per_tick,
                    )
                    if config.auto_pace
                    else config.batch_size
                )
                due = await _states.claim_due(
                    session,
                    discipline=DISCIPLINE,
                    limit=min(limit, MAX_BATCH),
                    scope=config.scope,
                    interval_seconds=config.interval_seconds,
                    jitter_fraction=config.jitter_fraction,
                    now=_now(),
                )
                ids = [state.social_account_id for state in due]
                await session.commit()
            if ids:
                await enqueue_fetch(ids, broker=broker)
            logger.info(
                "Deadlock rank tick: scope={} in_scope={} seeded={} per_tick={} claimed={}",
                config.scope,
                total,
                seeded,
                limit,
                len(ids),
            )
            return len(ids)
        except Exception:
            logger.exception("Deadlock rank collection tick failed")
            return 0
        finally:
            await release_distributed_lock(redis_client, token)


async def run_fetch_log_purge(*, session_factory: Any | None = None) -> int:
    """Drop this game's ``fetch_log`` rows past ``FETCH_LOG_RETENTION`` (no leader lock: the delete is idempotent)."""
    async with observe_scheduled_job("deadlock_rank_fetch_log_purge"):
        try:
            async with (session_factory or _sessions())() as session:
                deleted = await _logs.delete_older_than(session, _now() - FETCH_LOG_RETENTION, discipline=DISCIPLINE)
                await session.commit()
            return deleted
        except Exception:
            logger.exception("Deadlock fetch_log purge failed")
            return 0


_scheduler = IntervalScheduler(job_id="deadlock_rank_collection", label="Deadlock rank")
_purge_scheduler = IntervalScheduler(job_id="deadlock_rank_fetch_log_purge", label="Deadlock fetch-log purge")


def start_scheduler() -> None:
    _scheduler.start(run_collection_tick, seconds=TICK_SECONDS)
    _purge_scheduler.start(run_fetch_log_purge, seconds=24 * 60 * 60)


def shutdown_scheduler() -> None:
    _scheduler.shutdown()
    _purge_scheduler.shutdown()
