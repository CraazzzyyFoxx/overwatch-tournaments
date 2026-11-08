"""Processing a canonical ingest job: claim -> document -> validate -> bind -> one publishing transaction.

Three entry points share one publishing path (``_publish``):

* :func:`process_ingest_job` - the queue consumer. Claims the pending job (committed before any work), loads the stored
  canonical/decoded document (or decodes the raw bytes of a job that has none), validates it, looks identities up
  without creating anything and searches for the one game it provably belongs to. No game -> ``awaiting_link`` with
  zero observations and no success events. A game -> locks, materialized identities, derivation, atomic replacement.
* :func:`bind_ingest_job` - an administrator's complete team map for an ``awaiting_link``/``failed`` job. It runs the same
  validation/derivation/writer directly, under one transaction that also claims the job: the operator's map is never
  discarded by a pending round trip and no broker delivery competes for the uncommitted claim.
* :func:`reparse_ingest_job` - the explicit replay of a ``done`` job that is still the current provenance of its game,
  guarded by the revision the operator saw.

S3 reads, decoding and the vocabulary reads happen before any final lock. A semantic failure of the queue path is a
fenced ``failed`` transition (by claim token); an admin operation rolls back to the original row instead.
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.clients.s3 import S3Client
from shared.core.errors import ApiExc, ApiHTTPException, BaseAPIException
from shared.disciplines import DISCIPLINES, INGESTORS
from shared.disciplines.ingest import BoundMatch, DecodeError
from shared.models import AuthUser
from shared.repository.catalog import CatalogAliasMissRepository
from shared.repository.stats import IngestJobRepository, StatsMatchRepository
from shared.schemas.match_doc import IngestIssue, MatchDoc, MatchHint, MatchSource
from shared.services.audit import record_admin_audit
from src import schemas
from src.core.config import settings
from src.schemas.ingest import BindIngestRequest, GameObservationRead, IngestJobRead
from src.services.ingest.binding import (
    BindingMismatch,
    GameSeats,
    MapNotInPool,
    ModeNotInPool,
    bound_match,
    bound_participants,
    check_forced_teams,
    check_pool,
    check_roster_owners,
    find_binding,
    fits,
    load_game_seats,
    match_teams,
)
from src.services.ingest.decode_context import load_decode_context
from src.services.ingest.identity import IdentityConflict, lookup_identities, resolve_identities
from src.services.ingest.jobs import (
    SEMANTIC_CODES,
    Claim,
    IngestRejected,
    Producer,
    claim_job,
    encode_error,
    envelope_for,
    finish_claim,
    is_current_claim,
    load_document,
    lock_object,
    read_job,
    store_document,
)
from src.services.ingest.validation import DocumentRejected, ValidatedDocument, validate_document
from src.services.ingest.writer import ClaimSuperseded, StaleTarget, lock_owners, write_observations
from src.services.match_logs.admin_reads import record_read
from src.services.match_logs.binary import binary_match_logs
from src.services.match_logs.limits import match_log_oversize_message
from src.services.match_logs.log_records import compute_content_hash, log_records_service, reparse_observation
from src.services.match_logs.objectiveless import load_producers

__all__ = (
    "bind_ingest_job",
    "game_observation",
    "process_ingest_job",
    "reparse_authorized_job",
    "reparse_ingest_job",
    "retry_log",
)

_jobs = IngestJobRepository()
_matches = StatsMatchRepository()
_misses = CatalogAliasMissRepository()
Status = models.IngestJobStatus
_TERMINAL = {Status.DONE, Status.FAILED, Status.AWAITING_LINK}
_AWAITING_MESSAGE = "No single game could be identified from the participants; an administrator must bind the log"


# -- failures --------------------------------------------------------------------------------------------------


class IngestFailure(Exception):
    """A refusal with a stable code and, optionally, the issues that locate it."""

    def __init__(self, code: str, message: str, issues: tuple[IngestIssue, ...] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.issues = issues


class _NeedsLink(Exception):
    """The document has no provable game (or lost it under the locks): park it for an administrator."""

    def __init__(self, message: str, prepared: Prepared) -> None:
        super().__init__(message)
        self.prepared = prepared


@dataclass(frozen=True, slots=True)
class Failure:
    code: str
    message: str
    issues: tuple[IngestIssue, ...] = ()
    misses: Mapping[str, tuple[str, ...]] = dataclasses.field(default_factory=dict)


def _api_code(exc: BaseAPIException) -> tuple[str, str]:
    detail = exc.detail
    if isinstance(detail, list) and detail:
        detail = detail[0]
    if isinstance(detail, dict):
        return str(detail.get("code") or f"http_{exc.status_code}"), str(detail.get("msg") or detail.get("code"))
    text = str(detail)
    return (
        text.split(":", 1)[0] if ":" in text and " " not in text.split(":", 1)[0] else f"http_{exc.status_code}"
    ), text


def classify(exc: BaseException) -> Failure:
    """The persisted/returned explanation of an exception; everything unexpected is ``internal_error``."""
    if isinstance(exc, DocumentRejected):
        if exc.issues and all(issue.code == "hint_unresolved" for issue in exc.issues):
            return Failure("binding_target_not_found", "Binding target not found", exc.issues)
        return Failure(
            SEMANTIC_CODES.get(exc.code, "document_invalid"),
            "The document references unknown codes or an unsupported identity provider",
            exc.issues,
            exc.misses(),
        )
    if isinstance(exc, IngestFailure):
        return Failure(exc.code, str(exc), exc.issues)
    if isinstance(exc, DecodeError):
        return Failure(exc.code, str(exc), (), exc.misses())
    if isinstance(exc, (IdentityConflict, BindingMismatch, StaleTarget, MapNotInPool, ModeNotInPool)):
        return Failure(exc.code, str(exc))
    if isinstance(exc, BaseAPIException):
        code, message = _api_code(exc)
        return Failure(code, message)
    if isinstance(exc, ValueError) and str(exc).startswith("unsupported_ingestor:"):
        return Failure("unsupported_ingestor", str(exc).partition(": ")[2])
    return Failure("internal_error", f"{type(exc).__name__}: {exc}"[:500])


_ADMIN_STATUS = {
    "invalid_team_map": 422,
    "binding_mismatch": 409,
    "identity_conflict": 409,
    "binding_stale": 409,
    "map_not_in_pool": 400,
    "mode_not_in_pool": 400,
    "mode_map_mismatch": 422,
    "binding_target_not_found": 404,
    "unknown_code": 422,
    "document_invalid": 422,
}


def _reject(exc: BaseException) -> IngestRejected:
    """An admin operation's failure as the same refusal shape a submit uses; the job row stays as it was."""
    if isinstance(exc, IngestRejected):
        return exc
    if isinstance(exc, ClaimSuperseded):
        return IngestRejected(409, "ingest_busy", "The ingest job is being processed by another worker")
    failure = classify(exc)
    status = _ADMIN_STATUS.get(failure.code, exc.status_code if isinstance(exc, BaseAPIException) else 422)
    return IngestRejected(status, failure.code, failure.message, issues=failure.issues)


