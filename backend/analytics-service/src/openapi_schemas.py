"""OpenAPI request/response model map for analytics-service RPC subjects.

Schemas-only module consumed by the export script — see ``shared.rpc.openapi``.
No generic-CRUD engine here; every subject is a bespoke @broker.subscriber.
Models mirror the rating-flow return annotations and the ML handlers' direct
model construction.
"""

from __future__ import annotations

from shared.core.pagination import Paginated
from shared.rpc.openapi import Op, QueryParam
from src import schemas
from src.schemas.analytics_read import PlayerShiftUpdate
from src.schemas.ml import (
    AnalyticsJobCreate,
    AnalyticsJobRow,
    AnomalyFeedbackBody,
    AnomalyFeedbackRow,
    ExplanationRow,
    MatchQualityRow,
    MLArtifactRow,
    PerformanceRow,
    PlayerAnomalyRow,
    StandingsRow,
)

# Ad-hoc query params (analytics handlers read these via c.q1; no query model).
_TID = QueryParam("tournament_id", "integer")
_WS = QueryParam("workspace_id", "integer")
_ALG = QueryParam("algorithm_id", "integer")

OPERATIONS: dict[str, Op] = {
    # ── rating reads (public) ──────────────────────────────────────────────
    "rpc.analytics.list_algorithms": Op(
        response=Paginated[schemas.AnalyticsAlgorithmRead],
        query_params=(QueryParam("page", "integer"), QueryParam("per_page", "integer"), _TID),
    ),
    "rpc.analytics.get_algorithm": Op(response=schemas.AnalyticsAlgorithmRead),
    "rpc.analytics.get_analytics": Op(
        response=schemas.TournamentAnalytics,
        query_params=(
            QueryParam("tournament_id", "integer", required=True),
            QueryParam("algorithm", "integer", required=True),
            _WS,
        ),
    ),
    "rpc.analytics.get_streaks": Op(
        response=schemas.PlayerStreak,
        response_array=True,
        query_params=(QueryParam("tournament_id", "integer", required=True),),
    ),
    # ── ML reads (require analytics.read) ──────────────────────────────────
    "rpc.analytics.performance": Op(
        response=PerformanceRow,
        response_array=True,
        query_params=(QueryParam("tournament_id", "integer", required=True), _ALG),
    ),
    "rpc.analytics.standings": Op(
        response=StandingsRow,
        response_array=True,
        query_params=(QueryParam("tournament_id", "integer", required=True), _ALG),
    ),
    "rpc.analytics.match_quality": Op(
        response=MatchQualityRow,
        response_array=True,
        query_params=(QueryParam("tournament_id", "integer", required=True), _ALG),
    ),
    "rpc.analytics.player_anomalies": Op(
        response=PlayerAnomalyRow,
        response_array=True,
        query_params=(
            QueryParam("tournament_id", "integer", required=True),
            QueryParam("player_id", "integer"),
            QueryParam("kind"),
        ),
    ),
    "rpc.analytics.feedback_list": Op(
        response=AnomalyFeedbackRow,
        response_array=True,
        query_params=(QueryParam("tournament_id", "integer", required=True),),
    ),
    "rpc.analytics.explain": Op(response=ExplanationRow, query_params=(_ALG,)),
    "rpc.analytics.artifacts": Op(
        response=MLArtifactRow,
        response_array=True,
        query_params=(QueryParam("model_kind"), QueryParam("active_only", "boolean")),
    ),
    # ── job reads ──────────────────────────────────────────────────────────
    "rpc.analytics.jobs_active": Op(response=AnalyticsJobRow, query_params=(_WS,)),
    "rpc.analytics.jobs_list": Op(
        response=AnalyticsJobRow,
        response_array=True,
        query_params=(_WS, QueryParam("limit", "integer"), QueryParam("active_only", "boolean")),
    ),
    "rpc.analytics.jobs_get": Op(response=AnalyticsJobRow),
    # ── mutations / job-control ────────────────────────────────────────────
    "rpc.analytics.shift": Op(request=PlayerShiftUpdate, response=PlayerShiftUpdate),
    "rpc.analytics.feedback_submit": Op(request=AnomalyFeedbackBody, response=AnomalyFeedbackRow),
    "rpc.analytics.create_job": Op(request=AnalyticsJobCreate, response=AnalyticsJobRow, query_params=(_WS,)),
    "rpc.analytics.recalculate": Op(response=AnalyticsJobRow, query_params=(_WS,)),
    "rpc.analytics.points": Op(
        response=AnalyticsJobRow, query_params=(QueryParam("tournament_id", "integer", required=True), _WS)
    ),
}
