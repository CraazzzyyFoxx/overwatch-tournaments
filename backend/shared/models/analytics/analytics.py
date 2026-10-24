from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db
from shared.models.catalog import CatalogRole
from shared.models.encounter.encounter import Encounter
from shared.models.tournament.team import Player, Team
from shared.models.tournament.tournament import Tournament

__all__ = (
    "AnalyticsJob",
    "AnalyticsAnomalyFeedback",
    "AnalyticsMatchQuality",
    "AnalyticsPlayerAnomaly",
    "AnalyticsPerformance",
    "AnalyticsPlayer",
    "AnalyticsAlgorithm",
    "AnalyticsShift",
    "AnalyticsStandingsDistribution",
    "MLModelArtifact",
)


class AnalyticsPlayer(db.TimeStampIntegerMixin):
    __tablename__ = "player_shift"
    __table_args__ = (
        UniqueConstraint("tournament_id", "player_id", name="uq_analytics_player_shift"),
        {"schema": "analytics"},
    )

    tournament_id: Mapped[int] = mapped_column(ForeignKey(Tournament.id, ondelete="CASCADE"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey(Player.id, ondelete="CASCADE"), index=True)
    wins: Mapped[int] = mapped_column()
    losses: Mapped[int] = mapped_column()
    shift_one: Mapped[int | None] = mapped_column(nullable=True)
    shift_two: Mapped[int | None] = mapped_column(nullable=True)
    shift: Mapped[int | None] = mapped_column(nullable=True)

    tournament: Mapped[Tournament] = relationship()
    player: Mapped[Player] = relationship()


class AnalyticsAlgorithm(db.TimeStampIntegerMixin):
    __tablename__ = "algorithms"
    __table_args__ = ({"schema": "analytics"},)

    name: Mapped[str] = mapped_column(String(), unique=True)
    # ``True`` for algorithms that write per-player shift rows into
    # ``analytics.shifts`` (the visible shift algorithms + ``OpenSkill + ML``).
    # ``False`` for augmentation pipelines (Performance ML v2, Standings MC v2,
    # Match Quality v1) that materialise into dedicated tables instead.
    # The HTTP read API filters the dropdown by this flag.
    produces_shifts: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="true", default=True)


class AnalyticsShift(db.TimeStampIntegerMixin):
    __tablename__ = "shifts"
    __table_args__ = (
        UniqueConstraint("tournament_id", "player_id", "algorithm_id", name="uq_analytics_shifts"),
        {"schema": "analytics"},
    )

    tournament_id: Mapped[int] = mapped_column(ForeignKey(Tournament.id, ondelete="CASCADE"), index=True)
    algorithm_id: Mapped[int] = mapped_column(ForeignKey(AnalyticsAlgorithm.id, ondelete="CASCADE"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey(Player.id, ondelete="CASCADE"), index=True)
    #: The player's mis-rating in canonical-ladder divisions (+ = belongs higher).
    shift: Mapped[float] = mapped_column()
    #: Posterior sd of ``shift``, same units; NULL when unknown (rows written before it existed, unranked players).
    shift_sd: Mapped[float | None] = mapped_column(Float(), nullable=True)
    effective_evidence: Mapped[float] = mapped_column(Float(), nullable=False, server_default="0", default=0.0)
    sample_tournaments: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0", default=0)
    sample_matches: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0", default=0)
    log_coverage: Mapped[float] = mapped_column(Float(), nullable=False, server_default="0", default=0.0)

    tournament: Mapped[Tournament] = relationship()
    player: Mapped[Player] = relationship()


# ---------------------------------------------------------------------------
# ML v2 — model registry, predictions
# ---------------------------------------------------------------------------


class MLModelArtifact(db.TimeStampIntegerMixin):
    """Registry of trained ML model artifacts.

    Storage URI points to the serialised booster on disk or S3. One row per
    (algorithm_id, model_kind, role_id, version) tuple; ``is_active=True`` rows
    are loaded by the inference runner.
    """

    __tablename__ = "ml_model_artifact"
    __table_args__ = (
        UniqueConstraint(
            "algorithm_id",
            "model_kind",
            "role_id",
            "version",
            name="uq_analytics_ml_model_artifact_role",
        ),
        ForeignKeyConstraint(
            ["role_id", "dimension_id"],
            ["catalog.role.id", "catalog.role.dimension_id"],
            name="fk_ml_model_artifact_role",
            deferrable=True,
            initially="DEFERRED",
        ),
        {"schema": "analytics"},
    )

    algorithm_id: Mapped[int] = mapped_column(ForeignKey(AnalyticsAlgorithm.id, ondelete="CASCADE"), index=True)
    model_kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    dimension_id: Mapped[int | None] = mapped_column(BigInteger)
    role_id: Mapped[int | None] = mapped_column(BigInteger)
    role_row: Mapped[CatalogRole | None] = relationship(lazy="joined", foreign_keys=[role_id])
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    storage_uri: Mapped[str] = mapped_column(Text(), nullable=False)
    feature_version: Mapped[str] = mapped_column(String(32), nullable=False)
    training_cutoff_tournament_id: Mapped[int] = mapped_column(
        ForeignKey(Tournament.id, ondelete="SET NULL"), nullable=True, index=True
    )
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    feature_importance: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, server_default="false", default=False, index=True
    )

    @property
    def role(self) -> str | None:
        return self.role_row.code if self.role_row is not None else None


