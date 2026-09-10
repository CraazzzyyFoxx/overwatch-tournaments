from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from loguru import logger

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.jobs import JobService, JobSpec, RedisMetaStore, Unlimited
from shared.observability import metrics
from shared.services.balancer_realtime import (
    BALANCER_JOB_FAILED,
    BALANCER_JOB_QUEUED,
    BALANCER_JOB_RUNNING,
    BALANCER_JOB_SUCCEEDED,
)
from shared.services.roster import roster_engine
from shared.services.roster_shape_access import get_effective_roster_shape
from src.core import db
from src.core.job_store import get_job_store
from src.core.metrics import (
    BALANCER_JOB_QUEUE_WAIT_SECONDS,
    BALANCER_JOB_TOTAL_SECONDS,
    BALANCER_SOLVER_SECONDS,
)
from src.core.security.api_key_limiter import (
    get_api_key_id,
    get_api_key_limiter,
    get_effective_limits,
    get_principal,
    is_api_key_principal,
)
from src.core.security.api_key_policy import validate_api_key_config_policy
from src.core.security.workspace_access import WorkspaceAccessPolicy
from src.schemas.balancer import CreateJobResponse, JobStatusResponse
from src.services.balancer.config.provider import get_balancer_config_payload
from src.services.balancer.config.public_contract import normalize_balance_job_result_payload
from src.services.balancer.progress import (
    TERMINAL_STATUSES,
    ProgressEventThrottler,
)
from src.services.balancer.publisher import BalancerJobPublisher
from src.services.balancer.realtime import (
    emit_job_lifecycle,
    emit_job_progress,
)
from src.services.balancer.request_parser import BalancerRequestParser
from src.services.balancer.solver import run_balance

_access_policy = WorkspaceAccessPolicy()
_payload_parser = BalancerRequestParser()

# Outer wall-clock safety net for a single solver run (review H5). The native
# optimizer already honours ``time_limit_ms`` (max 600s); this watchdog is a
# coarse backstop that fails the job instead of awaiting forever should the
# solver hang or ignore its budget. Sized above the max native budget plus room
# for polishing/serialization.
_SOLVER_WATCHDOG_SECONDS = 660.0


def _count_variant_players(variant: dict[str, Any]) -> int:
    team_players = sum(
        len(role_players)
        for team in variant.get("teams", [])
        if isinstance(team, dict)
        for role_players in team.get("roster", {}).values()
        if isinstance(role_players, list)
    )
    benched_players = variant.get("benched_players", [])
    benched_count = len(benched_players) if isinstance(benched_players, list) else 0
    return team_players + benched_count


def _count_input_players(player_data: dict[str, Any]) -> int:
    players = player_data.get("players")
    if isinstance(players, (dict, list)):
        return len(players)
    return 0


def _enforce_upload_limit(user, uploaded_file) -> None:
    # Applies to every principal (review H5): API keys use their per-key cap,
    # session users the generous ``SESSION_LIMITS`` ceiling.
    upload_size = getattr(uploaded_file, "size", None)
    if upload_size is None:
        return
    max_upload_bytes = get_effective_limits(user)["max_upload_bytes"]
    try:
        upload_size_int = int(upload_size)
    except (TypeError, ValueError):
        return
    if upload_size_int > max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "code": "balancer_upload_too_large",
                "max_upload_bytes": max_upload_bytes,
            },
        )


def _enforce_player_limit(user, player_data: dict[str, Any]) -> None:
    player_count = _count_input_players(player_data)
    max_players = get_effective_limits(user)["max_players"]
    if player_count > max_players:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "balancer_player_limit_exceeded",
                "max_players": max_players,
            },
        )


def _build_job_urls(job_id: str) -> dict[str, str]:
    return {
        "status_url": f"/api/balancer/jobs/{job_id}",
        "result_url": f"/api/balancer/jobs/{job_id}/result",
        "stream_url": f"/api/balancer/jobs/{job_id}/stream",
    }


