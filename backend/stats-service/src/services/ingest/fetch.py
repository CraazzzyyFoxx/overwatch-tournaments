"""Import a match by its external id: the pending request, the worker tick that pulls it, and its admin warnings.

A tournament game's request comes from tournament-service, which authorizes the caller (a captain of the encounter,
or ``match.result``) and names the game; a pickup mix round's comes from this service's own route, authorized here
(:func:`mix_round_target`: the mix's host, a co-host, a superuser or workspace ``log.create``, the log upload's
audience). This module resolves the encounter discipline's single ``match_fetchers`` kind and keeps one
``stats.match_fetch`` row per ``(kind, external id, game)``. The worker tick calls the module's fetcher for due rows,
retrying with backoff while it raises ``MatchFetchNotReady`` until :data:`FETCH_WINDOW` after the request, then gives
up (``failed``). Fetched bytes are stored and queued exactly like an uploaded log (``logs/{tournament}/{sha256}`` or
``logs/mix/{mix}/{sha256}``, the normal ingest job carrying the game hint), so the module's decoder, binding,
``logs_official`` and evidence rules apply unchanged -- a mix round gets statistics, never a result.

Warnings are derived when an admin reads the game's requests, never stored: ``fetch_failed`` (the row gave up),
``participants_dropped`` (the bound observation seats fewer players on a team than the tournament's format starts,
or than the mix round seated - what a decoder dropping anonymous participants leaves behind) and
``banned_character_played`` (a character of the observation that the game's hero room banned).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.clients.s3 import S3Client
from shared.core import enums
from shared.core.errors import ApiExc
from shared.core.errors import BaseAPIException as HTTPException
from shared.disciplines import DISCIPLINES
from shared.disciplines.ingest import MatchFetchFailed, MatchFetchNotReady
from shared.messaging.config import ACHIEVEMENT_EVALUATE_QUEUE
from shared.messaging.outbox import enqueue_outbox_event
from shared.models import MatchFetch, MatchFetchStatus
from shared.observability import observe_scheduled_job
from shared.repository import CustomGameRepository
from shared.repository.encounter import EncounterGameRepository
from shared.repository.identity import UserRepository
from shared.repository.match_fetch import MatchFetchRepository
from shared.repository.stats import IngestJobRepository
from shared.repository.tournament import TournamentRepository
from shared.rpc.identity import ensure_workspace_permission
from shared.schemas.events import AchievementEvaluateEvent
from shared.services.distributed_lock import (
    DistributedLockUnavailable,
    acquire_distributed_lock,
    release_distributed_lock,
    renew_distributed_lock,
)
from shared.services.mix_hosts import is_mix_host
from shared.services.scheduler import IntervalScheduler
from shared.services.team_format import tournament_format
from src.core import db
from src.core.config import settings
from src.services.ingest.jobs import lock_object, provenance_classifier
from src.services.match_logs.admin_reads import _validate_attached_encounter
from src.services.match_logs.log_records import compute_content_hash, enqueue_ingest_request, log_records_service
from src.services.match_logs.realtime import emit_logs_updated

__all__ = (
    "FETCH_WINDOW",
    "list_fetches",
    "mix_round_target",
    "next_delay",
    "run_fetch_tick",
    "shutdown_scheduler",
    "source_kind_of",
    "start_scheduler",
    "submit_fetch",
)

FETCH_WINDOW = timedelta(hours=24)
TICK_SECONDS = 60
#: One lease per discipline, shared by every worker that selects it, whatever else each selects.
LEADER_LOCK_KEY = "stats:match_fetch:leader"
#: Renewed before each attempt; one attempt (a fetcher's request with its client retries, then the store) stays far
#: inside it.
LEASE_SECONDS = 3 * TICK_SECONDS
_BACKOFF_MINUTES = (1, 2, 5, 10, 20, 40)
_DUE_PER_TICK = 20
_EXTERNAL_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}")
_REASON_LIMIT = 500

_fetches = MatchFetchRepository()
_games = EncounterGameRepository()
_jobs = IngestJobRepository()
_mixes = CustomGameRepository()
_tournaments = TournamentRepository()
_users = UserRepository()
_scheduler = IntervalScheduler(job_id="match_fetch_tick", label="Match fetch tick")


def _refuse(status_code: int, code: str, msg: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail=[ApiExc(code=code, msg=msg)])


def next_delay(attempts: int) -> timedelta:
    """Wait after the ``attempts``-th miss: 1, 2, 5, 10, 20, 40 minutes, then hourly."""
    return timedelta(minutes=_BACKOFF_MINUTES[attempts - 1] if attempts <= len(_BACKOFF_MINUTES) else 60)


def source_kind_of(discipline: str) -> str:
    """The discipline's one fetchable source kind; none (or an ambiguous several) is ``unsupported_ingestor``."""
    spec = DISCIPLINES.get(discipline)
    kinds = list(spec.match_fetchers) if spec is not None else []
    if len(kinds) != 1:
        raise _refuse(422, "unsupported_ingestor", "This game has no match import")
    return kinds[0]