class AnalyticsPerformance(db.TimeStampIntegerMixin):
    """Per-player-per-tournament performance v2 prediction.

    Replaces the primitive average of per-match PerformancePoints.
    ``impact_score`` is the 0-100 percentile within (tournament, role) cohort.
    ``raw_value`` is the predicted residual (observed_win - baseline_win_prob).
    Full SHAP lives in ``contributions``; ``top_features`` is the UI top-5 slice.
    """

    __tablename__ = "performance"
    __table_args__ = (
        UniqueConstraint(
            "tournament_id",
            "player_id",
            "algorithm_id",
            name="uq_analytics_performance",
        ),
        {"schema": "analytics"},
    )

    tournament_id: Mapped[int] = mapped_column(ForeignKey(Tournament.id, ondelete="CASCADE"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey(Player.id, ondelete="CASCADE"), index=True)
    algorithm_id: Mapped[int] = mapped_column(ForeignKey(AnalyticsAlgorithm.id, ondelete="CASCADE"), index=True)
    impact_score: Mapped[float] = mapped_column(Float(), nullable=False)
    raw_value: Mapped[float] = mapped_column(Float(), nullable=False)
    confidence: Mapped[float] = mapped_column(Float(), nullable=False, server_default="0", default=0.0)
    log_coverage: Mapped[float] = mapped_column(Float(), nullable=False, server_default="0", default=0.0)
    local_mean: Mapped[float] = mapped_column(Float(), nullable=False, server_default="0", default=0.0)
    local_std: Mapped[float] = mapped_column(Float(), nullable=False, server_default="1", default=1.0)
    local_residual: Mapped[float] = mapped_column(Float(), nullable=False, server_default="0", default=0.0)
    local_zscore: Mapped[float] = mapped_column(Float(), nullable=False, server_default="0", default=0.0)
    local_percentile: Mapped[float] = mapped_column(Float(), nullable=False, server_default="50", default=50.0)
    local_reference_n: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0", default=0)
    local_band_min_div: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    local_band_max_div: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    contributions: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    base_value: Mapped[float | None] = mapped_column(Float(), nullable=True)
    tournament: Mapped[Tournament] = relationship()
    player: Mapped[Player] = relationship()

    @property
    def top_features(self) -> list[dict[str, Any]] | None:
        if not self.contributions:
            return None
        return self.contributions[:5]


class AnalyticsStandingsDistribution(db.TimeStampIntegerMixin):
    """Per-team-per-tournament predicted standings distribution from MC simulation.

    The sole source of predicted standings. The scalar ``predicted_place`` served
    by the read API is derived from these rows as ``round(mean_position)``; the
    distributional columns (percentiles, ``prob_top{1,3,8}``, histogram) back the
    richer v2 consumers.
    """

    __tablename__ = "standings_distribution"
    __table_args__ = (
        UniqueConstraint(
            "tournament_id",
            "team_id",
            "algorithm_id",
            name="uq_analytics_standings_distribution",
        ),
        {"schema": "analytics"},
    )

    tournament_id: Mapped[int] = mapped_column(ForeignKey(Tournament.id, ondelete="CASCADE"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey(Team.id, ondelete="CASCADE"), index=True)
    algorithm_id: Mapped[int] = mapped_column(ForeignKey(AnalyticsAlgorithm.id, ondelete="CASCADE"), index=True)
    mean_position: Mapped[float] = mapped_column(Float(), nullable=False)
    median_position: Mapped[float] = mapped_column(Float(), nullable=False)
    p10_position: Mapped[float] = mapped_column(Float(), nullable=False)
    p90_position: Mapped[float] = mapped_column(Float(), nullable=False)
    prob_top1: Mapped[float] = mapped_column(Float(), nullable=False, server_default="0", default=0.0)
    prob_top3: Mapped[float] = mapped_column(Float(), nullable=False, server_default="0", default=0.0)
    prob_top8: Mapped[float] = mapped_column(Float(), nullable=False, server_default="0", default=0.0)
    position_histogram: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class AnalyticsMatchQuality(db.TimeStampIntegerMixin):
    """Post-hoc quality score for an encounter.

    Player anomalies live in ``analytics.player_anomaly`` and are attached on read.
    """

    __tablename__ = "match_quality"
    __table_args__ = (
        UniqueConstraint(
            "encounter_id",
            "algorithm_id",
            name="uq_analytics_match_quality",
        ),
        {"schema": "analytics"},
    )

    encounter_id: Mapped[int] = mapped_column(ForeignKey(Encounter.id, ondelete="CASCADE"), index=True)
    algorithm_id: Mapped[int] = mapped_column(ForeignKey(AnalyticsAlgorithm.id, ondelete="CASCADE"), index=True)
    competitiveness: Mapped[float] = mapped_column(Float(), nullable=False)
    predictability: Mapped[float] = mapped_column(Float(), nullable=False)
    skill_balance: Mapped[float] = mapped_column(Float(), nullable=False)
    quality_score: Mapped[float] = mapped_column(Float(), nullable=False)


class AnalyticsPlayerAnomaly(db.TimeStampIntegerMixin):
    """Player-level anomaly emitted by the unified player-signal pipeline."""

    __tablename__ = "player_anomaly"
    __table_args__ = (
        UniqueConstraint(
            "tournament_id",
            "player_id",
            "kind",
            "source_encounter_id",
            name="uq_analytics_player_anomaly",
        ),
        {"schema": "analytics"},
    )

    tournament_id: Mapped[int] = mapped_column(ForeignKey(Tournament.id, ondelete="CASCADE"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey(Player.id, ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    score: Mapped[float] = mapped_column(Float(), nullable=False)
    confidence: Mapped[float] = mapped_column(Float(), nullable=False, server_default="0", default=0.0)
    reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    source_encounter_id: Mapped[int | None] = mapped_column(
        ForeignKey(Encounter.id, ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    tournament: Mapped[Tournament] = relationship()
    player: Mapped[Player] = relationship()
    source_encounter: Mapped[Encounter | None] = relationship()


class AnalyticsAnomalyFeedback(db.TimeStampIntegerMixin):
    """Reviewer verdict on a player anomaly.

    Anomaly detectors emit *signals*, not verdicts. Storing an admin's
    confirm/dismiss decision turns those signals into labels, which
    :func:`tune_threshold` uses to pick detector cut-offs by precision/recall
    instead of hand-set magic numbers. One verdict per
    ``(tournament, player, kind)`` — the latest decision wins (upsert).
    """

    __tablename__ = "anomaly_feedback"
    __table_args__ = (
        UniqueConstraint(
            "tournament_id",
            "player_id",
            "kind",
            name="uq_analytics_anomaly_feedback",
        ),
        {"schema": "analytics"},
    )

    tournament_id: Mapped[int] = mapped_column(ForeignKey(Tournament.id, ondelete="CASCADE"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey(Player.id, ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # "confirmed" (true positive) | "dismissed" (false positive)
    verdict: Mapped[str] = mapped_column(String(16), nullable=False)
    reviewer_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    tournament: Mapped[Tournament] = relationship()
    player: Mapped[Player] = relationship()


# ---------------------------------------------------------------------------
# Unified analytics-job tracker
# ---------------------------------------------------------------------------


class AnalyticsJob(db.TimeStampIntegerMixin):
    """Tracks a single analytics computation request end-to-end.

    Replaces the ad-hoc "Recalculate" + "Train ML" + "Run inference" buttons.
    One row per request; the worker writes ``progress`` as each stage finishes
    and flips ``status`` between ``pending → running → succeeded|failed``.

    Concurrency:

    A partial unique index on ``workspace_id`` WHERE ``status IN ('pending',
    'running')`` prevents two simultaneous jobs from racing inside the same
    workspace. The HTTP endpoint surfaces this as a 409 Conflict.

    Permission split (enforced at the HTTP layer, not in the model):

    - ``kind = 'compute'``   — runs v1 recalc + v2 inference. Organizer-allowed
      (``analytics.update``).
    - ``kind = 'train_ml'``  — trains v2 gradient-boosted models. Superuser
      only (resource-heavy, not relevant to tournament organizers).
    """

    __tablename__ = "job"
    __table_args__ = (
        Index(
            "uq_analytics_job_one_running_per_workspace",
            "workspace_id",
            unique=True,
            postgresql_where=sa_text("status IN ('pending', 'running')"),
        ),
        Index("ix_analytics_job_status", "status"),
        {"schema": "analytics"},
    )

    workspace_id: Mapped[int | None] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE"), nullable=True, index=True
    )
    tournament_id: Mapped[int] = mapped_column(ForeignKey(Tournament.id, ondelete="CASCADE"), index=True)
    requested_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # 'compute' | 'train_ml'
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending", default="pending")
    # NOTE (dbarch05 JSON-normalization pass): both of the JSON columns below
    # were evaluated for normalization into FK child tables and intentionally
    # LEFT AS JSON (gated), because they are polymorphic/ephemeral job-request
    # parameters, not sets of stable FK ids:
    #   * ``algorithms`` is polymorphic by ``kind``: for ``kind='compute'`` it
    #     holds v1 algorithm NAMES (soft refs to ``analytics.algorithms.name``),
    #     but for ``kind='train_ml'`` it holds MODEL KINDS
    #     (['performance','shift','standings'] — see the runner + AnalyticsJobCreate
    #     schema), which are not rows in ``analytics.algorithms`` at all. A
    #     ``job_algorithm`` FK table would silently drop every train_ml value.
    #   * ``training_workspace_ids`` is a clean workspace-id array, but it is an
    #     ephemeral, train_ml-only scoping parameter serialized directly into the
    #     ``AnalyticsJobRow`` API response; normalizing it buys no referential
    #     value for a request-tracker row and would only add lazy-load risk.
    algorithms: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    training_workspace_ids: Mapped[list[int] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    progress: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, server_default="{}", default=dict)
    error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    started_at: Mapped[Any | None] = mapped_column(db.DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Any | None] = mapped_column(db.DateTime(timezone=True), nullable=True)