def get_config() -> dict:
    return get_balancer_config_payload()


def _runtime(store=None) -> JobService:
    return JobService(store=RedisMetaStore(store or get_job_store()), concurrency=Unlimited())


# The job store is Redis; neither the queue-time RPC (a read) nor the worker
# writes anything to Postgres. `emit` publishes on a session's commit, so the
# event row is the only write there is and it needs a session of its own — the
# one case where opening one here is not the old "publish from a side session
# after the fact" pattern, because there is no other transaction to ride.
# Best-effort throughout: a broadcast must never fail the job it describes.
async def _emit_job(tournament_id: int, event_type: str, **fields: Any) -> None:
    try:
        async with db.async_session_maker() as session, session.begin():
            await emit_job_lifecycle(session, tournament_id, event_type, **fields)
    except Exception:
        logger.exception("Failed to publish balancer job event", tournament_id=tournament_id)


async def _emit_job_progress(tournament_id: int, **fields: Any) -> None:
    try:
        async with db.async_session_maker() as session, session.begin():
            await emit_job_progress(session, tournament_id, **fields)
    except Exception:
        logger.exception("Failed to publish balancer job progress", tournament_id=tournament_id)


async def create_job(
    *,
    session,
    uploaded_file,
    raw_config: str | None,
    workspace_id: int,
    user,
    broker,
    tournament_id: int | None = None,
) -> CreateJobResponse:
    job_store = get_job_store()
    api_key_limiter = get_api_key_limiter()

    await api_key_limiter.check_request(user)
    _access_policy.ensure_workspace_access(user, workspace_id)
    _enforce_upload_limit(user, uploaded_file)

    player_data = await _payload_parser.parse_player_data(uploaded_file)
    config_overrides = _payload_parser.parse_config_overrides(raw_config)
    validate_api_key_config_policy(user, config_overrides)
    _enforce_player_limit(user, player_data)

    # Per-team slot counts are the tournament's, not the request's: resolved
    # here so a broken roster shape fails the call instead of the job, and so
    # the queued payload records the shape the run was accepted for.
    roster_shape = await get_effective_roster_shape(
        session,
        tournament_id=tournament_id,
        workspace_id=workspace_id,
    )

    job_id = uuid.uuid4().hex
    api_key_id = get_api_key_id(user) if is_api_key_principal(user) else None
    principal = get_principal(user)
    await api_key_limiter.reserve_job(user, job_id)

    try:
        meta = await _runtime(job_store).create(
            None,
            JobSpec(
                kind="balance",
                workspace_id=workspace_id,
                extra={
                    "player_data": player_data,
                    "config_overrides": config_overrides,
                    "job_id": job_id,
                    "tournament_id": tournament_id,
                    "created_by": user.id,
                    "credential_type": getattr(user, "_credential_type", "access_token"),
                    "api_key_id": api_key_id,
                    "role_mask": roster_shape.slots,
                },
            ),
        )
        job_id = str(meta.get("job_id") or job_id)
    except Exception:
        if principal is not None:
            await api_key_limiter.release_job(principal[0], principal[1], job_id)
        raise

    try:
        await BalancerJobPublisher(broker, logger).publish_job_requested(job_id)
    except Exception as exc:
        await _runtime(job_store).mark_failed(None, job_id, error=f"Failed to enqueue balancer job: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to enqueue balancer job",
        ) from exc

    # Broadcast to everyone with the tournament's balancer page open. Admin jobs
    # carry a tournament_id; API-key/public jobs without one are not fanned out.
    if tournament_id is not None:
        await _emit_job(
            tournament_id,
            BALANCER_JOB_QUEUED,
            job_id=job_id,
            status="queued",
            actor_user_id=user.id,
        )

    return CreateJobResponse(job_id=job_id, status="queued", **_build_job_urls(job_id))


