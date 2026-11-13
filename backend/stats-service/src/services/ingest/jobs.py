"""Canonical ingest jobs: authenticated idempotent submit, tenant-scoped reads, document envelope, claim fencing.

Durability order for a submit: authorize -> parse -> validate (read-only) -> PUT raw bytes and the document envelope ->
one transaction (job + evidence + outbox request, or failed job + diagnostics) -> commit -> serialize the committed
state once. S3 success followed by a rolled-back transaction can leave an unreferenced immutable object, never a
committed job pointing at absent bytes; an identical retry reuses the same keys.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, get_args

import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.clients.s3 import S3Client
from shared.core.errors import BaseAPIException
from shared.models import AuthUser
from shared.repository.catalog import CatalogAliasMissRepository
from shared.repository.identity import UserRepository
from shared.repository.stats import IngestJobRepository
from shared.rpc.identity import credential_type
from shared.schemas.match_doc import MAX_MATCH_DOC_BYTES, IngestIssue, MatchDoc, MatchDocError, parse_match_doc
from src.schemas.ingest import IngestBinding, IngestError, IngestJobRead
from src.services.ingest.validation import DocumentRejected, validate_document
from src.services.match_logs.limits import match_log_oversize_message
from src.services.match_logs.log_records import ERROR_MESSAGE_LIMIT, enqueue_ingest_request, log_records_service
from src.services.match_logs.realtime import emit_logs_updated

__all__ = (
    "INGEST_SCOPE",
    "SEMANTIC_CODES",
    "Claim",
    "IngestRejected",
    "Producer",
    "claim_job",
    "decode_error",
    "encode_error",
    "finish_claim",
    "get_ingest_job",
    "is_current_claim",
    "load_document",
    "lock_object",
    "provenance_classifier",
    "read_job",
    "require_ingest_principal",
    "store_document",
    "submit_document",
)

INGEST_SCOPE = "stats.ingest"
Producer = Literal["canonical", "decoded"]
_PRODUCERS = frozenset(get_args(Producer))
_ENVELOPE_KEYS = frozenset({"document", "producer"})
#: Issues echoed in an error response; the persisted error keeps as many as fit ``ERROR_MESSAGE_LIMIT``.
_RESPONSE_ISSUES = 50
_jobs = IngestJobRepository()
_misses = CatalogAliasMissRepository()
_users = UserRepository()


class IngestRejected(BaseAPIException):
    """A refusal with a stable machine ``code`` and, when it persisted a failed job, that job's id.

    ``details`` becomes the RPC ``error.details`` (flat in HTTP v1), so ``ingest_job_id`` and ``issues`` reach the client.
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        issues: Sequence[IngestIssue] = (),
        ingest_job_id: int | None = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(
            status_code, {"msg": message, "code": code}, {"Retry-After": str(retry_after)} if retry_after else None
        )
        self.code = code
        self.details: dict[str, Any] = {}
        if issues:
            self.details["issues"] = [issue.to_dict() for issue in issues[:_RESPONSE_ISSUES]]
        if ingest_job_id is not None:
            self.details["ingest_job_id"] = ingest_job_id


def _unavailable(message: str) -> IngestRejected:
    return IngestRejected(503, "ingest_unavailable", message, retry_after=1)


# -- authorization ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Principal:
    workspace_id: int
    api_key_id: int


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def require_ingest_principal(user: AuthUser) -> _Principal:
    """Workspace and key come only from the rehydrated credential: a real key, its literal scope and the owner's right.

    Owner privilege, sessions and service tokens are never enough, and the workspace is the key's own, never a request
    field -- so a superuser-backed key still cannot act in another workspace.
    """
    key_id = getattr(user, "_api_key_id", None)
    workspace_id = getattr(user, "_api_key_workspace_id", None)
    if credential_type(user) != "api_key" or not _positive_int(key_id) or not _positive_int(workspace_id):
        raise IngestRejected(403, "api_key_required", "A workspace API key is required")
    scopes = getattr(user, "_api_key_scopes", None)
    if INGEST_SCOPE not in (scopes if isinstance(scopes, list) else []) or not user.has_workspace_permission(
        workspace_id, "stats", "ingest"
    ):
        raise IngestRejected(403, "scope_required", f"The API key needs the effective {INGEST_SCOPE} permission")
    return _Principal(workspace_id=workspace_id, api_key_id=key_id)