def _read(row: MatchFetch, warnings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "id": row.id,
        "status": str(row.status),
        "attempts": row.attempts,
        "last_error": row.last_error,
        "external_id": row.external_id,
        "created_at": row.created_at.isoformat(),
        "warnings": warnings or [],
    }


async def mix_round_target(
    session: AsyncSession, user: models.AuthUser, *, custom_game_id: int, encounter_id: int
) -> dict[str, Any]:
    """A mix round's game as :func:`submit_fetch` / :func:`list_fetches` name it, for the log upload's audience: the
    mix's host, a co-host or a superuser, else workspace ``log.create``. The mix's status is not checked: a closed mix
    still takes imports. 404 for a round of another mix, or one without a live game."""
    mix = await _mixes.get(session, custom_game_id)
    if mix is None:
        raise HTTPException(status_code=404, detail="Mix not found")
    if not await is_mix_host(session, user, custom_game_id):
        ensure_workspace_permission(user, mix.workspace_id, "log", "create")
    encounter = await _validate_attached_encounter(session, custom_game_id=custom_game_id, encounter_id=encounter_id)
    games = await _games.list_for_encounter(session, encounter.id)
    if not games:
        raise HTTPException(status_code=404, detail="Game not found")
    return {
        "workspace_id": encounter.workspace_id,
        "discipline": encounter.discipline,
        "tournament_id": None,
        "encounter_id": encounter.id,
        # A mix round is a Bo1.
        "encounter_game_id": games[0].id,
    }


async def submit_fetch(session: AsyncSession, *, data: dict[str, Any], requested_by_user_id: int | None) -> dict:
    """Request (or re-request) one game's match; idempotent per ``(kind, external id, game)``.

    ``data`` names a game its caller already authorized: ``workspace_id``, ``discipline``, ``tournament_id`` (``None``
    for a mix round), ``encounter_id``, ``encounter_game_id`` and the caller's ``external_id``. A failed request is
    reset (a fresh 24 h window); a live or done one is returned as it is. A mix round's pending match search stops: the
    round has its id.
    """
    kind = source_kind_of(data["discipline"])
    external_id = data.get("external_id")
    if not isinstance(external_id, str) or not _EXTERNAL_ID.fullmatch(external_id):
        raise _refuse(422, "invalid_external_id", "external_id must be 1-128 letters, digits or _.:-")
    game_id = int(data["encounter_game_id"])
    workspace_id = int(data["workspace_id"])
    tournament_id = data.get("tournament_id")
    # Held through the insert/reset and the commit below: a concurrent request of another game waits here and then
    # sees this one's committed row.
    await _fetches.lock_match(session, workspace_id=workspace_id, source_kind=kind, external_id=external_id)
    if await _fetches.active_elsewhere(
        session,
        workspace_id=workspace_id,
        source_kind=kind,
        external_id=external_id,
        encounter_game_id=game_id,
    ):
        raise _refuse(409, "match_already_imported", "This match is already imported for another game")
    row = await _fetches.get_or_create(
        session,
        workspace_id=workspace_id,
        discipline=data["discipline"],
        source_kind=kind,
        external_id=external_id,
        hint_tournament_id=None if tournament_id is None else int(tournament_id),
        hint_encounter_id=int(data["encounter_id"]),
        hint_encounter_game_id=game_id,
        requested_by_user_id=requested_by_user_id,
    )
    if row.status == MatchFetchStatus.FAILED:
        now = datetime.now(UTC)
        row.status, row.attempts, row.last_error, row.ingest_job_id = MatchFetchStatus.PENDING, 0, None, None
        row.created_at = row.next_attempt_at = now
        row.requested_by_user_id = requested_by_user_id
    if tournament_id is None:
        await session.execute(
            sa.update(models.MatchSearch)
            .where(
                models.MatchSearch.encounter_id == int(data["encounter_id"]),
                models.MatchSearch.status == models.MatchSearchStatus.PENDING,
            )
            .values(status=models.MatchSearchStatus.STOPPED)
        )
    read = _read(row)
    await session.commit()
    return read