# -- document --------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Prepared:
    doc: MatchDoc
    producer: Producer
    #: The decoded envelope this attempt adds to the job (``None`` when the job already points at the right one).
    document_ref: str | None


def _job_hint(job: models.IngestJob) -> MatchHint | None:
    hint = MatchHint(
        tournament_id=job.hint_tournament_id,
        encounter_id=job.hint_encounter_id,
        encounter_game_id=job.hint_encounter_game_id,
    )
    return hint if hint.model_dump(exclude_none=True) else None


async def _decode(session: AsyncSession, job: models.IngestJob, raw: bytes) -> MatchDoc:
    """Raw bytes of a job -> the module decoder's canonical document, off the event loop."""
    decoder = INGESTORS.get((job.discipline, job.source_kind))
    if decoder is None:
        raise ValueError(f"unsupported_ingestor: no decoder for {job.discipline}/{job.source_kind}")
    ctx = await load_decode_context(
        session,
        discipline=job.discipline,
        source=MatchSource(kind=job.source_kind, external_id=job.external_id),
        hint=_job_hint(job),
        received_at=job.created_at,
    )
    return await asyncio.to_thread(decoder, raw, ctx)


async def _prepare(session: AsyncSession, job: models.IngestJob, s3: S3Client, *, redecode: bool = False) -> Prepared:
    """The document of ``job``: its stored envelope, or (no envelope, or a decoded one being reparsed) a fresh decode."""
    if job.document_ref:
        try:
            doc, producer = await load_document(s3, job.document_ref)
        except (LookupError, ValueError) as exc:
            raise IngestFailure(
                "stored_document_invalid", "The stored document is missing or invalid; resubmit it"
            ) from exc
        if producer == "canonical" or not redecode:
            return Prepared(doc, producer, None)
    raw = await binary_match_logs.get_log(s3, job)
    if not raw:
        raise ApiHTTPException(
            status_code=404, detail=[ApiExc(code="log_not_found", msg="Raw log is missing or empty")]
        )
    oversize = match_log_oversize_message(len(raw), settings.max_match_log_bytes, filename=job.filename)
    if oversize:
        raise ApiHTTPException(status_code=413, detail=[ApiExc(code="match_log_too_large", msg=oversize)])
    if job.content_hash is None or await asyncio.to_thread(compute_content_hash, raw) != job.content_hash.lower():
        raise ValueError("Stored raw bytes do not agree with the ingest job content hash")
    doc = await _decode(session, job, raw)
    ref, _ = envelope_for(job.workspace_id, doc, "decoded")
    return Prepared(doc, "decoded", None if ref == job.document_ref else ref)


