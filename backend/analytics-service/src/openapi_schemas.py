"""OpenAPI request/response model map for analytics-service RPC subjects.

Schemas-only module consumed by the export script — see ``shared.rpc.openapi``.
No generic-CRUD engine here; every subject is a bespoke @broker.subscriber.
Models mirror the v1 flow return annotations and the v2 handlers' direct
model construction. ``openskill`` (410 gone) is intentionally omitted.
"""

from __future__ import annotations

from shared.core.pagination import Paginated
from shared.rpc.openapi import Op

from src import schemas
from src.schemas.analytics_read import BalanceQualityRead, PlayerShiftUpdate
from src.schemas.v2 import (
    AnalyticsJobCreate,
    AnalyticsJobRow,
    AnomalyFeedbackBody,
    AnomalyFeedbackRow,
    ExplanationRow,
    InferRequestBody,
    JobAcceptedResponse,
    MatchQualityRow,
    MLArtifactRow,
    PerformanceRow,
    PlayerAnomalyRow,
    StandingsRow,
    TrainRequestBody,
)

OPERATIONS: dict[str, Op] = {
    # ── v1 reads (public) ──────────────────────────────────────────────────
    "rpc.analytics.list_algorithms": Op(response=Paginated[schemas.AnalyticsAlgorithmRead]),
    "rpc.analytics.get_algorithm": Op(response=schemas.AnalyticsAlgorithmRead),
    "rpc.analytics.get_analytics": Op(response=schemas.TournamentAnalytics),
    "rpc.analytics.get_streaks": Op(response=schemas.PlayerStreak, response_array=True),
    "rpc.analytics.balance_quality": Op(response=BalanceQualityRead),
    # ── v2 ML reads (require analytics.read) ───────────────────────────────
    "rpc.analytics.v2_performance": Op(response=PerformanceRow, response_array=True),
    "rpc.analytics.v2_standings": Op(response=StandingsRow, response_array=True),
    "rpc.analytics.v2_match_quality": Op(response=MatchQualityRow, response_array=True),
    "rpc.analytics.v2_player_anomalies": Op(response=PlayerAnomalyRow, response_array=True),
    "rpc.analytics.v2_feedback_list": Op(response=AnomalyFeedbackRow, response_array=True),
    "rpc.analytics.v2_explain": Op(response=ExplanationRow),
    "rpc.analytics.v2_artifacts": Op(response=MLArtifactRow, response_array=True),
    # ── job reads ──────────────────────────────────────────────────────────
    "rpc.analytics.jobs_active": Op(response=AnalyticsJobRow),
    "rpc.analytics.jobs_list": Op(response=AnalyticsJobRow, response_array=True),
    "rpc.analytics.jobs_get": Op(response=AnalyticsJobRow),
    # ── mutations / job-control ────────────────────────────────────────────
    "rpc.analytics.shift": Op(request=PlayerShiftUpdate, response=schemas.PlayerAnalytics),
    "rpc.analytics.feedback_submit": Op(request=AnomalyFeedbackBody, response=AnomalyFeedbackRow),
    "rpc.analytics.create_job": Op(request=AnalyticsJobCreate, response=AnalyticsJobRow),
    "rpc.analytics.recalculate": Op(response=AnalyticsJobRow),
    "rpc.analytics.points": Op(response=AnalyticsJobRow),
    "rpc.analytics.train": Op(request=TrainRequestBody, response=JobAcceptedResponse),
    "rpc.analytics.infer": Op(request=InferRequestBody, response=JobAcceptedResponse),
}
