"""Pydantic response/request schemas for the v2 ML analytics surface.

These models were extracted verbatim from the decommissioned HTTP layer
(``src/routes/v2.py``) so the typed-RPC handlers (``src/rpc/*``) keep a single
source of truth for the wire contract. Field names, order, defaults, aliases
and validators are preserved exactly — the RPC response bytes must stay
identical. This module is deliberately free of any web-framework dependency.
"""

from __future__ import annotations

import typing
from datetime import datetime

from pydantic import BaseModel, Field

__all__ = (
    "PerformanceRow",
    "StandingsRow",
    "MatchQualityRow",
    "ExplanationRow",
    "MLArtifactRow",
    "TrainRequestBody",
    "InferRequestBody",
    "JobAcceptedResponse",
    "PlayerAnomalyRow",
    "AnomalyFeedbackRow",
    "AnomalyFeedbackBody",
    "AnalyticsJobRow",
    "AnalyticsJobCreate",
)


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