async def _warnings(session: AsyncSession, row: MatchFetch) -> list[dict[str, Any]]:
    if row.status == MatchFetchStatus.FAILED:
        return [{"code": "fetch_failed", "count": None, "characters": []}]
    match = (
        await session.scalar(sa.select(models.StatsMatch).where(models.StatsMatch.ingest_job_id == row.ingest_job_id))
        if row.ingest_job_id is not None
        else None
    )
    if match is None or match.encounter_game_id is None:
        return []
    warnings: list[dict[str, Any]] = []
    team, player = models.StatsMatchTeam, models.StatsMatchPlayer
    seated = dict(
        (
            await session.execute(
                sa.select(team.encounter_team_id, sa.func.count(player.workspace_member_id))
                .select_from(team)
                .outerjoin(
                    player,
                    sa.and_(player.match_id == team.match_id, player.encounter_team_id == team.encounter_team_id),
                )
                .where(team.match_id == match.id)
                .group_by(team.encounter_team_id)
            )
        ).all()
    )
    if row.hint_tournament_id is None:
        # A mix has no format: the round's own seats are what the match should show.
        member = models.EncounterTeamMember
        expected = dict(
            (
                await session.execute(
                    sa.select(member.encounter_team_id, sa.func.count())
                    .where(member.encounter_id == match.encounter_id, member.active.is_(True))
                    .group_by(member.encounter_team_id)
                )
            ).all()
        )
    else:
        tournament = await _tournaments.get(session, row.hint_tournament_id)
        expected = dict.fromkeys(seated, (await tournament_format(session, tournament))[0].starter_min)
    if dropped := sum(max(0, expected.get(team_id, 0) - count) for team_id, count in seated.items()):
        warnings.append({"code": "participants_dropped", "count": dropped, "characters": []})
    game = await _games.get(session, match.encounter_game_id)
    entry, room, entity = models.PickBanEntry, models.PickBanSession, models.CatalogEntity
    banned = (
        sa.select(entry.item_id)
        .join(room, room.id == entry.session_id)
        .where(
            room.encounter_id == game.encounter_id,
            room.kind == enums.PickBanKind.HERO,
            entry.round == game.position,
            entry.status == enums.MapPoolEntryStatus.BANNED,
        )
    )
    played = sa.select(models.StatsFact.entity_id).where(
        models.StatsFact.match_id == match.id, models.StatsFact.entity_id.is_not(None)
    )
    names = list(
        await session.scalars(
            sa.select(entity.name).where(entity.id.in_(played), entity.id.in_(banned)).order_by(entity.name)
        )
    )
    if names:
        warnings.append({"code": "banned_character_played", "count": len(names), "characters": names})
    return warnings


async def list_fetches(session: AsyncSession, *, encounter_game_id: int, with_warnings: bool) -> list[dict]:
    """A game's requests, newest first; ``with_warnings`` for the organizer's read only."""
    rows = await _fetches.for_game(session, encounter_game_id)
    return [_read(row, await _warnings(session, row) if with_warnings else None) for row in rows]


# -- the worker tick ---------------------------------------------------------------------------------------------


def _reason(exc: BaseException, default: str) -> str:
    return (str(exc) or default)[:_REASON_LIMIT]


