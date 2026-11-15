"""Job-control RPC subscribers (``rpc.analytics.*``).

Creates ``AnalyticsJob`` rows and enqueues to the heavy worker's job queues.
This svc only writes the row + its request event, through the outbox in one transaction -- the actual compute
runs in ``analytics-worker`` (``serve.py``). recalculate/points are thin 202
wrappers over a scoped ``kind=compute`` job (recalculate narrows it to the
ratings via ``algorithms``, but the compute job also runs ML inference like
every other compute job). Wired from ``serve_rpc.py``.

Auth: create_job / recalculate / points gate per
``_require_actor`` (compute → workspace-scoped ``analytics.update``; train_ml →
superuser). On top of the permission gate, every workspace-scoped GPU job
(``kind=compute``) also requires the workspace to be verified or
trusted — see ``shared.domain.workspace_tier``: self-service workspaces start
``unverified`` and must not burn GPU time (403 ``workspace_not_verified``).
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit.annotations import RabbitMessage

from shared import quota
from shared.core.errors import BaseAPIException as HTTPException
from shared.jobs import JobConflict
from src.core import db
from src.core.jobs import (
    JOB_KIND_COMPUTE,
    JOB_KIND_TRAIN_ML,
    create_analytics_job,
    require_analytics_owner,
    require_verified_workspace,
)
from src.schemas.ml import AnalyticsJobCreate, AnalyticsJobRow
from src.services.analytics.service import analytics_service

from . import _common as c

# Mirror src.services.analytics.flows.POINTS without importing that module
# (it pulls pandas/numpy/openskill into the lightweight svc).
_POINTS = "Points"


async def _require_actor(
    body: AnalyticsJobCreate,
    workspace_id: int | None,
    user: Any,
) -> None:
    """Permission gate per ``kind``:

    - ``compute``  → ``analytics.update`` in the workspace; the global grant
      when the job carries no ``workspace_id`` (never left ungated -- see
      ``require_verified_workspace``, which treats the unscoped case as
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

    async def _dispatch(
        session: Any,
        body: AnalyticsJobCreate,
        workspace_id: int | None,
        user: Any,
        *,
        operation: str | None = None,
    ) -> Any:
        """Create a job; its dispatch event commits with the row (``create_analytics_job``)."""
        await _require_actor(body, workspace_id, user)
        if body.kind == JOB_KIND_COMPUTE:
            await require_verified_workspace(session, workspace_id)
        # Every admission names a tournament that must lie in the requested workspace; a named model or a training
        # also needs a discipline with analytics models. Without ``algorithms`` a compute job is automatic
        # enrichment, which the worker turns into an empty summary for a discipline with no analytics module.
        await require_analytics_owner(
            session,
            body.tournament_id,
            scope=body.training_workspace_ids
            if body.kind == JOB_KIND_TRAIN_ML
            else ([workspace_id] if workspace_id is not None else None),
            models_required=body.kind == JOB_KIND_TRAIN_ML or bool(body.algorithms),
        )
        # Metered only for the callers that have their own quota operation slug;
        # create_job/points enqueue the same compute work but are not metered
        # subjects, so charging here unconditionally would bill a slug they do not
        # own. After both gates: an unauthorized or unverified caller must not
        # spend quota on a job that never runs.
        if operation is not None:
            await quota.charge(user, operation, workspace_id=workspace_id)
        try:
            return await create_analytics_job(
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
            except KeyError, TypeError, ValueError:
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