async def _validate(
    session: AsyncSession, job: models.IngestJob, prepared: Prepared, hint: MatchHint | None
) -> ValidatedDocument:
    doc = prepared.doc.model_copy(update={"hint": hint})
    return await validate_document(session, workspace_id=job.workspace_id, doc=doc, producer=prepared.producer)


async def _store_envelope(session: AsyncSession, workspace_id: int, prepared: Prepared, s3: S3Client) -> None:
    """PUT a new decoded envelope under the object lock that is held until the transaction referencing it ends."""
    if prepared.document_ref is None:
        return
    await lock_object(session, prepared.document_ref)
    await store_document(s3, workspace_id=workspace_id, doc=prepared.doc, producer="decoded")


# -- the publishing transaction --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Admin:
    """An administrator's operation: its kind, the operator's revision precondition and complete team map."""

    kind: str  # "bind" | "reparse"
    expected_revision: int | None
    teams: Mapping[str, int]


def _check_revision(expected: int | None, match: models.StatsMatch | None) -> None:
    if match is not None and expected is None:
        raise IngestRejected(409, "expected_revision_required", "The target game already has an observation")
    if expected is not None and expected != (match.revision if match is not None else 0):
        raise IngestRejected(409, "stale_revision", "The target game's observation changed since it was read")


def _check_admin(admin: _Admin, job: models.IngestJob, match: models.StatsMatch | None) -> None:
    if job.status == Status.PROCESSING:
        raise IngestRejected(409, "ingest_busy", "The ingest job is being processed")
    if admin.kind == "bind":
        if job.status == Status.DONE:
            raise IngestRejected(409, "reparse_required", "A done job is replayed by an explicit reparse")
        if job.status == Status.PENDING:
            raise IngestRejected(409, "ingest_pending", "The ingest job is queued for processing")
    else:
        if job.status != Status.DONE:
            raise IngestRejected(409, "job_not_done", "Only a done job can be reparsed")
        if match is None or match.ingest_job_id != job.id:
            raise IngestRejected(409, "stale_binding", "The job is no longer the current evidence of its game")
    _check_revision(admin.expected_revision, match)