async def create_tournament_job(
    *,
    session,
    tournament_id: int,
    raw_config: str | None,
    workspace_id: int,
    user,
    broker,
) -> CreateJobResponse:
    """Queue a balance for a tournament's own pool -- no upload, no client build.

    The algorithm's input used to be assembled in the BROWSER from the admin
    registration list, which is how the balancer and the draft ended up reading
    two different rank sources. It is built here now, by the same engine the
    draft reads (``shared.services.roster``), so the two cannot diverge again.
    """
    job_store = get_job_store()
    api_key_limiter = get_api_key_limiter()

    await api_key_limiter.check_request(user)
    _access_policy.ensure_workspace_access(user, workspace_id)

    rosters = await roster_engine.for_tournament(session, tournament_id, pool_only=True)
    player_data = roster_engine.balancer_input(rosters.values())
    if not player_data["players"]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No pool registration has a ranked role; set ranks in the balancer first",
        )
    config_overrides = _payload_parser.parse_config_overrides(raw_config)
    validate_api_key_config_policy(user, config_overrides)
    _enforce_player_limit(user, player_data)

    roster_shape = await get_effective_roster_shape(
        session,
        tournament_id=tournament_id,
        workspace_id=workspace_id,
    )

    job_id = uuid.uuid4().hex
    api_key_id = get_api_key_id(user) if is_api_key_principal(user) else None
    principal = get_principal(user)
    await api_key_limiter.reserve_job(user, job_id)

    try:
        meta = await _runtime(job_store).create(
            None,
            JobSpec(
                kind="balance",
                workspace_id=workspace_id,
                extra={
                    "player_data": player_data,
                    "config_overrides": config_overrides,
                    "job_id": job_id,
                    "tournament_id": tournament_id,
                    "created_by": user.id,
                    "credential_type": getattr(user, "_credential_type", "access_token"),
                    "api_key_id": api_key_id,
                    "role_mask": roster_shape.slots,
                },
            ),
        )
        job_id = str(meta.get("job_id") or job_id)
    except Exception:
        if principal is not None:
            await api_key_limiter.release_job(principal[0], principal[1], job_id)
        raise

    try:
        await BalancerJobPublisher(broker, logger).publish_job_requested(job_id)
    except Exception as exc:
        await _runtime(job_store).mark_failed(None, job_id, error=f"Failed to enqueue balancer job: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to enqueue balancer job",
        ) from exc

    await _emit_job(
        tournament_id,
        BALANCER_JOB_QUEUED,
        job_id=job_id,
        status="queued",
        actor_user_id=user.id,
    )
    return CreateJobResponse(job_id=job_id, status="queued", **_build_job_urls(job_id))


async def get_job_status(*, job_id: str, user) -> JobStatusResponse:
    job_store = get_job_store()
    await get_api_key_limiter().check_request(user)
    meta = await job_store.get_job_meta(job_id)
    if meta is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Balancer job not found")
    _access_policy.ensure_workspace_access(
        user,
        meta.get("workspace_id"),
        api_key_id=meta.get("api_key_id"),
        require_api_key_job_match=True,
    )
    return JobStatusResponse.model_validate(meta)


