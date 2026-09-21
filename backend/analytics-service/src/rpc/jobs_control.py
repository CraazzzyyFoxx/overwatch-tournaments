"""Job-control RPC subscribers (``rpc.analytics.*``).

Creates ``AnalyticsJob`` rows and enqueues to the heavy worker's job queues.
This svc only writes the row + publishes the request event — the actual compute
runs in ``analytics-worker`` (``serve.py``). recalculate/points are thin 202
wrappers over a scoped ``kind=compute`` job (the legacy synchronous 200
behaviour is intentionally replaced by the unified async job; recalculate's
old ratings-only scope is preserved via ``algorithms``, but the compute job also
runs ML inference like every other compute job). Wired from ``serve_rpc.py``.

Auth mirrors the routes: create_job / recalculate / points gate per
``_require_actor`` (compute → workspace-scoped ``analytics.update``; train_ml →
superuser); the deprecated train/infer use a global ``analytics.update``.
On top of the permission gate, every workspace-scoped GPU job (``kind=compute``
and the deprecated train/infer) also requires the workspace to be verified or
trusted — see ``shared.domain.workspace_tier``: self-service workspaces start
``unverified`` and must not burn GPU time (403 ``workspace_not_verified``).
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit.annotations import RabbitMessage

from shared import quota
from shared.core.errors import BaseAPIException as HTTPException
from shared.jobs import JobConflict
from shared.messaging.config import (
    ANALYTICS_INFER_QUEUE,
    ANALYTICS_JOB_QUEUE,
    ANALYTICS_TRAIN_QUEUE,
)
from shared.observability import publish_message
from shared.repository import WorkspaceRepository
from shared.schemas.events import (
    AnalyticsInferRequest,
    AnalyticsJobRequested,
    AnalyticsTrainRequest,
)
from shared.domain.workspace_tier import is_verified_or_trusted
from src.core import config, db
from src.core.jobs import JOB_KIND_COMPUTE, JOB_KIND_TRAIN_ML, create_analytics_job, job_runtime
from src.schemas.ml import (
    AnalyticsJobCreate,
    AnalyticsJobRow,
    InferRequestBody,
    JobAcceptedResponse,
    TrainRequestBody,
)
from src.services.analytics.service import analytics_service

from . import _common as c

# Mirror src.services.analytics.flows.POINTS without importing that module
# (it pulls pandas/numpy/openskill into the lightweight svc).
_POINTS = "Points"

_workspaces = WorkspaceRepository()


async def _require_verified_workspace(session: Any, workspace_id: int | None) -> None:
    """GPU gate: a workspace-scoped compute/train/infer job only runs for a
    verified or trusted workspace. Global (``workspace_id is None``) jobs are
    superuser/global-permission territory and stay ungated."""
    if workspace_id is None:
        return
    workspace = await _workspaces.get(session, workspace_id)
    if workspace is None or not is_verified_or_trusted(workspace):
        raise HTTPException(status_code=403, detail="workspace_not_verified")


async def _require_actor(
    body: AnalyticsJobCreate,
    workspace_id: int | None,
    user: Any,
) -> None:
    """Permission gate per ``kind`` (extracted from the decommissioned
    ``src/routes/v2.py``):

    - ``compute``  → ``analytics.update`` in the workspace; the global grant
      when the job carries no ``workspace_id`` (never left ungated -- see
      ``_require_verified_workspace``, which treats the unscoped case as
      global-permission territory too)
    - ``train_ml`` → superuser
    """
    if body.kind == JOB_KIND_TRAIN_ML:
        if not getattr(user, "is_superuser", False):
            raise HTTPException(
                status_code=403,
                detail="Training ML models is restricted to superusers.",
            )
        return
    if workspace_id is not None:
        if not user.has_workspace_permission(workspace_id, "analytics", "update"):
            raise HTTPException(
                status_code=403,
                detail="analytics.update permission required for this workspace.",
            )
    elif not user.has_permission("analytics", "update"):
        raise HTTPException(
            status_code=403,
            detail="analytics.update permission required.",
        )


def register(broker: Any, logger: Any) -> None:
    sf = db.async_session_maker

    async def _publish_event(payload: dict[str, Any], queue: str, *, unavailable: str, failed: str) -> None:
        if not config.settings.rabbitmq_url:
            raise HTTPException(status_code=503, detail=unavailable)
        try:
            await publish_message(broker, payload, queue)
        except Exception:
            logger.exception("Failed to publish analytics job to RabbitMQ")
            raise HTTPException(status_code=502, detail=failed)

    async def _dispatch(
        session: Any,
        body: AnalyticsJobCreate,
        workspace_id: int | None,
        user: Any,
        *,
        operation: str | None = None,
    ) -> Any:
        """Create + enqueue a job, mirroring routes.v2.create_analytics_job."""
        await _require_actor(body, workspace_id, user)
        if body.kind == JOB_KIND_COMPUTE:
            await _require_verified_workspace(session, workspace_id)
        # Metered only for the callers that have their own quota operation slug;
        # create_job/points enqueue the same compute work but are not metered
        # subjects, so charging here unconditionally would bill a slug they do not
        # own. After both gates: an unauthorized or unverified caller must not
        # spend quota on a job that never runs.
        if operation is not None:
            await quota.charge(user, operation, workspace_id=workspace_id)
        try:
            job = await create_analytics_job(
                session,
                workspace_id=workspace_id,
                tournament_id=body.tournament_id,
                kind=body.kind,
                algorithms=body.algorithms,
                training_workspace_ids=(body.training_workspace_ids if body.kind == JOB_KIND_TRAIN_ML else None),
                requested_by_user_id=int(user.id),
            )
        except JobConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc))

        if not config.settings.rabbitmq_url:
            await job_runtime.mark_failed(
                session,
                int(job.id),
                error="RabbitMQ is not configured; worker dispatch was not possible.",
            )
            await session.commit()
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
            await job_runtime.mark_failed(
                session,
                int(job.id),
                error=f"Failed to dispatch analytics job to queue: {exc}",
            )
            await session.commit()
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
                algorithm_names = await analytics_service.list_algorithm_names_by_ids(
                    session, [int(i) for i in algorithm_ids]
                )
            body = AnalyticsJobCreate(
                tournament_id=tournament_id,
                kind=JOB_KIND_COMPUTE,
                algorithms=algorithm_names,
            )
            job = await _dispatch(
                session,
                body,
                c.q1(data, "workspace_id", int),
                user,
                operation="analytics.recalculate",
            )
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
            user = c.actor(data)
            c.require_permission(user, "analytics", "update")
            body = TrainRequestBody.model_validate(c.payload(data))
            await _require_verified_workspace(session, body.workspace_id)
            # The costliest operation on the platform: a full model retrain over
            # every workspace in scope. Charged rather than leased because this
            # handler only publishes to ANALYTICS_TRAIN_QUEUE and returns -- the
            # compute lives in another process (``serve.py``), which is where a
            # lease would have to be released, so a lease taken here would cover
            # the publish and nothing else.
            await quota.charge(user, "analytics.train", workspace_id=body.workspace_id)
            event = AnalyticsTrainRequest(
                cutoff_tournament_id=body.cutoff_tournament_id,
                model_kinds=body.model_kinds,
                workspace_id=body.workspace_id,
                workspace_ids=body.workspace_ids,
                source_service="analytics-svc",
            )
            await _publish_event(
                event.model_dump(),
                ANALYTICS_TRAIN_QUEUE,
                unavailable="RabbitMQ is not configured; cannot dispatch training jobs.",
                failed="Failed to dispatch training job to queue",
            )
            return JobAcceptedResponse(message="Training job dispatched.", job="train", correlation_id=event.event_id)

        return await c.envelope(logger, "train", op, session_factory=sf)

    @broker.subscriber("rpc.analytics.infer")
    async def _infer(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_permission(user, "analytics", "update")
            body = InferRequestBody.model_validate(c.payload(data))
            await _require_verified_workspace(session, body.workspace_id)
            await quota.charge(user, "analytics.infer", workspace_id=body.workspace_id)
            event = AnalyticsInferRequest(
                tournament_id=body.tournament_id,
                model_kinds=body.model_kinds,
                workspace_id=body.workspace_id,
                source_service="analytics-svc",
            )
            await _publish_event(
                event.model_dump(),
                ANALYTICS_INFER_QUEUE,
                unavailable="RabbitMQ is not configured; cannot dispatch inference jobs.",
                failed="Failed to dispatch inference job to queue",
            )
            return JobAcceptedResponse(message="Inference job dispatched.", job="infer", correlation_id=event.event_id)

        return await c.envelope(logger, "infer", op, session_factory=sf)