async def _publish(
    session: AsyncSession,
    *,
    job: models.IngestJob,
    claim: Claim | None,
    validated: ValidatedDocument,
    producer: Producer,
    binding: BoundMatch,
    known: Mapping[str, int],
    document_ref: str | None,
    producers: Mapping[int, str],
    admin: _Admin | None = None,
) -> None:
    """Take the final locks, re-verify everything under them, materialize identities, derive and replace atomically.

    The caller commits. ``claim`` is the committed processing claim; an admin operation passes ``None`` and gets its
    claim from the transition made in this very transaction.
    """
    locked = await lock_owners(
        session,
        job_id=job.id,
        workspace_id=job.workspace_id,
        discipline=job.discipline,
        encounter_id=binding.encounter_id,
        game_id=binding.encounter_game_id,
    )
    locked_job = locked.job
    if admin is not None:
        _check_admin(admin, locked_job, locked.match)
        await log_records_service.transition(session, locked_job, Status.PROCESSING)
        claim = Claim(locked_job.id, locked_job.workspace_id, locked_job.attempts, locked_job.started_at)
    elif not is_current_claim(locked_job, claim):
        raise ClaimSuperseded("the ingest claim was superseded")

    games = await load_game_seats(
        session, workspace_id=job.workspace_id, discipline=job.discipline, game_ids=[binding.encounter_game_id]
    )
    if not games or games[0].encounter_id != binding.encounter_id or not fits(games[0], validated):
        raise StaleTarget("the target game changed before it was locked")
    game: GameSeats = games[0]
    await check_pool(session, encounter_id=binding.encounter_id, map_id=validated.map_id, mode_id=validated.mode_id)
    if admin is not None:
        check_forced_teams(validated.doc, known, game, admin.teams)
        teams = dict(admin.teams)
    else:
        verdict, teams = match_teams(validated.doc, known, game)
        if verdict != "bound" or teams != dict(binding.team_ids):
            raise StaleTarget("the roster evidence no longer proves this binding")
    binding = bound_match(job.workspace_id, job.discipline, game, teams)

    members = await resolve_identities(session, workspace_id=job.workspace_id, doc=validated.doc, producer=producer)
    participants = await bound_participants(session, doc=validated.doc, binding=binding, game=game, members=members)
    binding = dataclasses.replace(
        binding, participants=participants, basis_game_result_version=locked.game.result_version
    )
    final = validated
    derive = DISCIPLINES[job.discipline].derive_match
    if producer == "decoded" and derive is not None:
        derived = await derive(session, validated.doc, binding)
        final = await validate_document(session, workspace_id=job.workspace_id, doc=derived, producer="decoded")
    await write_observations(
        session,
        job=locked_job,
        claim_token=(claim.attempts, claim.started_at),
        doc=final,
        binding=binding,
        document_ref=document_ref,
        producers={**producers, job.id: producer},
    )


# -- queue path ------------------------------------------------------------------------------------------------


async def _fresh_job(session: AsyncSession, job_id: int) -> models.IngestJob:
    return (
        await session.scalars(
            sa.select(models.IngestJob).where(models.IngestJob.id == job_id).execution_options(populate_existing=True)
        )
    ).one()


async def _status_of(session: AsyncSession, job_id: int) -> Status | None:
    return await session.scalar(sa.select(models.IngestJob.status).where(models.IngestJob.id == job_id))


async def _run(session: AsyncSession, claim: Claim, s3: S3Client) -> None:
    job = await _fresh_job(session, claim.job_id)
    linked = await reparse_observation(session, job)
    prepared = await _prepare(session, job, s3)
    hint = _job_hint(job)
    validated = await _validate(session, job, prepared, hint)
    await _store_envelope(session, job.workspace_id, prepared, s3)
    known = await lookup_identities(
        session, workspace_id=job.workspace_id, doc=validated.doc, producer=prepared.producer
    )
    binding = await find_binding(
        session,
        workspace_id=job.workspace_id,
        doc=validated,
        known_players=known,
        hint=hint,
        linked_game_id=None if linked is None else linked.encounter_game_id,
    )
    if binding is None:
        raise _NeedsLink(_AWAITING_MESSAGE, prepared)
    producers = await load_producers(session, s3, binding.encounter_id)
    try:
        await _publish(
            session,
            job=job,
            claim=claim,
            validated=validated,
            producer=prepared.producer,
            binding=binding,
            known=known,
            document_ref=prepared.document_ref,
            producers=producers,
        )
    except StaleTarget as exc:
        # The roster or the game moved between the search and the locks: the evidence no longer proves a binding.
        raise _NeedsLink(str(exc), prepared) from exc
    await session.commit()


async def _fail(session: AsyncSession, claim: Claim, failure: Failure) -> bool:
    job = await _jobs.get_for_update(session, claim.job_id, workspace_id=claim.workspace_id)
    if not is_current_claim(job, claim):
        await session.rollback()
        return False
    for kind, names in failure.misses.items():
        await _misses.record_miss(session, job.discipline, kind, names, ingest_job_id=job.id)
    await log_records_service.transition(
        session, job, Status.FAILED, error_message=encode_error(failure.code, failure.message, failure.issues)
    )
    await session.commit()
    return True