async def _store(session: AsyncSession, row: MatchFetch, raw: bytes, s3: S3Client) -> int:
    """The upload path's store and queue (``UploadService.store_uploaded_log_bytes``) for fetched bytes."""
    # One job per workspace's match: an existing one is the match's, whatever the producer answers now (it may
    # enrich a match later). Orphaned by a mix Undo (the round and its match deleted), it follows this request.
    job = await session.scalar(
        sa.select(models.IngestJob)
        .where(
            models.IngestJob.workspace_id == row.workspace_id,
            models.IngestJob.source_kind == row.source_kind,
            models.IngestJob.external_id == row.external_id,
        )
        .with_for_update()
    )
    if job is not None:
        if job.hint_tournament_id != row.hint_tournament_id or not await log_records_service.revive_orphan(
            session, job, encounter_id=row.hint_encounter_id, encounter_game_id=row.hint_encounter_game_id
        ):
            await enqueue_ingest_request(session, job.id, discipline=job.discipline)
        return job.id
    content_hash = compute_content_hash(raw)
    if row.hint_tournament_id is not None:
        owner = str(row.hint_tournament_id)
    else:
        mix = await session.scalar(
            sa.select(models.Encounter.custom_game_id).where(models.Encounter.id == row.hint_encounter_id)
        )
        owner = f"mix/{mix}"
    raw_ref = f"logs/{owner}/{content_hash}"
    await lock_object(session, raw_ref)
    if not await s3.put_object(raw_ref, raw):
        raise MatchFetchNotReady("raw_storage_unavailable")
    uploader_id = (
        await _users.get_id_by_auth_user_id(session, row.requested_by_user_id)
        if row.requested_by_user_id is not None
        else None
    )
    job, created = await _jobs.create_or_get(
        session,
        workspace_id=row.workspace_id,
        discipline=row.discipline,
        source_kind=row.source_kind,
        external_id=row.external_id,
        content_hash=content_hash,
        filename=f"{row.source_kind}:{row.external_id}"[:500],
        raw_ref=raw_ref,
        document_ref=None,
        uploader_user_id=uploader_id,
        api_key_id=None,
        hint_tournament_id=row.hint_tournament_id,
        hint_encounter_id=row.hint_encounter_id,
        hint_encounter_game_id=row.hint_encounter_game_id,
        classify_existing=provenance_classifier(s3),
    )
    if created:
        await emit_logs_updated(session, job.workspace_id, change="pending")
        await enqueue_outbox_event(
            session,
            AchievementEvaluateEvent(
                event_id=f"achievement:{job.workspace_id}:{job.hint_tournament_id or 0}:upload:{job.id}",
                workspace_id=job.workspace_id,
                tournament_id=job.hint_tournament_id,
                changed_tables=["stats.ingest_job"],
                source_service="stats-service",
            ),
            exchange="",
            routing_key=ACHIEVEMENT_EVALUATE_QUEUE.name,
        )
    await enqueue_ingest_request(session, job.id, discipline=job.discipline)
    return job.id


async def _settle(
    session_factory: Any, fetch_id: int, now: datetime, *, failure: str | None = None, retry: str | None = None
) -> None:
    """Record a miss: ``failure`` ends the row, ``retry`` backs it off until the window closes."""
    async with session_factory() as session:
        row = await _fetches.get_for_update(session, fetch_id)
        if row is None or row.status != MatchFetchStatus.PENDING:
            return
        row.attempts += 1
        if failure is None and now - row.created_at >= FETCH_WINDOW:
            failure = f"not_available_after_24h: {retry}"[:_REASON_LIMIT]
        if failure is not None:
            row.status, row.last_error = MatchFetchStatus.FAILED, failure
        else:
            row.next_attempt_at, row.last_error = now + next_delay(row.attempts), retry
        await session.commit()


