"""Light mutation RPC subscribers (``rpc.analytics.*``).

Bespoke, non-job mutations: manual shift override (``POST /analytics/shift``),
anomaly-feedback upsert (``POST /v2/player-anomalies/feedback``), and the
deprecated OpenSkill v1 endpoint (``POST /analytics/openskill`` → always 410).
Each mirrors its route exactly, including the underlying ``commit``. Heavier
compute lives behind job-control (``jobs_control.py``). Wired from
``serve_rpc.py``.

Auth: all require a global ``analytics.update`` permission (gateway
``AuthRequired`` + the same ``has_permission`` check the routes use).
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from fastapi import HTTPException
from faststream.rabbit.annotations import RabbitMessage

from src import models, schemas
from src.core import db
from src.routes.v2 import AnomalyFeedbackBody, AnomalyFeedbackRow
from src.services.analytics_read import flows as analytics_flows

from . import _common as c


async def _validate_tournament_workspace(
    session: Any, tournament_id: int, workspace_id: int | None
) -> None:
    """Local copy of routes/analytics._validate_tournament_workspace.

    Replicated (not imported) so the lightweight analytics-svc does not pull
    src.routes.analytics → src.services.analytics.flows (pandas/numpy/openskill).
    """
    if workspace_id is None:
        return
    tournament_workspace_id = await session.scalar(
        sa.select(models.Tournament.workspace_id).where(models.Tournament.id == tournament_id)
    )
    if tournament_workspace_id is None:
        raise HTTPException(status_code=404, detail="Tournament not found")
    if tournament_workspace_id != workspace_id:
        raise HTTPException(
            status_code=400, detail="workspace_id does not match tournament workspace"
        )


def register(broker: Any, logger: Any) -> None:
    sf = db.async_session_maker

    @broker.subscriber("rpc.analytics.shift")
    async def _shift(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            c.require_permission(c.actor(data), "analytics", "update")
            body = schemas.PlayerShiftUpdate.model_validate(c.payload(data))
            # change_shift commits internally (service.change_shift).
            return await analytics_flows.change_shift(session, body.player_id, body.shift)

        return await c.envelope(logger, "shift", op, session_factory=sf)

    @broker.subscriber("rpc.analytics.feedback_submit")
    async def _feedback_submit(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_permission(user, "analytics", "update")
            body = AnomalyFeedbackBody.model_validate(c.payload(data))
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
            # Build the response before commit so serialisation never triggers a
            # lazy (out-of-greenlet) load on an expired attribute.
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

        return await c.envelope(logger, "feedback_submit", op, session_factory=sf)

    @broker.subscriber("rpc.analytics.openskill")
    async def _openskill(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            c.require_permission(c.actor(data), "analytics", "update")
            tournament_id = c.require_query_int(data, "tournament_id")
            await _validate_tournament_workspace(
                session, tournament_id, c.q1(data, "workspace_id", int)
            )
            raise HTTPException(
                status_code=410,
                detail=(
                    "Open Skill v1 is no longer available. "
                    "Run the unified analytics job to compute OpenSkill + ML."
                ),
            )

        return await c.envelope(logger, "openskill", op, session_factory=sf)