async def process_ingest_job(
    session: AsyncSession, job_id: int, s3: S3Client, *, is_raise: bool = True
) -> models.IngestJobStatus:
    """Process one queued job. Returns the job's committed status; ``PROCESSING`` = another delivery owns the claim."""
    claim = await claim_job(session, job_id)
    if claim is None:
        # Not pending: a duplicate delivery of a finished, parked or running job does no work.
        status = await _status_of(session, job_id)
        await session.rollback()
        if status is None:
            raise ApiHTTPException(status_code=404, detail=[ApiExc(code="not_found", msg="Ingest job not found")])
        return status
    try:
        await _run(session, claim, s3)
        return Status.DONE
    except ClaimSuperseded:
        await session.rollback()
        current = await _status_of(session, job_id)
        await session.rollback()
        return current if current in _TERMINAL else Status.PROCESSING
    except _NeedsLink as parked:
        await session.rollback()
        issues = (IngestIssue(["teams"], "awaiting_link", str(parked)),)
        try:
            # The rollback released the envelope's object lock: take it again before the pointer is committed.
            await _store_envelope(session, claim.workspace_id, parked.prepared, s3)
        except Exception as exc:
            await session.rollback()
            if not await _fail(session, claim, classify(exc)):
                raise
            if is_raise:
                raise
            return Status.FAILED
        if await finish_claim(
            session,
            claim,
            Status.AWAITING_LINK,
            error_message=encode_error("awaiting_link", str(parked), issues),
            document_ref=parked.prepared.document_ref,
        ):
            return Status.AWAITING_LINK
        current = await _status_of(session, job_id)
        await session.rollback()
        return current if current in _TERMINAL else Status.PROCESSING
    except Exception as exc:
        await session.rollback()
        if not await _fail(session, claim, classify(exc)):
            current = await _status_of(session, job_id)
            await session.rollback()
            if current in _TERMINAL:
                return current
            raise
        if is_raise:
            raise
        return Status.FAILED


# -- admin paths -----------------------------------------------------------------------------------------------


def _authorize(user: AuthUser, job: models.IngestJob) -> None:
    if not user.has_workspace_permission(job.workspace_id, "log", "update"):
        raise IngestRejected(
            403, "forbidden", f"Permission denied for workspace {job.workspace_id}: log.update required"
        )


async def _load_job(session: AsyncSession, job_id: int, user: AuthUser) -> models.IngestJob:
    job = await _jobs.get(session, job_id, populate_existing=True)
    if job is None:
        raise IngestRejected(404, "ingest_job_not_found", "Ingest job not found")
    _authorize(user, job)
    return job


async def _prepare_admin(
    session: AsyncSession, job: models.IngestJob, s3: S3Client, *, redecode: bool
) -> tuple[Prepared, ValidatedDocument]:
    """Everything an admin operation computes before any final lock: the document, validation (no hint: the operator's
    explicit target outranks the candidate constraint), and the store of a new decoded envelope."""
    try:
        prepared = await _prepare(session, job, s3, redecode=redecode)
        validated = await _validate(session, job, prepared, None)
    except Exception as exc:
        raise _reject(exc) from exc
    return prepared, validated


async def _run_admin(
    session: AsyncSession,
    *,
    job: models.IngestJob,
    prepared: Prepared,
    validated: ValidatedDocument,
    game: GameSeats,
    admin: _Admin,
    s3: S3Client,
) -> IngestJobRead:
    try:
        await _store_envelope(session, job.workspace_id, prepared, s3)
        known = await lookup_identities(
            session, workspace_id=job.workspace_id, doc=validated.doc, producer=prepared.producer
        )
        # A position that names no map yet (e.g. one a whole-series report cancelled) accepts the log's map.
        if not fits(game, validated):
            raise BindingMismatch("the target game is played on another map or mode than the document's")
        check_forced_teams(validated.doc, known, game, admin.teams)
        await check_roster_owners(
            session, workspace_id=job.workspace_id, doc=validated.doc, known=known, game=game, teams=admin.teams
        )
        binding = bound_match(job.workspace_id, job.discipline, game, admin.teams)
        producers = await load_producers(session, s3, game.encounter_id)
        await _publish(
            session,
            job=job,
            claim=None,
            validated=validated,
            producer=prepared.producer,
            binding=binding,
            known=known,
            document_ref=prepared.document_ref,
            producers=producers,
            admin=admin,
        )
        await session.commit()
    except SQLAlchemyError as exc:
        await session.rollback()
        raise IngestRejected(503, "ingest_unavailable", "Ingest storage is unavailable", retry_after=1) from exc
    except BaseException as exc:
        await session.rollback()
        if isinstance(exc, Exception):
            raise _reject(exc) from exc
        raise
    return await read_job(session, job.id, job.workspace_id)