# -- document envelope -----------------------------------------------------------------------------------------


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def raw_ref_for(workspace_id: int, sha256: str) -> str:
    """Original bytes by content: never by filename or external id."""
    return f"stats/raw/{workspace_id}/{sha256}"


def envelope_for(workspace_id: int, doc: MatchDoc, producer: Producer) -> tuple[str, bytes]:
    """The envelope's content-addressed key and bytes; the key is known before anything is written."""
    if producer not in _PRODUCERS:
        raise ValueError(f"unknown producer {producer!r}")
    body = _canonical_json({"document": doc.model_dump(mode="json"), "producer": producer})
    return f"stats/documents/{workspace_id}/{hashlib.sha256(body).hexdigest()}.json", body


async def store_document(s3: S3Client, *, workspace_id: int, doc: MatchDoc, producer: Producer) -> str:
    """Write the two-field server envelope under its own hash; the envelope hash is addressing, not job identity."""
    ref, body = envelope_for(workspace_id, doc, producer)
    try:
        stored = await s3.put_object(ref, body)
    except Exception as exc:
        raise _unavailable("Document storage is unavailable") from exc
    if not stored:
        raise _unavailable("Document storage is unavailable")
    return ref


async def load_document(s3: S3Client, document_ref: str) -> tuple[MatchDoc, Producer]:
    """Fetch, validate and unwrap an envelope. Raises ``LookupError`` if absent and ``ValueError`` if malformed."""
    body = await s3.get_object(document_ref)
    if not body:
        raise LookupError("document object is missing")
    try:
        envelope = json.loads(body)
        if (
            not isinstance(envelope, dict)
            or envelope.keys() != _ENVELOPE_KEYS
            or envelope["producer"] not in _PRODUCERS
        ):
            raise ValueError("document envelope must be exactly {document, producer}")
        return MatchDoc.model_validate(envelope["document"]), envelope["producer"]
    except (ValueError, TypeError, ValidationError) as exc:
        raise ValueError("stored document envelope is invalid") from exc


def provenance_classifier(s3: S3Client):
    """Classify an existing row by its envelope's server-assigned producer; never guess from keys or FKs."""

    async def classify(row: models.IngestJob) -> Literal["canonical", "raw"]:
        try:
            _, producer = await load_document(s3, row.document_ref)
        except LookupError, ValueError:
            raise IngestRejected(
                409, "stored_document_invalid", "The existing job's stored document is missing or invalid"
            ) from None
        return "canonical" if producer == "canonical" else "raw"

    return classify


# -- structured error ------------------------------------------------------------------------------------------


