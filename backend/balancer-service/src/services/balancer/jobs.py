from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import HTTPException, Request, status
from loguru import logger

from shared.observability import metrics
from shared.services.balancer_realtime import (
    BALANCER_JOB_FAILED,
    BALANCER_JOB_QUEUED,
    BALANCER_JOB_RUNNING,
    BALANCER_JOB_SUCCEEDED,
)
from src.core.job_store import get_job_store
from src.core.metrics import (
    BALANCER_JOB_QUEUE_WAIT_SECONDS,
    BALANCER_JOB_TOTAL_SECONDS,
    BALANCER_SOLVER_SECONDS,
)
from src.core.security.api_key_limiter import (
    get_api_key_id,
    get_api_key_limiter,
    get_api_key_limits,
    is_api_key_principal,
)
from src.core.security.api_key_policy import validate_api_key_config_policy
from src.core.security.workspace_access import WorkspaceAccessPolicy
from src.schemas.balancer import BalanceJobResult, CreateJobResponse, JobStatusResponse
from src.services.balancer.config.provider import get_balancer_config_payload
from src.services.balancer.config.public_contract import normalize_balance_job_result_payload
from src.services.balancer.progress import (
    TERMINAL_STATUSES,
    ProgressEventThrottler,
)
from src.services.balancer.publisher import BalancerJobPublisher
from src.services.balancer.realtime import (
    emit_balancer_job_event,
    emit_balancer_job_progress,
)
from src.services.balancer.request_parser import BalancerRequestParser
from src.services.balancer.solver import run_balance

_access_policy = WorkspaceAccessPolicy()
_payload_parser = BalancerRequestParser()


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


def _enforce_api_key_upload_limit(user, uploaded_file) -> None:
    if not is_api_key_principal(user):
        return
    upload_size = getattr(uploaded_file, "size", None)
    if upload_size is None:
        return
    max_upload_bytes = get_api_key_limits(user)["max_upload_bytes"]
    try:
        upload_size_int = int(upload_size)
    except (TypeError, ValueError):
        return
    if upload_size_int > max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "code": "api_key_upload_too_large",
                "max_upload_bytes": max_upload_bytes,
            },
        )


def _enforce_api_key_player_limit(user, player_data: dict[str, Any]) -> None:
    if not is_api_key_principal(user):
        return
    player_count = _count_input_players(player_data)
    max_players = get_api_key_limits(user)["max_players"]
    if player_count > max_players:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "api_key_player_limit_exceeded",
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


async def create_job(
    *,
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
    _enforce_api_key_upload_limit(user, uploaded_file)

    player_data = await _payload_parser.parse_player_data(uploaded_file)
    config_overrides = _payload_parser.parse_config_overrides(raw_config)
    validate_api_key_config_policy(user, config_overrides)
    _enforce_api_key_player_limit(user, player_data)

    job_id = uuid.uuid4().hex
    api_key_id = get_api_key_id(user) if is_api_key_principal(user) else None
    await api_key_limiter.reserve_job(user, job_id)

    try:
        job_id = await job_store.create_job(
            player_data,
            config_overrides,
            job_id=job_id,
            workspace_id=workspace_id,
            tournament_id=tournament_id,
            created_by=user.id,
            credential_type=getattr(user, "_credential_type", "access_token"),
            api_key_id=api_key_id,
        )
    except Exception:
        if api_key_id is not None:
            await api_key_limiter.release_job(api_key_id, job_id)
        raise

    try:
        await BalancerJobPublisher(broker, logger).publish_job_requested(job_id)
    except Exception as exc:
        await job_store.mark_failed(job_id, f"Failed to enqueue balancer job: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to enqueue balancer job",
        ) from exc

    # Broadcast to everyone with the tournament's balancer page open. Admin jobs
    # carry a tournament_id; API-key/public jobs without one are not fanned out.
    if tournament_id is not None:
        await emit_balancer_job_event(
            tournament_id,
            BALANCER_JOB_QUEUED,
            job_id=job_id,
            status="queued",
            workspace_id=workspace_id,
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


async def get_job_result(*, job_id: str, user) -> BalanceJobResult:
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
    return BalanceJobResult.model_validate(result)


async def stream_job_events(
    *,
    request: Request,
    job_id: str,
    after_event_id: int,
    last_event_id: str | None,
    user,
) -> AsyncIterator[str]:
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

    cursor = after_event_id
    if last_event_id and last_event_id.isdigit():
        cursor = max(cursor, int(last_event_id))

    async def event_generator() -> AsyncIterator[str]:
        next_cursor = cursor
        while True:
            if await request.is_disconnected():
                break

            events = await job_store.get_events_since(job_id, next_cursor)
            for event in events:
                next_cursor = max(next_cursor, int(event["event_id"]))
                yield f"id: {event['event_id']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"

            current_meta = await job_store.get_job_meta(job_id)
            if current_meta is None:
                break
            if current_meta.get("status") in TERMINAL_STATUSES and not events:
                break

            yield ": heartbeat\n\n"
            await asyncio.sleep(1)

    return event_generator()


def _build_progress_callback(event_queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
    def progress_callback(progress_payload: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(event_queue.put_nowait, progress_payload)

    return progress_callback


async def execute_balance_job(job_id: str, *, progress_clock=None) -> None:
    job_store = get_job_store()
    total_started_at = time.perf_counter()
    payload = await job_store.get_job_payload(job_id)
    if payload is None:
        return

    current_meta = await job_store.get_job_meta(job_id)
    if current_meta and current_meta.get("status") in TERMINAL_STATUSES:
        return

    # Realtime fan-out context is fixed at creation time; capture it before
    # mark_* reassigns `current_meta`. Admin jobs carry a tournament_id; jobs
    # without one (API-key/public) skip realtime broadcasting entirely.
    rt_tournament_id = current_meta.get("tournament_id") if isinstance(current_meta, dict) else None
    rt_workspace_id = current_meta.get("workspace_id") if isinstance(current_meta, dict) else None
    rt_actor_id = current_meta.get("created_by") if isinstance(current_meta, dict) else None

    async def publish_job_progress(update: dict[str, Any]) -> None:
        if rt_tournament_id is None:
            return
        await emit_balancer_job_progress(
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
        await emit_balancer_job_event(
            int(rt_tournament_id),
            event_type,
            job_id=job_id,
            status=status_value,
            progress=progress,
            error=error,
            workspace_id=int(rt_workspace_id) if rt_workspace_id is not None else None,
            actor_user_id=int(rt_actor_id) if rt_actor_id is not None else None,
        )

    event_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    loop = asyncio.get_running_loop()
    progress_callback = _build_progress_callback(event_queue, loop)
    progress_throttler: ProgressEventThrottler | None = None
    consume_task: asyncio.Task[None] | None = None
    algorithm = "moo"
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

        algorithm = "moo"
        created_at = current_meta.get("created_at") if isinstance(current_meta, dict) else None
        if isinstance(created_at, (int, float)):
            queue_wait_seconds = max(0.0, time.time() - float(created_at))
        BALANCER_JOB_QUEUE_WAIT_SECONDS.labels(algorithm=algorithm).observe(queue_wait_seconds)

        players_payload = input_data.get("players", {})
        if isinstance(players_payload, dict):
            player_count = len(players_payload)

        current_meta = await job_store.mark_running(job_id, meta=current_meta)
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
        result = await run_balance(input_data, config_overrides, progress_callback)
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

        current_meta = await job_store.mark_succeeded(job_id, result, meta=current_meta)
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

        current_meta = await job_store.mark_failed(
            job_id,
            f"Balancer job failed: {exc}",
            meta=current_meta,
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