async def bind_ingest_job(
    session: AsyncSession,
    *,
    job_id: int,
    request: BindIngestRequest,
    user: AuthUser,
    s3: S3Client,
    data: dict[str, Any] | None = None,
) -> IngestJobRead:
    """Bind an ``awaiting_link``/``failed`` job to the operator's game and team map and publish it, atomically.

    ``data`` is the operator's request: when given, the bind is audited in the same transaction.
    """
    job = await _load_job(session, job_id, user)
    if data is not None:
        await record_admin_audit(
            session,
            action="match_log.bind",
            actor=user,
            data=data,
            workspace_id=job.workspace_id,
            entity_type="match_log",
            entity_id=job_id,
            after={"encounter_game_id": request.encounter_game_id, "expected_revision": request.expected_revision},
        )
    if job.status != Status.AWAITING_LINK and job.status != Status.FAILED:
        _check_admin(_Admin("bind", None, {}), job, None)
    try:
        linked = await reparse_observation(session, job)
    except BaseAPIException as exc:
        raise IngestRejected(409, _api_code(exc)[0], _api_code(exc)[1]) from exc
    if linked is not None:
        raise IngestRejected(409, "already_bound", "The job already owns an observation: reparse it instead")
    games = await load_game_seats(
        session, workspace_id=job.workspace_id, discipline=job.discipline, game_ids=[request.encounter_game_id]
    )
    if not games:
        raise IngestRejected(404, "binding_target_not_found", "Binding target not found")
    game = games[0]
    prepared, validated = await _prepare_admin(session, job, s3, redecode=False)
    # Fast refusal on the operator's view of the target; compared again under the final lock.
    _check_revision(
        request.expected_revision,
        await _matches.get_for_game(
            session, encounter_game_id=game.game_id, workspace_id=job.workspace_id, discipline=job.discipline
        ),
    )
    return await _run_admin(
        session,
        job=job,
        prepared=prepared,
        validated=validated,
        game=game,
        admin=_Admin("bind", request.expected_revision, dict(request.teams)),
        s3=s3,
    )


async def reparse_ingest_job(
    session: AsyncSession, *, job_id: int, expected_revision: int, user: AuthUser, s3: S3Client
) -> IngestJobRead:
    """Replay a ``done`` job that is still its game's current provenance, replacing the observations (revision + 1).

    The team mapping is the one the observation was written with: the stored document's ordered team keys joined to
    the match's ``source_position`` rows. A decoded job decodes its original raw bytes anew; a canonical one reloads
    its stored document and never runs raw decoding or derivation.
    """
    job = await _load_job(session, job_id, user)
    return await _reparse(session, job, expected_revision, s3)


async def retry_log(
    session: AsyncSession,
    *,
    job_id: int,
    workspace_id: int,
    request: schemas.LogRetryRequest,
    user: AuthUser,
    data: dict[str, Any],
    s3: S3Client,
) -> schemas.LogRecordRead:
    """Re-pend a log (optionally re-attaching it), or with ``reparse`` replay a done one under the revision the operator
    saw; either way audited, and answered with the record as the history lists it."""
    if request.reparse:
        if request.expected_revision is None or request.expected_revision < 1:
            raise BaseAPIException(status_code=422, detail="reparse requires expected_revision (the revision seen)")
        if request.encounter_id is not None or request.encounter_game_id is not None:
            raise BaseAPIException(status_code=422, detail="reparse cannot re-attach a log")
        after = {"expected_revision": request.expected_revision}
    elif request.expected_revision is not None:
        raise BaseAPIException(status_code=422, detail="expected_revision is only valid with reparse")
    else:
        after = {"attached_encounter_id": request.encounter_id} if request.encounter_id is not None else None
    await record_admin_audit(
        session,
        action="match_log.reparse" if request.reparse else "match_log.retry",
        actor=user,
        data=data,
        workspace_id=workspace_id,
        entity_type="match_log",
        entity_id=job_id,
        after=after,
    )
    if request.reparse:
        await reparse_ingest_job(session, job_id=job_id, expected_revision=request.expected_revision, user=user, s3=s3)
    else:
        await log_records_service.retry(
            session,
            job_id,
            workspace_id=workspace_id,
            encounter_id=request.encounter_id,
            encounter_game_id=request.encounter_game_id,
        )
    return await record_read(session, job_id)