async def get_job_result(*, job_id: str, user) -> dict[str, Any]:
    job_store = get_job_store()
    await get_api_key_limiter().check_request(user)
    meta = await job_store.get_job_meta(job_id)
    if meta is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Balancer job not found")
    _access_policy.ensure_workspace_access(
        user,
        meta.get("workspace_id"),
        api_key_id=meta.get("api_key_id"),
        require_api_key_job_match=True,
    )

    status_value = meta.get("status")
    if status_value == "failed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=meta.get("error") or "Balancer job failed",
        )
    if status_value != "succeeded":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Balancer job is still {status_value}",
        )

    result = await job_store.get_job_result(job_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Balancer job result not found")
    # The worker stored this payload already normalized through
    # ``normalize_balance_job_result_payload`` (validated ``BalanceJobResult``,
    # exclude_none dump), so return the parsed dict as-is instead of
    # re-validating and re-dumping the multi-MB payload on every read.
    return result


def _build_progress_callback(event_queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
    def progress_callback(progress_payload: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(event_queue.put_nowait, progress_payload)

    return progress_callback


async def execute_balance_job(job_id: str, *, progress_clock=None) -> None:
    job_store = get_job_store()
    runtime = _runtime(job_store)
    total_started_at = time.perf_counter()
    payload = await job_store.get_job_payload(job_id)
    if payload is None:
        return

    current_meta = await runtime.get(None, job_id)
    if current_meta and current_meta.get("status") in TERMINAL_STATUSES:
        return

    # Realtime fan-out context is fixed at creation time; capture it before
    # mark_* reassigns `current_meta`. Admin jobs carry a tournament_id; jobs
    # without one (API-key/public) skip realtime broadcasting entirely.
    rt_tournament_id = current_meta.get("tournament_id") if isinstance(current_meta, dict) else None
    rt_actor_id = current_meta.get("created_by") if isinstance(current_meta, dict) else None

    async def publish_job_progress(update: dict[str, Any]) -> None:
        if rt_tournament_id is None:
            return
        await _emit_job_progress(
            int(rt_tournament_id),
            job_id=job_id,
            status=str(update.get("status", "running")),
            progress=update.get("progress"),
        )

    async def publish_job_lifecycle(
        event_type: str,
        status_value: str,
        *,
        progress: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        if rt_tournament_id is None:
            return
        await _emit_job(
            int(rt_tournament_id),
            event_type,
            job_id=job_id,
            status=status_value,
            progress=progress,
            error=error,
            actor_user_id=int(rt_actor_id) if rt_actor_id is not None else None,
        )

    event_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    loop = asyncio.get_running_loop()
    progress_callback = _build_progress_callback(event_queue, loop)
    progress_throttler: ProgressEventThrottler | None = None
    consume_task: asyncio.Task[None] | None = None
    algorithm = "tournament_balancer"
    player_count = 0
    team_count = 0
    queue_wait_seconds = 0.0
    solver_seconds = 0.0

    async def stop_progress_consumer(*, suppress_exceptions: bool) -> None:
        if consume_task is None:
            return
        if not consume_task.done():
            await event_queue.put(None)
        try:
            await consume_task
        except Exception:
            if not suppress_exceptions:
                raise

    try:
        input_data = payload.get("player_data")
        config_overrides = payload.get("config_overrides") or {}
        if not isinstance(input_data, dict):
            raise ValueError("Job payload does not contain valid player data")
        if not isinstance(config_overrides, dict):
            raise ValueError("Job payload does not contain valid config overrides")
        # Absent on jobs queued before the roster shape reached the balancer:
        # ``None`` keeps the AlgorithmConfig default mask.
        role_mask = payload.get("role_mask") or None
        if role_mask is not None and not isinstance(role_mask, dict):
            raise ValueError("Job payload does not contain a valid role mask")

        algorithm = "tournament_balancer"
        created_at = current_meta.get("created_at") if isinstance(current_meta, dict) else None
        if isinstance(created_at, (int, float)):
            queue_wait_seconds = max(0.0, time.time() - float(created_at))
        BALANCER_JOB_QUEUE_WAIT_SECONDS.labels(algorithm=algorithm).observe(queue_wait_seconds)

        players_payload = input_data.get("players", {})
        if isinstance(players_payload, dict):
            player_count = len(players_payload)

        current_meta = await runtime.mark_running(None, job_id)
        await publish_job_lifecycle(BALANCER_JOB_RUNNING, "running")
        progress_throttler = ProgressEventThrottler(
            job_store=job_store,
            job_id=job_id,
            meta=current_meta,
            clock=progress_clock,
            on_emit=publish_job_progress,
        )

        async def consume_progress_events() -> None:
            while True:
                update = await event_queue.get()
                if update is None:
                    break
                await progress_throttler.handle(update)

        consume_task = asyncio.create_task(consume_progress_events())

        await job_store.append_event(
            job_id,
            status="running",
            stage="solving",
            message=f"Running {algorithm} solver...",
            level="info",
            progress=None,
            update_meta=True,
            meta=current_meta,
        )

        solver_started_at = time.perf_counter()
        result = await asyncio.wait_for(
            run_balance(input_data, config_overrides, progress_callback, role_mask),
            timeout=_SOLVER_WATCHDOG_SECONDS,
        )
        solver_seconds = time.perf_counter() - solver_started_at
        BALANCER_SOLVER_SECONDS.labels(algorithm=algorithm).observe(solver_seconds)
        result = normalize_balance_job_result_payload(result)

        await asyncio.sleep(0)
        await stop_progress_consumer(suppress_exceptions=False)
        await progress_throttler.flush_pending()

        variants = result.get("variants", [])
        if variants:
            first_variant = variants[0]
            statistics = first_variant.get("statistics", {})
            if isinstance(statistics, dict):
                team_count = int(statistics.get("total_teams") or 0)
            if team_count <= 0:
                teams = first_variant.get("teams", [])
                if isinstance(teams, list):
                    team_count = len(teams)
            resolved_player_count = _count_variant_players(first_variant)
            if resolved_player_count > 0:
                player_count = resolved_player_count

        current_meta = await runtime.mark_succeeded(None, job_id, result=result)
        await publish_job_lifecycle(
            BALANCER_JOB_SUCCEEDED,
            "succeeded",
            progress={"percent": 100.0},
        )
        total_seconds = time.perf_counter() - total_started_at
        BALANCER_JOB_TOTAL_SECONDS.labels(algorithm=algorithm, status="succeeded").observe(total_seconds)
        # Business metric correlated with traces (Prometheus keeps the operational
        # latency histograms above); distribution of solved job sizes.
        metrics.distribution(
            "balancer.job.size",
            player_count,
            attributes={"algorithm": algorithm, "team_count": team_count},
        )
        logger.bind(
            job_id=job_id,
            algorithm=algorithm,
            player_count=player_count,
            team_count=team_count,
            progress_events_emitted=progress_throttler.emitted_count,
            queue_wait_ms=round(queue_wait_seconds * 1000, 2),
            solver_ms=round(solver_seconds * 1000, 2),
            total_ms=round(total_seconds * 1000, 2),
            events_count=current_meta.get("events_count") if isinstance(current_meta, dict) else None,
        ).info("Balancer job execution completed")
    except Exception as exc:
        if progress_throttler is not None:
            await asyncio.sleep(0)
            await stop_progress_consumer(suppress_exceptions=True)
            await progress_throttler.flush_pending()
        current_meta = await runtime.mark_failed(
            None,
            job_id,
            error=f"Balancer job failed: {exc}",
        )
        await publish_job_lifecycle(
            BALANCER_JOB_FAILED,
            "failed",
            error=f"Balancer job failed: {exc}",
        )
        total_seconds = time.perf_counter() - total_started_at
        BALANCER_JOB_TOTAL_SECONDS.labels(algorithm=algorithm, status="failed").observe(total_seconds)
        logger.bind(
            job_id=job_id,
            algorithm=algorithm,
            player_count=player_count,
            team_count=team_count,
            progress_events_emitted=progress_throttler.emitted_count if progress_throttler is not None else 0,
            queue_wait_ms=round(queue_wait_seconds * 1000, 2),
            solver_ms=round(solver_seconds * 1000, 2),
            total_ms=round(total_seconds * 1000, 2),
            events_count=current_meta.get("events_count") if isinstance(current_meta, dict) else None,
        ).error("Balancer job execution failed")
        raise
