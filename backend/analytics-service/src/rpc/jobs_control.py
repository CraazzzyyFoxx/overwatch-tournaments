"""Job-control RPC subscribers (``rpc.analytics.*``).

Creates ``AnalyticsJob`` rows and enqueues to the heavy worker's job queues.
This svc only writes the row + publishes the request event — the actual compute
runs in ``analytics-worker`` (``serve.py``). recalculate/points are thin 202
wrappers over a scoped ``kind=compute`` job (the legacy synchronous 200
behaviour is intentionally replaced by the unified async job; recalculate's
old v1-only scope is preserved via ``algorithms``, but the compute job also
runs v2 inference like every other compute job). Wired from ``serve_rpc.py``.

Auth mirrors the routes: create_job / recalculate / points gate per
``_require_actor`` (compute → workspace-scoped ``analytics.update``; train_ml →
superuser); the deprecated train/infer use a global ``analytics.update``.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from fastapi import HTTPException
from faststream.rabbit.annotations import RabbitMessage
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

from src import models
from src.core import config, db
from src.routes.v2 import (
    AnalyticsJobCreate,
    AnalyticsJobRow,
    InferRequestBody,
    JobAcceptedResponse,
    TrainRequestBody,
    _require_actor,
)
from src.services.jobs import (
    JOB_KIND_COMPUTE,
    JOB_KIND_TRAIN_ML,
    ActiveJobConflict,
    create_job,
    mark_job_failed,
)

from . import _common as c

# Mirror src.services.analytics.flows.POINTS without importing that module
# (it pulls pandas/numpy/openskill into the lightweight svc).
_POINTS = "Points"


def register(broker: Any, logger: Any) -> None:
    sf = db.async_session_maker

    async def _dispatch(
        session: Any, body: AnalyticsJobCreate, workspace_id: int | None, user: Any
    ) -> models.AnalyticsJob:
        """Create + enqueue a job, mirroring routes.v2.create_analytics_job."""
        await _require_actor(body, workspace_id, user)
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
                requested_by_user_id=int(user.id),
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

        event = AnalyticsJobRequested(job_id=int(job.id), source_service="analytics-svc")
        try:
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
        return job

    @broker.subscriber("rpc.analytics.create_job")
    async def _create_job(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_active(user)
            body = AnalyticsJobCreate.model_validate(c.payload(data))
            job = await _dispatch(session, body, c.q1(data, "workspace_id", int), user)
            return AnalyticsJobRow.model_validate(job, from_attributes=True)

        return await c.envelope(logger, "create_job", op, session_factory=sf)

    @broker.subscriber("rpc.analytics.recalculate")
    async def _recalculate(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_active(user)
            payload = c.payload(data)
            try:
                tournament_id = int(payload["tournament_id"])
            except (KeyError, TypeError, ValueError):
                raise HTTPException(status_code=422, detail="tournament_id is required")
            algorithm_ids = payload.get("algorithm_ids") or []
            algorithm_names: list[str] | None = None
            if algorithm_ids:
                rows = await session.scalars(
                    sa.select(models.AnalyticsAlgorithm.name).where(
                        models.AnalyticsAlgorithm.id.in_([int(i) for i in algorithm_ids])
                    )
                )
                algorithm_names = list(rows.all())
            body = AnalyticsJobCreate(
                tournament_id=tournament_id,
                kind=JOB_KIND_COMPUTE,
                algorithms=algorithm_names,
            )
            job = await _dispatch(session, body, c.q1(data, "workspace_id", int), user)
            return AnalyticsJobRow.model_validate(job, from_attributes=True)

        return await c.envelope(logger, "recalculate", op, session_factory=sf)

    @broker.subscriber("rpc.analytics.points")
    async def _points(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_active(user)
            tournament_id = c.require_query_int(data, "tournament_id")
            body = AnalyticsJobCreate(
                tournament_id=tournament_id,
                kind=JOB_KIND_COMPUTE,
                algorithms=[_POINTS],
            )
            job = await _dispatch(session, body, c.q1(data, "workspace_id", int), user)
            return AnalyticsJobRow.model_validate(job, from_attributes=True)

        return await c.envelope(logger, "points", op, session_factory=sf)

    @broker.subscriber("rpc.analytics.train")
    async def _train(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            c.require_permission(c.actor(data), "analytics", "update")
            body = TrainRequestBody.model_validate(c.payload(data))
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
                source_service="analytics-svc",
            )
            try:
                await publish_message(broker, event.model_dump(), ANALYTICS_TRAIN_QUEUE)
            except Exception:
                logger.exception("Failed to publish train request to RabbitMQ")
                raise HTTPException(
                    status_code=502, detail="Failed to dispatch training job to queue"
                )
            return JobAcceptedResponse(
                message="Training job dispatched.", job="train", correlation_id=event.event_id
            )

        return await c.envelope(logger, "train", op, session_factory=sf)

    @broker.subscriber("rpc.analytics.infer")
    async def _infer(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            c.require_permission(c.actor(data), "analytics", "update")
            body = InferRequestBody.model_validate(c.payload(data))
            if not config.settings.rabbitmq_url:
                raise HTTPException(
                    status_code=503,
                    detail="RabbitMQ is not configured; cannot dispatch inference jobs.",
                )
            event = AnalyticsInferRequest(
                tournament_id=body.tournament_id,
                model_kinds=body.model_kinds,
                workspace_id=body.workspace_id,
                source_service="analytics-svc",
            )
            try:
                await publish_message(broker, event.model_dump(), ANALYTICS_INFER_QUEUE)
            except Exception:
                logger.exception("Failed to publish infer request to RabbitMQ")
                raise HTTPException(
                    status_code=502, detail="Failed to dispatch inference job to queue"
                )
            return JobAcceptedResponse(
                message="Inference job dispatched.", job="infer", correlation_id=event.event_id
            )

        return await c.envelope(logger, "infer", op, session_factory=sf)
