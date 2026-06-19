"""Public + authenticated read RPC subscribers (``rpc.analytics.*``).

Each handler mirrors a read route in ``src/routes/analytics_read.py`` or
``src/routes/v2.py`` exactly: it calls the same flow/query and coerces the
result through the same response model (default ``exclude_none=False`` — none
of the analytics read routes set ``response_model_exclude_none``). Response
schemas are imported from the route modules so the contract stays single-source.

Auth: the v1 reads are public (gateway ``AuthNone``); the v2 + job reads require
a global ``analytics.read`` permission (gateway ``AuthRequired`` + the same
``has_permission`` check the routes use).
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from fastapi import HTTPException
from faststream.rabbit.annotations import RabbitMessage
from sqlalchemy.orm import selectinload

from src import models
from src.core import db, pagination
from src.routes.analytics_read import BalancePlayerSnapshotRead, BalanceQualityRead
from src.routes.v2 import (
    AnalyticsJobRow,
    AnomalyFeedbackRow,
    ExplanationRow,
    MatchQualityRow,
    MLArtifactRow,
    PerformanceRow,
    PlayerAnomalyRow,
    StandingsRow,
)
from src.services.analytics_read import flows as analytics_flows
from src.services.jobs import get_active_job, get_job, list_jobs

from . import _common as c


def _req_int(data: dict[str, Any], key: str) -> int:
    value = c.q1(data, key, int)
    if value is None:
        raise HTTPException(status_code=422, detail=f"{key} is required")
    return value


def register(broker: Any, logger: Any) -> None:
    sf = db.async_session_maker

    # ── v1 reads (public) ──────────────────────────────────────────────

    @broker.subscriber("rpc.analytics.get_algorithm")
    async def _get_algorithm(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            return await analytics_flows.get_algorithm(session, c.require_id(data))

        return await c.envelope(logger, "get_algorithm", op, session_factory=sf)

    @broker.subscriber("rpc.analytics.list_algorithms")
    async def _list_algorithms(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            params = pagination.PaginationParams.from_query_params(
                pagination.PaginationQueryParams(
                    page=c.q1(data, "page", int, 1),
                    per_page=c.q1(data, "per_page", int, 10),
                )
            )
            return await analytics_flows.get_algorithms(
                session, params, tournament_id=c.q1(data, "tournament_id", int)
            )

        return await c.envelope(logger, "list_algorithms", op, session_factory=sf)

    @broker.subscriber("rpc.analytics.get_analytics")
    async def _get_analytics(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            return await analytics_flows.get_analytics(
                session,
                _req_int(data, "tournament_id"),
                _req_int(data, "algorithm"),
                workspace_id=c.q1(data, "workspace_id", int),
            )

        return await c.envelope(logger, "get_analytics", op, session_factory=sf)

    @broker.subscriber("rpc.analytics.get_streaks")
    async def _get_streaks(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            return await analytics_flows.get_streaks(session, _req_int(data, "tournament_id"))

        return await c.envelope(logger, "get_streaks", op, session_factory=sf)

    @broker.subscriber("rpc.analytics.balance_quality")
    async def _balance_quality(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            tournament_id = _req_int(data, "tournament_id")
            result = await session.execute(
                sa.select(models.AnalyticsBalanceSnapshot)
                .where(models.AnalyticsBalanceSnapshot.tournament_id == tournament_id)
                .options(selectinload(models.AnalyticsBalanceSnapshot.players))
            )
            snapshot = result.scalar_one_or_none()
            if snapshot is None:
                return None
            return BalanceQualityRead(
                tournament_id=snapshot.tournament_id,
                algorithm=snapshot.algorithm,
                division_scope=snapshot.division_scope,
                team_count=snapshot.team_count,
                player_count=snapshot.player_count,
                avg_sr_overall=snapshot.avg_sr_overall,
                sr_std_dev=snapshot.sr_std_dev,
                sr_range=snapshot.sr_range,
                total_discomfort=snapshot.total_discomfort,
                off_role_count=snapshot.off_role_count,
                objective_score=snapshot.objective_score,
                players=[
                    BalancePlayerSnapshotRead(
                        user_id=p.user_id,
                        team_id=p.team_id,
                        assigned_role=p.assigned_role,
                        preferred_role=p.preferred_role,
                        assigned_rank=p.assigned_rank,
                        discomfort=p.discomfort,
                        division_number=p.division_number,
                        is_captain=p.is_captain,
                        was_off_role=p.was_off_role,
                    )
                    for p in snapshot.players
                ],
            )

        return await c.envelope(logger, "balance_quality", op, session_factory=sf)

    # ── v2 ML reads (require analytics.read) ───────────────────────────

    @broker.subscriber("rpc.analytics.v2_performance")
    async def _v2_performance(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            c.require_permission(c.actor(data), "analytics", "read")
            tournament_id = _req_int(data, "tournament_id")
            algorithm_id = c.q1(data, "algorithm_id", int)
            query = sa.select(models.AnalyticsPerformance).where(
                models.AnalyticsPerformance.tournament_id == tournament_id
            )
            if algorithm_id is not None:
                query = query.where(models.AnalyticsPerformance.algorithm_id == algorithm_id)
            rows = (await session.execute(query)).scalars().all()
            return [PerformanceRow.model_validate(r, from_attributes=True) for r in rows]

        return await c.envelope(logger, "v2_performance", op, session_factory=sf)

    @broker.subscriber("rpc.analytics.v2_standings")
    async def _v2_standings(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            c.require_permission(c.actor(data), "analytics", "read")
            tournament_id = _req_int(data, "tournament_id")
            algorithm_id = c.q1(data, "algorithm_id", int)
            query = sa.select(models.AnalyticsStandingsDistribution).where(
                models.AnalyticsStandingsDistribution.tournament_id == tournament_id
            )
            if algorithm_id is not None:
                query = query.where(
                    models.AnalyticsStandingsDistribution.algorithm_id == algorithm_id
                )
            rows = (await session.execute(query)).scalars().all()
            return [StandingsRow.model_validate(r, from_attributes=True) for r in rows]

        return await c.envelope(logger, "v2_standings", op, session_factory=sf)

    @broker.subscriber("rpc.analytics.v2_match_quality")
    async def _v2_match_quality(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            c.require_permission(c.actor(data), "analytics", "read")
            tournament_id = _req_int(data, "tournament_id")
            algorithm_id = c.q1(data, "algorithm_id", int)
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
            rows = (await session.execute(query)).scalars().all()
            return [MatchQualityRow.model_validate(r, from_attributes=True) for r in rows]

        return await c.envelope(logger, "v2_match_quality", op, session_factory=sf)

    @broker.subscriber("rpc.analytics.v2_player_anomalies")
    async def _v2_player_anomalies(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            c.require_permission(c.actor(data), "analytics", "read")
            tournament_id = _req_int(data, "tournament_id")
            player_id = c.q1(data, "player_id", int)
            kind = c.q1(data, "kind", str)
            query = sa.select(models.AnalyticsPlayerAnomaly).where(
                models.AnalyticsPlayerAnomaly.tournament_id == tournament_id
            )
            if player_id is not None:
                query = query.where(models.AnalyticsPlayerAnomaly.player_id == player_id)
            if kind is not None:
                query = query.where(models.AnalyticsPlayerAnomaly.kind == kind)
            rows = (await session.execute(query)).scalars().all()
            return [PlayerAnomalyRow.model_validate(r, from_attributes=True) for r in rows]

        return await c.envelope(logger, "v2_player_anomalies", op, session_factory=sf)

    @broker.subscriber("rpc.analytics.v2_feedback_list")
    async def _v2_feedback_list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            c.require_permission(c.actor(data), "analytics", "read")
            tournament_id = _req_int(data, "tournament_id")
            rows = (
                await session.scalars(
                    sa.select(models.AnalyticsAnomalyFeedback).where(
                        models.AnalyticsAnomalyFeedback.tournament_id == tournament_id
                    )
                )
            ).all()
            return [AnomalyFeedbackRow.model_validate(r, from_attributes=True) for r in rows]

        return await c.envelope(logger, "v2_feedback_list", op, session_factory=sf)

    @broker.subscriber("rpc.analytics.v2_explain")
    async def _v2_explain(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            c.require_permission(c.actor(data), "analytics", "read")
            player_id = int(data["player_id"])
            tournament_id = int(data["tournament_id"])
            algorithm_id = c.q1(data, "algorithm_id", int)
            query = sa.select(models.AnalyticsExplanation).where(
                models.AnalyticsExplanation.entity_id == player_id,
                models.AnalyticsExplanation.entity_kind == "player",
                models.AnalyticsExplanation.tournament_id == tournament_id,
            )
            if algorithm_id is not None:
                query = query.where(models.AnalyticsExplanation.algorithm_id == algorithm_id)
            query = query.order_by(models.AnalyticsExplanation.created_at.desc()).limit(1)
            row = (await session.execute(query)).scalar_one_or_none()
            if row is None:
                raise HTTPException(status_code=404, detail="Explanation not found")
            return ExplanationRow.model_validate(row, from_attributes=True)

        return await c.envelope(logger, "v2_explain", op, session_factory=sf)

    @broker.subscriber("rpc.analytics.v2_artifacts")
    async def _v2_artifacts(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            c.require_permission(c.actor(data), "analytics", "read")
            model_kind = c.q1(data, "model_kind", str)
            active_only = c.q1(data, "active_only", c.qbool, False)
            query = sa.select(models.MLModelArtifact)
            if model_kind is not None:
                query = query.where(models.MLModelArtifact.model_kind == model_kind)
            if active_only:
                query = query.where(models.MLModelArtifact.is_active.is_(True))
            query = query.order_by(models.MLModelArtifact.created_at.desc())
            rows = (await session.execute(query)).scalars().all()
            return [MLArtifactRow.model_validate(r, from_attributes=True) for r in rows]

        return await c.envelope(logger, "v2_artifacts", op, session_factory=sf)

    # ── job reads (require analytics.read) ─────────────────────────────

    @broker.subscriber("rpc.analytics.jobs_active")
    async def _jobs_active(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            c.require_permission(c.actor(data), "analytics", "read")
            job = await get_active_job(session, c.q1(data, "workspace_id", int))
            return AnalyticsJobRow.model_validate(job, from_attributes=True) if job is not None else None

        return await c.envelope(logger, "jobs_active", op, session_factory=sf)

    @broker.subscriber("rpc.analytics.jobs_list")
    async def _jobs_list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            c.require_permission(c.actor(data), "analytics", "read")
            jobs = await list_jobs(
                session,
                workspace_id=c.q1(data, "workspace_id", int),
                limit=c.q1(data, "limit", int, 20),
                active_only=c.q1(data, "active_only", c.qbool, False),
            )
            return [AnalyticsJobRow.model_validate(j, from_attributes=True) for j in jobs]

        return await c.envelope(logger, "jobs_list", op, session_factory=sf)

    @broker.subscriber("rpc.analytics.jobs_get")
    async def _jobs_get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            c.require_permission(c.actor(data), "analytics", "read")
            job = await get_job(session, c.require_id(data))
            if job is None:
                raise HTTPException(status_code=404, detail="Job not found")
            return AnalyticsJobRow.model_validate(job, from_attributes=True)

        return await c.envelope(logger, "jobs_get", op, session_factory=sf)
