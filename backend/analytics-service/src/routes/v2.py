"""HTTP endpoints exposing the v2 ML analytics outputs.

Each endpoint reads from one ``analytics.*`` table populated by the
:mod:`src.services.ml.inference.runner` worker:

- ``GET /v2/performance``         → ``analytics.performance``
- ``GET /v2/standings/distribution``→ ``analytics.standings_distribution``
- ``GET /v2/match-quality``       → ``analytics.match_quality``
- ``GET /v2/explain/player/...``  → ``analytics.explanation`` (denormalised
  top-5 SHAP contributions are also embedded in ``analytics.performance``).

Routes are auth-gated via ``shared.core.auth`` like the v1 surface; an
authenticated read with the ``analytics.read`` permission is required.
"""

from __future__ import annotations

import logging
import typing
from datetime import datetime

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from shared.messaging.config import (
    ANALYTICS_INFER_QUEUE,
    ANALYTICS_JOB_QUEUE,
    ANALYTICS_TRAIN_QUEUE,
)
from shared.observability import publish_message
from shared.schemas.events import (
    AnalyticsInferRequest,
    AnalyticsJobRequested,
    AnalyticsTrainRequest,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.core import auth, config, db, enums
from src.core.messaging import ensure_broker
from src.core.workspace import WorkspaceQuery
from src.services.jobs import (
    JOB_KIND_TRAIN_ML,
    ActiveJobConflict,
    create_job,
    get_active_job,
    get_job,
    list_jobs,
    mark_job_failed,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v2", tags=[enums.RouteTag.ANALYTICS])


# ---------------------------------------------------------------------------
# Response schemas (kept minimal — frontend consumers fan in from here).
# ---------------------------------------------------------------------------


class PerformanceRow(BaseModel):
    tournament_id: int
    player_id: int
    algorithm_id: int
    impact_score: float
    raw_value: float
    confidence: float
    log_coverage: float
    local_mean: float
    local_std: float
    local_residual: float
    local_zscore: float
    local_percentile: float
    local_reference_n: int
    local_band_min_div: int | None = None
    local_band_max_div: int | None = None
    top_features: list[dict] | None = None


class StandingsRow(BaseModel):
    tournament_id: int
    team_id: int
    algorithm_id: int
    mean_position: float
    median_position: float
    p10_position: float
    p90_position: float
    prob_top1: float
    prob_top3: float
    prob_top8: float
    position_histogram: dict


class MatchQualityRow(BaseModel):
    encounter_id: int
    algorithm_id: int
    competitiveness: float
    predictability: float
    skill_balance: float
    quality_score: float
    anomaly_flags: list[dict] | None = None


class ExplanationRow(BaseModel):
    algorithm_id: int
    entity_id: int
    entity_kind: str
    tournament_id: int
    base_value: float
    contributions: list[dict]


class MLArtifactRow(BaseModel):
    id: int
    algorithm_id: int
    model_kind: str
    role: str | None
    version: str
    storage_uri: str
    feature_version: str
    training_cutoff_tournament_id: int | None
    metrics: dict | None
    feature_importance: dict | None
    is_active: bool
    created_at: datetime
    updated_at: datetime | None


class TrainRequestBody(BaseModel):
    cutoff_tournament_id: int
    model_kinds: list[str] | None = None
    workspace_id: int | None = None
    workspace_ids: list[int] | None = Field(
        default=None,
        description=(
            "Training data scope. None means all workspaces; a list limits "
            "the training sample to those workspace IDs."
        ),
    )


class InferRequestBody(BaseModel):
    tournament_id: int
    model_kinds: list[str] | None = None
    workspace_id: int | None = None


class JobAcceptedResponse(BaseModel):
    message: str
    job: str  # "train" | "infer"
    correlation_id: str


class PlayerAnomalyRow(BaseModel):
    tournament_id: int
    player_id: int
    kind: str
    score: float
    confidence: float
    reasons: list[str]
    evidence: dict | None = None
    source_encounter_id: int | None = None


class AnomalyFeedbackRow(BaseModel):
    id: int
    tournament_id: int
    player_id: int
    kind: str
    verdict: str
    reviewer_user_id: int | None = None
    note: str | None = None


class AnomalyFeedbackBody(BaseModel):
    tournament_id: int
    player_id: int
    kind: str
    verdict: typing.Literal["confirmed", "dismissed"]
    note: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/performance", response_model=list[PerformanceRow])
async def list_performance(
    tournament_id: int = Query(..., description="Tournament id"),
    algorithm_id: int | None = Query(None, description="Filter to a single algorithm"),
    _user=Depends(auth.require_permission("analytics", "read")),
    session: AsyncSession = Depends(db.get_async_session),
) -> typing.Sequence[models.AnalyticsPerformance]:
    query = sa.select(models.AnalyticsPerformance).where(
        models.AnalyticsPerformance.tournament_id == tournament_id
    )
    if algorithm_id is not None:
        query = query.where(models.AnalyticsPerformance.algorithm_id == algorithm_id)
    result = await session.execute(query)
    return result.scalars().all()


@router.get("/standings/distribution", response_model=list[StandingsRow])
async def list_standings_distribution(
    tournament_id: int = Query(...),
    algorithm_id: int | None = Query(None),
    _user=Depends(auth.require_permission("analytics", "read")),
    session: AsyncSession = Depends(db.get_async_session),
) -> typing.Sequence[models.AnalyticsStandingsDistribution]:
    query = sa.select(models.AnalyticsStandingsDistribution).where(
        models.AnalyticsStandingsDistribution.tournament_id == tournament_id
    )
    if algorithm_id is not None:
        query = query.where(
            models.AnalyticsStandingsDistribution.algorithm_id == algorithm_id
        )
    result = await session.execute(query)
    return result.scalars().all()


@router.get("/match-quality", response_model=list[MatchQualityRow])
async def list_match_quality(
    tournament_id: int = Query(...),
    algorithm_id: int | None = Query(None),
    _user=Depends(auth.require_permission("analytics", "read")),
    session: AsyncSession = Depends(db.get_async_session),
) -> typing.Sequence[models.AnalyticsMatchQuality]:
    query = (
        sa.select(models.AnalyticsMatchQuality)
        .join(
            models.Encounter,
            models.Encounter.id == models.AnalyticsMatchQuality.encounter_id,
        )
        .where(models.Encounter.tournament_id == tournament_id)
    )
    if algorithm_id is not None:
        query = query.where(models.AnalyticsMatchQuality.algorithm_id == algorithm_id)
    result = await session.execute(query)
    return result.scalars().all()


@router.get("/player-anomalies", response_model=list[PlayerAnomalyRow])
async def list_player_anomalies(
    tournament_id: int = Query(...),
    player_id: int | None = Query(None),
    kind: str | None = Query(None),
    _user=Depends(auth.require_permission("analytics", "read")),
    session: AsyncSession = Depends(db.get_async_session),
) -> typing.Sequence[models.AnalyticsPlayerAnomaly]:
    query = sa.select(models.AnalyticsPlayerAnomaly).where(
        models.AnalyticsPlayerAnomaly.tournament_id == tournament_id
    )
    if player_id is not None:
        query = query.where(models.AnalyticsPlayerAnomaly.player_id == player_id)
    if kind is not None:
        query = query.where(models.AnalyticsPlayerAnomaly.kind == kind)
    result = await session.execute(query)
    return result.scalars().all()


@router.get("/player-anomalies/feedback", response_model=list[AnomalyFeedbackRow])
async def list_anomaly_feedback(
    tournament_id: int = Query(...),
    _user=Depends(auth.require_permission("analytics", "read")),
    session: AsyncSession = Depends(db.get_async_session),
) -> typing.Sequence[models.AnalyticsAnomalyFeedback]:
    """Reviewer verdicts for a tournament so the UI can show confirm/dismiss state."""
    result = await session.scalars(
        sa.select(models.AnalyticsAnomalyFeedback).where(
            models.AnalyticsAnomalyFeedback.tournament_id == tournament_id
        )
    )
    return result.all()


@router.post(
    "/player-anomalies/feedback",
    response_model=AnomalyFeedbackRow,
    status_code=200,
)
async def submit_anomaly_feedback(
    body: AnomalyFeedbackBody,
    user: models.AuthUser = Depends(auth.require_permission("analytics", "update")),
    session: AsyncSession = Depends(db.get_async_session),
) -> AnomalyFeedbackRow:
    """Record a reviewer verdict on an anomaly (upsert per tournament/player/kind).

    These confirmed/dismissed labels are what
    :func:`src.services.ml.models.anomaly_tuning.tune_threshold` uses to set
    detector cut-offs by precision/recall.
    """
    existing = await session.scalar(
        sa.select(models.AnalyticsAnomalyFeedback).where(
            models.AnalyticsAnomalyFeedback.tournament_id == body.tournament_id,
            models.AnalyticsAnomalyFeedback.player_id == body.player_id,
            models.AnalyticsAnomalyFeedback.kind == body.kind,
        )
    )
    reviewer_id = int(user.id) if getattr(user, "id", None) is not None else None
    if existing is not None:
        existing.verdict = body.verdict
        existing.note = body.note
        existing.reviewer_user_id = reviewer_id
        row = existing
    else:
        row = models.AnalyticsAnomalyFeedback(
            tournament_id=body.tournament_id,
            player_id=body.player_id,
            kind=body.kind,
            verdict=body.verdict,
            reviewer_user_id=reviewer_id,
            note=body.note,
        )
        session.add(row)

    await session.flush()
    await session.refresh(row)
    # Build the response before commit so serialisation never triggers a lazy
    # (out-of-greenlet) load on an expired attribute — see the MissingGreenlet
    # lesson around server-side onupdate timestamps.
    response = AnomalyFeedbackRow(
        id=int(row.id),
        tournament_id=row.tournament_id,
        player_id=row.player_id,
        kind=row.kind,
        verdict=row.verdict,
        reviewer_user_id=row.reviewer_user_id,
        note=row.note,
    )
    await session.commit()
    return response


@router.get(
    "/explain/player/{player_id}/tournament/{tournament_id}",
    response_model=ExplanationRow,
)
async def explain_player(
    player_id: int,
    tournament_id: int,
    algorithm_id: int | None = Query(None),
    _user=Depends(auth.require_permission("analytics", "read")),
    session: AsyncSession = Depends(db.get_async_session),
) -> models.AnalyticsExplanation:
    query = sa.select(models.AnalyticsExplanation).where(
        models.AnalyticsExplanation.entity_id == player_id,
        models.AnalyticsExplanation.entity_kind == "player",
        models.AnalyticsExplanation.tournament_id == tournament_id,
    )
    if algorithm_id is not None:
        query = query.where(models.AnalyticsExplanation.algorithm_id == algorithm_id)
    query = query.order_by(models.AnalyticsExplanation.created_at.desc()).limit(1)

    result = await session.execute(query)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Explanation not found")
    return row


# ---------------------------------------------------------------------------
# v2 ML — admin endpoints (train / infer dispatchers + artifact registry)
# ---------------------------------------------------------------------------


@router.get("/artifacts", response_model=list[MLArtifactRow])
async def list_artifacts(
    model_kind: str | None = Query(None, description="Filter by 'performance'|'shift'|'standings'|'match_quality'"),
    active_only: bool = Query(False, description="Return only is_active=true rows"),
    _user=Depends(auth.require_permission("analytics", "read")),
    session: AsyncSession = Depends(db.get_async_session),
) -> typing.Sequence[models.MLModelArtifact]:
    """List trained ML model artifacts so the UI can show training history."""
    query = sa.select(models.MLModelArtifact)
    if model_kind is not None:
        query = query.where(models.MLModelArtifact.model_kind == model_kind)
    if active_only:
        query = query.where(models.MLModelArtifact.is_active.is_(True))
    query = query.order_by(models.MLModelArtifact.created_at.desc())
    result = await session.execute(query)
    return result.scalars().all()


@router.post(
    "/train",
    response_model=JobAcceptedResponse,
    status_code=202,
)
async def trigger_train(
    body: TrainRequestBody,
    _user=Depends(auth.require_permission("analytics", "update")),
) -> JobAcceptedResponse:
    """Enqueue a v2 ML training job.

    The job runs asynchronously in the analytics-worker FastStream consumer
    (``serve.consume_train_request``). Returns 202 immediately with the
    correlation id; clients poll ``GET /v2/artifacts`` to see new rows.
    """
    logger.info(
        "POST /v2/train received: cutoff=%s, model_kinds=%s, workspace_id=%s",
        body.cutoff_tournament_id,
        body.model_kinds,
        body.workspace_id,
    )
    if not config.settings.rabbitmq_url:
        raise HTTPException(
            status_code=503,
            detail="RabbitMQ is not configured; cannot dispatch training jobs.",
        )
    event = AnalyticsTrainRequest(
        cutoff_tournament_id=body.cutoff_tournament_id,
        model_kinds=body.model_kinds,
        workspace_id=body.workspace_id,
        workspace_ids=body.workspace_ids,
        source_service="analytics-service",
    )
    try:
        broker = await ensure_broker()
        await publish_message(broker, event.model_dump(), ANALYTICS_TRAIN_QUEUE)
    except Exception:
        logger.exception("Failed to publish train request to RabbitMQ")
        raise HTTPException(status_code=502, detail="Failed to dispatch training job to queue")
    logger.info("Train request published: correlation_id=%s", event.event_id)
    return JobAcceptedResponse(
        message="Training job dispatched.",
        job="train",
        correlation_id=event.event_id,
    )


@router.post(
    "/infer",
    response_model=JobAcceptedResponse,
    status_code=202,
)
async def trigger_infer(
    body: InferRequestBody,
    _user=Depends(auth.require_permission("analytics", "update")),
) -> JobAcceptedResponse:
    """Enqueue a v2 ML inference run for a single tournament."""
    logger.info(
        "POST /v2/infer received: tournament_id=%s, model_kinds=%s, workspace_id=%s",
        body.tournament_id,
        body.model_kinds,
        body.workspace_id,
    )
    if not config.settings.rabbitmq_url:
        raise HTTPException(
            status_code=503,
            detail="RabbitMQ is not configured; cannot dispatch inference jobs.",
        )
    event = AnalyticsInferRequest(
        tournament_id=body.tournament_id,
        model_kinds=body.model_kinds,
        workspace_id=body.workspace_id,
        source_service="analytics-service",
    )
    try:
        broker = await ensure_broker()
        await publish_message(broker, event.model_dump(), ANALYTICS_INFER_QUEUE)
    except Exception:
        logger.exception("Failed to publish infer request to RabbitMQ")
        raise HTTPException(status_code=502, detail="Failed to dispatch inference job to queue")
    logger.info("Infer request published: correlation_id=%s", event.event_id)
    return JobAcceptedResponse(
        message="Inference job dispatched.",
        job="infer",
        correlation_id=event.event_id,
    )


# ---------------------------------------------------------------------------
# Unified analytics job API (replaces Recalculate + Train ML + Run inference)
# ---------------------------------------------------------------------------


class AnalyticsJobRow(BaseModel):
    id: int
    workspace_id: int | None
    tournament_id: int
    requested_by_user_id: int | None
    kind: str
    status: str
    algorithms: list[str] | None
    training_workspace_ids: list[int] | None = None
    progress: dict
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime | None


class AnalyticsJobCreate(BaseModel):
    tournament_id: int
    kind: typing.Literal["compute", "train_ml"] = Field(
        default="compute",
        description=(
            "'compute' (organizer-allowed) runs v1 recalc + v2 inference. "
            "'train_ml' (superuser only) (re)trains v2 ML boosters."
        ),
    )
    algorithms: list[str] | None = Field(
        default=None,
        description=(
            "For kind=compute: list of v1 algorithm names to recalc (None = all). "
            "For kind=train_ml: list of model kinds ['performance','shift','standings']."
        ),
    )
    training_workspace_ids: list[int] | None = Field(
        default=None,
        description=(
            "Only for kind=train_ml. None trains on all workspaces; a non-empty "
            "list limits the sample to those workspace IDs."
        ),
    )


async def _require_actor(
    body: AnalyticsJobCreate,
    workspace_id: int | None,
    user: models.AuthUser,
) -> None:
    """Permission gate per ``kind``:

    - ``compute``  → ``analytics.update`` in the workspace
    - ``train_ml`` → superuser
    """
    if body.kind == JOB_KIND_TRAIN_ML:
        if not getattr(user, "is_superuser", False):
            raise HTTPException(
                status_code=403,
                detail="Training v2 ML models is restricted to superusers.",
            )
        return
    # compute: workspace-scoped permission
    if workspace_id is not None and not user.has_workspace_permission(
        workspace_id, "analytics", "update"
    ):
        raise HTTPException(
            status_code=403,
            detail="analytics.update permission required for this workspace.",
        )


@router.post(
    "/jobs",
    response_model=AnalyticsJobRow,
    status_code=202,
)
async def create_analytics_job(
    body: AnalyticsJobCreate,
    workspace_id: WorkspaceQuery = None,
    current_user: models.AuthUser = Depends(auth.get_current_active_user),
    session: AsyncSession = Depends(db.get_async_session),
) -> models.AnalyticsJob:
    """Enqueue a single analytics job — replaces Recalculate / Train / Infer.

    The DB enforces ``one running job per workspace`` via a partial unique
    index; concurrent requests get 409 Conflict immediately, no race.
    """
    await _require_actor(body, workspace_id, current_user)

    try:
        job = await create_job(
            session,
            workspace_id=workspace_id,
            tournament_id=body.tournament_id,
            kind=body.kind,
            algorithms=body.algorithms,
            training_workspace_ids=(
                body.training_workspace_ids if body.kind == JOB_KIND_TRAIN_ML else None
            ),
            requested_by_user_id=int(current_user.id),
        )
    except ActiveJobConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    if not config.settings.rabbitmq_url:
        await mark_job_failed(
            session,
            int(job.id),
            error="RabbitMQ is not configured; worker dispatch was not possible.",
        )
        raise HTTPException(
            status_code=503,
            detail="RabbitMQ is not configured; analytics job was marked failed.",
        )

    event = AnalyticsJobRequested(
        job_id=int(job.id),
        source_service="analytics-service",
    )
    try:
        broker = await ensure_broker()
        await publish_message(broker, event.model_dump(), ANALYTICS_JOB_QUEUE)
    except Exception as exc:
        logger.exception("Failed to publish analytics_job request")
        await session.rollback()
        await mark_job_failed(
            session,
            int(job.id),
            error=f"Failed to dispatch analytics job to queue: {exc}",
        )
        raise HTTPException(status_code=502, detail="Failed to dispatch job to queue")

    logger.info(
        "Analytics job created and dispatched: job_id=%d kind=%s tournament_id=%d workspace_id=%s",
        job.id,
        body.kind,
        body.tournament_id,
        workspace_id,
    )
    return job


@router.get(
    "/jobs/active",
    response_model=AnalyticsJobRow | None,
)
async def get_active_analytics_job(
    workspace_id: WorkspaceQuery = None,
    _user=Depends(auth.require_permission("analytics", "read")),
    session: AsyncSession = Depends(db.get_async_session),
) -> models.AnalyticsJob | None:
    """Return the currently-pending/running job for the workspace (or None)."""
    return await get_active_job(session, workspace_id)


@router.get(
    "/jobs",
    response_model=list[AnalyticsJobRow],
)
async def list_analytics_jobs(
    workspace_id: WorkspaceQuery = None,
    limit: int = Query(20, ge=1, le=100),
    active_only: bool = False,
    _user=Depends(auth.require_permission("analytics", "read")),
    session: AsyncSession = Depends(db.get_async_session),
) -> typing.Sequence[models.AnalyticsJob]:
    """List recent analytics jobs for the workspace."""
    return await list_jobs(
        session,
        workspace_id=workspace_id,
        limit=limit,
        active_only=active_only,
    )


@router.get("/jobs/{job_id}", response_model=AnalyticsJobRow)
async def get_analytics_job(
    job_id: int,
    _user=Depends(auth.require_permission("analytics", "read")),
    session: AsyncSession = Depends(db.get_async_session),
) -> models.AnalyticsJob:
    job = await get_job(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