async def _attempt(fetch_id: int, *, session_factory: Any, s3: S3Client, now: datetime) -> None:
    async with session_factory() as session:
        row = await _fetches.get(session, fetch_id)
        if row is None or row.status != MatchFetchStatus.PENDING:
            return
        spec, kind, external_id = DISCIPLINES.get(row.discipline), row.source_kind, row.external_id
    fetcher = spec.match_fetchers.get(kind) if spec is not None else None
    if fetcher is None:
        return await _settle(session_factory, fetch_id, now, failure="unsupported_ingestor")
    try:
        raw = await fetcher(external_id)
    except MatchFetchNotReady as exc:
        return await _settle(session_factory, fetch_id, now, retry=_reason(exc, "not_ready"))
    except MatchFetchFailed as exc:
        return await _settle(session_factory, fetch_id, now, failure=_reason(exc, "fetch_failed"))
    except Exception as exc:
        logger.exception("Match fetch {} ({}:{}) raised; retried", fetch_id, kind, external_id)
        return await _settle(session_factory, fetch_id, now, retry=type(exc).__name__)
    if len(raw) > settings.max_match_log_bytes:
        return await _settle(session_factory, fetch_id, now, failure="match_too_large")
    try:
        async with session_factory() as session:
            row = await _fetches.get_for_update(session, fetch_id)
            if row is None or row.status != MatchFetchStatus.PENDING:
                return None
            row.ingest_job_id = await _store(session, row, raw, s3)
            row.status, row.attempts, row.last_error = MatchFetchStatus.DONE, row.attempts + 1, None
            await session.commit()
    except MatchFetchNotReady as exc:
        return await _settle(session_factory, fetch_id, now, retry=_reason(exc, "not_ready"))
    except HTTPException as exc:
        # The job key refuses these bytes (another payload under the same external id, a provenance conflict).
        code = exc.detail.get("code") if isinstance(exc.detail, dict) else exc.detail
        return await _settle(session_factory, fetch_id, now, failure=str(code or "ingest_refused")[:_REASON_LIMIT])
    except Exception as exc:
        logger.exception("Storing match fetch {} ({}:{}) failed; retried", fetch_id, kind, external_id)
        return await _settle(session_factory, fetch_id, now, retry=type(exc).__name__)
    return None


async def _run_discipline(discipline: str, *, redis: Any, s3: S3Client, session_factory: Any, now: datetime) -> int:
    """The due requests of one discipline, under that discipline's lease (shared by every worker selecting it)."""
    try:
        token = await acquire_distributed_lock(
            redis, f"{LEADER_LOCK_KEY}:{discipline}", ttl_seconds=LEASE_SECONDS, acquire_timeout_seconds=0.5
        )
    except DistributedLockUnavailable:
        return 0
    tried = 0
    try:
        async with session_factory() as session:
            due = await _fetches.due_ids(session, now=now, limit=_DUE_PER_TICK, discipline=discipline)
        for fetch_id in due:
            # Renewed before each attempt, which is bounded well inside the lease: a lost lease stops the pass
            # before another leader's fetch of the same row can start.
            if not await renew_distributed_lock(redis, token, ttl_seconds=LEASE_SECONDS):
                logger.warning("Match fetch lease for {} lost; the pass stops", discipline)
                break
            try:
                await _attempt(fetch_id, session_factory=session_factory, s3=s3, now=now)
            except Exception:
                logger.exception("Match fetch {} failed unexpectedly; retried next tick", fetch_id)
            tried += 1
        return tried
    except Exception:
        logger.exception("Match fetch pass for {} failed", discipline)
        return tried
    finally:
        await release_distributed_lock(redis, token)


async def run_fetch_tick(
    *,
    redis: Any,
    s3: S3Client,
    disciplines: Sequence[str],
    session_factory: Any = db.async_session_maker,
    now: datetime | None = None,
) -> int:
    """One pass per selected discipline with a fetcher; returns how many requests were tried."""
    moment = now or datetime.now(UTC)
    async with observe_scheduled_job("match_fetch_tick"):
        tried = 0
        for code in sorted(set(disciplines)):
            if DISCIPLINES[code].match_fetchers:
                tried += await _run_discipline(code, redis=redis, s3=s3, session_factory=session_factory, now=moment)
        return tried


def start_scheduler(*, redis: Any, s3: S3Client, disciplines: Sequence[str]) -> None:
    if not any(DISCIPLINES[code].match_fetchers for code in disciplines):
        return
    _scheduler.start(
        run_fetch_tick, seconds=TICK_SECONDS, kwargs={"redis": redis, "s3": s3, "disciplines": list(disciplines)}
    )


def shutdown_scheduler() -> None:
    _scheduler.shutdown()