def encode_error(code: str, message: str, issues: Sequence[IngestIssue] = ()) -> str:
    """Deterministic ``{code,message,issues}`` JSON for ``error_message``, shrunk (issues first) to fit its bound."""
    kept = [issue.to_dict() for issue in issues]
    while True:
        text = json.dumps(
            {"code": code, "message": message[:500], "issues": kept},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        if len(text) <= ERROR_MESSAGE_LIMIT or not kept:
            return text
        kept = kept[: len(kept) // 2]


def decode_error(stored: str | None) -> IngestError | None:
    """Structured errors round-trip; any other text is a message-only historical error, never discarded."""
    if not stored:
        return None
    try:
        data = json.loads(stored)
        if isinstance(data, dict) and {"code", "message", "issues"} <= data.keys():
            return IngestError.model_validate(data)
    except ValueError, ValidationError:
        pass
    return IngestError(code="historical", message=stored)


# -- reads -----------------------------------------------------------------------------------------------------


async def read_job(session: AsyncSession, job_id: int, workspace_id: int) -> IngestJobRead:
    """One committed-state snapshot of a workspace's job; a foreign or absent id is the same 404."""
    job = (
        await session.scalars(
            sa.select(models.IngestJob)
            .where(models.IngestJob.id == job_id, models.IngestJob.workspace_id == workspace_id)
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    if job is None:
        raise IngestRejected(404, "ingest_job_not_found", "Ingest job not found")
    match = models.StatsMatch
    rows = (
        await session.execute(
            sa.select(match.id, match.encounter_game_id, match.revision)
            .where(
                match.ingest_job_id == job.id,
                match.workspace_id == job.workspace_id,
                match.encounter_game_id.is_not(None),
            )
            .limit(2)
        )
    ).all()
    binding = (
        IngestBinding(match_id=rows[0].id, encounter_game_id=rows[0].encounter_game_id, revision=rows[0].revision)
        if len(rows) == 1
        else None
    )
    return IngestJobRead(
        id=job.id,
        workspace_id=job.workspace_id,
        discipline=job.discipline,
        source_kind=job.source_kind,
        external_id=job.external_id,
        content_hash=job.content_hash,
        status=job.status,
        attempts=job.attempts or 0,
        created_at=job.created_at,
        updated_at=job.updated_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        error=decode_error(job.error_message),
        binding=binding,
    )


async def get_ingest_job(session: AsyncSession, *, job_id: int, user: AuthUser) -> IngestJobRead:
    principal = require_ingest_principal(user)
    return await read_job(session, job_id, principal.workspace_id)


# -- submit ----------------------------------------------------------------------------------------------------


def _parse_rejection(exc: MatchDocError) -> IngestRejected:
    first = exc.issues[0]
    message = first.message
    if first.code == "document_too_large":
        return IngestRejected(413, "match_document_too_large", message)
    if first.code == "invalid_utf8":
        return IngestRejected(400, "invalid_utf8", message)
    if first.code == "invalid_json":
        return IngestRejected(400, "invalid_json", message)
    if first.code == "duplicate_key" or (first.code == "invalid_document" and not first.path):
        return IngestRejected(400, "invalid_document", message)
    if any(issue.code == "unsupported_protocol" for issue in exc.issues):
        return IngestRejected(422, "unsupported_protocol", "protocol must be exactly 'owt.match/1'", issues=exc.issues)
    return IngestRejected(422, "document_invalid", "The document does not match owt.match/1", issues=exc.issues)


SEMANTIC_CODES = {
    "unresolved_references": "unknown_code",
    "unknown_identity_provider": "document_invalid",
    "mode_map_mismatch": "mode_map_mismatch",
}


async def lock_object(session: AsyncSession, ref: str) -> None:
    # The retention sweep takes the same per-object lock, so it cannot delete bytes between this PUT and the job
    # insert that makes them reachable.
    await session.execute(sa.text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"stats.raw:{ref}"})


def _display_name(kind: str, external_id: str | None, sha256: str) -> str:
    return (f"{kind}:{external_id}" if external_id else f"{kind}-{sha256[:12]}.json")[:500]


async def submit_document(session: AsyncSession, *, raw: bytes, user: AuthUser, s3: S3Client) -> IngestJobRead:
    """Accept one ``owt.match/1`` document for the credential's own workspace; idempotent per its key.

    Returns the actual committed job: new and queued/running jobs are non-terminal, an existing job is returned as it
    is (a failed duplicate is never implicitly retried). A semantic failure for an installed discipline persists a
    failed job with its diagnostics and raises :class:`IngestRejected` (422) carrying ``ingest_job_id``.
    """
    principal = require_ingest_principal(user)
    workspace_id = principal.workspace_id
    if len(raw) > MAX_MATCH_DOC_BYTES:
        raise IngestRejected(413, "match_document_too_large", match_log_oversize_message(len(raw), MAX_MATCH_DOC_BYTES))
    try:
        doc = await asyncio.to_thread(parse_match_doc, raw)
    except MatchDocError as exc:
        raise _parse_rejection(exc) from None
    sha256 = await asyncio.to_thread(lambda: hashlib.sha256(raw).hexdigest())

    failure: DocumentRejected | None = None
    try:
        await validate_document(session, workspace_id=workspace_id, doc=doc)
    except DocumentRejected as rejected:
        if rejected.code == "unknown_discipline":
            raise IngestRejected(422, "unsupported_discipline", "Discipline is not supported") from None
        if rejected.code == "discipline_not_enabled":
            raise IngestRejected(403, "discipline_disabled", "Discipline is not enabled for this workspace") from None
        if all(issue.code == "hint_unresolved" for issue in rejected.issues):
            raise IngestRejected(404, "binding_target_not_found", "Binding target not found") from None
        failure = rejected

    uploader_id = await _users.get_id_by_auth_user_id(session, user.id)
    raw_ref = raw_ref_for(workspace_id, sha256)
    # Hints survive a vocabulary rejection when each was validated; any unresolved/disagreeing hint voids them all.
    hint = doc.hint if failure is None or not any(i.code == "hint_unresolved" for i in failure.issues) else None
    try:
        # Both object locks are taken before either PUT and held through commit, raw first, then the document:
        # the retention sweep takes them in the same order, so it cannot delete an object a new job will reference.
        document_ref, _ = envelope_for(workspace_id, doc, "canonical")
        await lock_object(session, raw_ref)
        await lock_object(session, document_ref)
        try:
            if not await s3.put_object(raw_ref, raw):
                raise _unavailable("Raw document storage is unavailable")
        except IngestRejected:
            raise
        except Exception as exc:
            raise _unavailable("Raw document storage is unavailable") from exc
        await store_document(s3, workspace_id=workspace_id, doc=doc, producer="canonical")
        job, created = await _jobs.create_or_get(
            session,
            workspace_id=workspace_id,
            discipline=doc.discipline,
            source_kind=doc.source.kind,
            external_id=doc.source.external_id,
            content_hash=sha256,
            filename=_display_name(doc.source.kind, doc.source.external_id, sha256),
            raw_ref=raw_ref,
            document_ref=document_ref,
            uploader_user_id=uploader_id,
            api_key_id=principal.api_key_id,
            hint_tournament_id=hint.tournament_id if hint else None,
            hint_encounter_id=hint.encounter_id if hint else None,
            hint_encounter_game_id=hint.encounter_game_id if hint else None,
            classify_existing=provenance_classifier(s3),
        )
        job_id = job.id
        failed_here = created and failure is not None
        if created and failure is None:
            await emit_logs_updated(session, workspace_id, change="pending")
            await enqueue_ingest_request(session, job_id, discipline=doc.discipline)
        elif failed_here:
            await log_records_service.transition(
                session,
                job,
                models.IngestJobStatus.FAILED,
                error_message=encode_error(
                    SEMANTIC_CODES.get(failure.code, "document_invalid"),
                    "The document references unknown codes or an unsupported identity provider",
                    failure.issues,
                ),
            )
            for kind, names in failure.misses().items():
                await _misses.record_miss(session, doc.discipline, kind, names, ingest_job_id=job_id)
        await session.commit()
    except SQLAlchemyError as exc:
        await session.rollback()
        raise _unavailable("Ingest storage is unavailable") from exc
    except BaseException:
        await session.rollback()
        raise
    if failed_here:
        raise IngestRejected(
            422,
            SEMANTIC_CODES.get(failure.code, "document_invalid"),
            "The document references unknown codes or an unsupported identity provider",
            issues=failure.issues,
            ingest_job_id=job_id,
        )
    return await read_job(session, job_id, workspace_id)


# -- claim fencing ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Claim:
    """A processing attempt. ``attempts`` alone cannot fence a manual retry (its budget resets), so ``started_at``
    -- strictly monotonic per job -- completes the token."""

    job_id: int
    workspace_id: int
    attempts: int
    started_at: datetime


def is_current_claim(job: models.IngestJob | None, claim: Claim) -> bool:
    return (
        job is not None
        and job.status == models.IngestJobStatus.PROCESSING
        and job.attempts == claim.attempts
        and job.started_at == claim.started_at
    )


async def claim_job(session: AsyncSession, job_id: int) -> Claim | None:
    """Move a pending job to processing under its row lock and commit the claim before any CPU/S3 work.

    ``None`` for anything not pending (duplicate delivery of a processing/done/awaiting_link/failed job does no work).
    """
    workspace_id = await session.scalar(sa.select(models.IngestJob.workspace_id).where(models.IngestJob.id == job_id))
    job = await _jobs.get_for_update(session, job_id, workspace_id=workspace_id) if workspace_id else None
    if job is None or job.status != models.IngestJobStatus.PENDING:
        await session.rollback()
        return None
    await log_records_service.transition(session, job, models.IngestJobStatus.PROCESSING)
    claim = Claim(job_id=job.id, workspace_id=job.workspace_id, attempts=job.attempts, started_at=job.started_at)
    await session.commit()
    return claim


async def finish_claim(
    session: AsyncSession,
    claim: Claim,
    status: models.IngestJobStatus,
    *,
    error_message: str | None = None,
    document_ref: str | None = None,
) -> bool:
    """Apply a terminal/pending outcome only while ``claim`` is still the job's current attempt.

    The document pointer changes in this same fenced transition, so an expired worker cannot swap the active
    attempt's document. ``False`` (nothing written) means the attempt was superseded.
    """
    job = await _jobs.get_for_update(session, claim.job_id, workspace_id=claim.workspace_id)
    if not is_current_claim(job, claim):
        await session.rollback()
        return False
    await log_records_service.transition(session, job, status, error_message=error_message, document_ref=document_ref)
    await session.commit()
    return True