async def reparse_authorized_job(
    session: AsyncSession, *, job_id: int, expected_revision: int, s3: S3Client
) -> IngestJobRead:
    """The same reparse for a caller that already carries its own authorization (the tournament-wide operation)."""
    job = await _jobs.get(session, job_id, populate_existing=True)
    if job is None:
        raise IngestRejected(404, "ingest_job_not_found", "Ingest job not found")
    return await _reparse(session, job, expected_revision, s3)


async def _reparse(session: AsyncSession, job: models.IngestJob, expected_revision: int, s3: S3Client) -> IngestJobRead:
    if job.status != Status.DONE:
        _check_admin(_Admin("reparse", expected_revision, {}), job, None)
    try:
        linked = await reparse_observation(session, job)
    except BaseAPIException as exc:
        raise IngestRejected(409, _api_code(exc)[0], _api_code(exc)[1]) from exc
    if linked is None or linked.ingest_job_id != job.id:
        raise IngestRejected(409, "stale_binding", "The job is no longer the current evidence of its game")
    _check_revision(expected_revision, linked)
    seats = list(
        await session.scalars(
            sa.select(models.StatsMatchTeam.encounter_team_id)
            .where(models.StatsMatchTeam.match_id == linked.id)
            .order_by(models.StatsMatchTeam.source_position)
        )
    )
    games = await load_game_seats(
        session, workspace_id=job.workspace_id, discipline=job.discipline, game_ids=[linked.encounter_game_id]
    )
    if not games:
        raise IngestRejected(409, "stale_binding", "The observation's game no longer exists")
    prepared, validated = await _prepare_admin(session, job, s3, redecode=True)
    if len(seats) != len(validated.doc.teams):
        raise IngestRejected(409, "stale_binding", "The stored document no longer matches the observation's teams")
    teams = {team.key: seat for team, seat in zip(validated.doc.teams, seats, strict=True)}
    return await _run_admin(
        session,
        job=job,
        prepared=prepared,
        validated=validated,
        game=games[0],
        admin=_Admin("reparse", expected_revision, teams),
        s3=s3,
    )


async def game_observation(session: AsyncSession, *, encounter_game_id: int, user: AuthUser) -> GameObservationRead:
    """The game's current observation (workspace ``log.read``); unoccupied games answer revision 0."""
    workspace_id = await session.scalar(
        sa.select(models.Encounter.workspace_id)
        .join(models.EncounterGame, models.EncounterGame.encounter_id == models.Encounter.id)
        .where(models.EncounterGame.id == encounter_game_id)
    )
    if workspace_id is None:
        raise IngestRejected(404, "binding_target_not_found", "Binding target not found")
    if not user.has_workspace_permission(workspace_id, "log", "read"):
        raise IngestRejected(403, "forbidden", f"Permission denied for workspace {workspace_id}: log.read required")
    row = (
        await session.execute(
            sa.select(
                models.StatsMatch.id,
                models.StatsMatch.revision,
                models.StatsMatch.ingest_job_id,
                models.IngestJob.source_kind,
                models.IngestJob.external_id,
            )
            .outerjoin(models.IngestJob, models.IngestJob.id == models.StatsMatch.ingest_job_id)
            .where(
                models.StatsMatch.encounter_game_id == encounter_game_id,
                models.StatsMatch.workspace_id == workspace_id,
            )
        )
    ).first()
    if row is None:
        return GameObservationRead(encounter_game_id=encounter_game_id)
    historical = (
        row.ingest_job_id is None
        or row.source_kind == "historical_reference"
        or (row.external_id or "").startswith("legacy:")
    )
    return GameObservationRead(
        encounter_game_id=encounter_game_id,
        match_id=row.id,
        revision=row.revision,
        ingest_job_id=row.ingest_job_id,
        is_historical=historical,
    )
