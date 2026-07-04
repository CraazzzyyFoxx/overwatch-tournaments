from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db
from shared.models.tournament.encounter import Encounter
from shared.models.tournament.team import Player, Team
from shared.models.tournament.tournament import Tournament

if TYPE_CHECKING:
    from shared.models.identity.user import User
    from shared.models.tenancy.workspace import Workspace

__all__ = (
    "AnalyticsBalancePlayerSnapshot",
    "AnalyticsBalanceSnapshot",
    "AnalyticsExplanation",
    "AnalyticsJob",
    "AnalyticsAnomalyFeedback",
    "AnalyticsMatchQuality",
    "AnalyticsPlayerAnomaly",
    "AnalyticsPerformance",
    "AnalyticsPlayer",
    "AnalyticsAlgorithm",
    "AnalyticsPredictions",
    "AnalyticsShift",
    "AnalyticsStandingsDistribution",
    "MLFeatureStore",
    "MLModelArtifact",
)


class AnalyticsPlayer(db.TimeStampIntegerMixin):
    __tablename__ = "tournament"
    __table_args__ = ({"schema": "analytics"},)

    tournament_id: Mapped[int] = mapped_column(
        ForeignKey(Tournament.id, ondelete="CASCADE"), index=True
    )
    player_id: Mapped[int] = mapped_column(
        ForeignKey(Player.id, ondelete="CASCADE"), index=True
    )
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
    produces_shifts: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, server_default="true", default=True
    )


class AnalyticsShift(db.TimeStampIntegerMixin):
    __tablename__ = "shifts"
    __table_args__ = ({"schema": "analytics"},)

    tournament_id: Mapped[int] = mapped_column(
        ForeignKey(Tournament.id, ondelete="CASCADE"), index=True
    )
    algorithm_id: Mapped[int] = mapped_column(
        ForeignKey(AnalyticsAlgorithm.id, ondelete="CASCADE"), index=True
    )
    player_id: Mapped[int] = mapped_column(
        ForeignKey(Player.id, ondelete="CASCADE"), index=True
    )
    shift: Mapped[float] = mapped_column()
    confidence: Mapped[float] = mapped_column(Float(), nullable=False, server_default="0", default=0.0)
    effective_evidence: Mapped[float] = mapped_column(
        Float(), nullable=False, server_default="0", default=0.0
    )
    sample_tournaments: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0", default=0)
    sample_matches: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0", default=0)
    log_coverage: Mapped[float] = mapped_column(Float(), nullable=False, server_default="0", default=0.0)

    tournament: Mapped[Tournament] = relationship()
    player: Mapped[Player] = relationship()


class AnalyticsPredictions(db.TimeStampIntegerMixin):
    __tablename__ = "predictions"
    __table_args__ = ({"schema": "analytics"},)

    tournament_id: Mapped[int] = mapped_column(
        ForeignKey(Tournament.id, ondelete="CASCADE"), index=True
    )
    algorithm_id: Mapped[int] = mapped_column(
        ForeignKey(AnalyticsAlgorithm.id, ondelete="CASCADE"), index=True
    )
    team_id: Mapped[int] = mapped_column(
        ForeignKey(Team.id, ondelete="CASCADE"), index=True
    )
    predicted_place: Mapped[int] = mapped_column()


# ---------------------------------------------------------------------------
# Balance quality snapshots (written at balance export time)
# ---------------------------------------------------------------------------


class AnalyticsBalanceSnapshot(db.TimeStampIntegerMixin):
    """Snapshot of a balance result, created when a balance is exported to a tournament."""

    __tablename__ = "balance_snapshot"
    __table_args__ = (
        UniqueConstraint("tournament_id", "balance_id", name="uq_analytics_balance_snapshot"),
        {"schema": "analytics"},
    )

    tournament_id: Mapped[int] = mapped_column(
        ForeignKey(Tournament.id, ondelete="CASCADE"), index=True
    )
    balance_id: Mapped[int] = mapped_column(
        ForeignKey("balancer.balance.id", ondelete="CASCADE"), index=True
    )
    variant_id: Mapped[int | None] = mapped_column(
        ForeignKey("balancer.balance_variant.id", ondelete="SET NULL"), nullable=True
    )
    workspace_id: Mapped[int | None] = mapped_column(
        ForeignKey("workspace.id", ondelete="SET NULL"), nullable=True
    )
    algorithm: Mapped[str] = mapped_column(String(32), nullable=False)
    division_scope: Mapped[str | None] = mapped_column(String(32), nullable=True)
    division_grid_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    team_count: Mapped[int] = mapped_column(Integer(), nullable=False)
    player_count: Mapped[int] = mapped_column(Integer(), nullable=False)
    avg_sr_overall: Mapped[float] = mapped_column(Float(), nullable=False)
    sr_std_dev: Mapped[float] = mapped_column(Float(), nullable=False)
    sr_range: Mapped[float] = mapped_column(Float(), nullable=False)
    total_discomfort: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0", default=0)
    off_role_count: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0", default=0)
    objective_score: Mapped[float | None] = mapped_column(Float(), nullable=True)

    tournament: Mapped[Tournament] = relationship()
    workspace: Mapped["Workspace | None"] = relationship()
    players: Mapped[list["AnalyticsBalancePlayerSnapshot"]] = relationship(back_populates="snapshot")


class AnalyticsBalancePlayerSnapshot(db.TimeStampIntegerMixin):
    """Per-player snapshot of their balance assignment at export time."""

    __tablename__ = "balance_player_snapshot"
    __table_args__ = ({"schema": "analytics"},)

    balance_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("analytics.balance_snapshot.id", ondelete="CASCADE"), index=True
    )
    tournament_id: Mapped[int] = mapped_column(
        ForeignKey(Tournament.id, ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("players.user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    team_id: Mapped[int | None] = mapped_column(
        ForeignKey(Team.id, ondelete="SET NULL"), nullable=True
    )
    assigned_role: Mapped[str] = mapped_column(String(16), nullable=False)
    preferred_role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    assigned_rank: Mapped[int] = mapped_column(Integer(), nullable=False)
    discomfort: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0", default=0)
    division_number: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    is_captain: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)
    was_off_role: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)

    snapshot: Mapped[AnalyticsBalanceSnapshot] = relationship(back_populates="players")
    tournament: Mapped[Tournament] = relationship()
    user: Mapped["User | None"] = relationship()


# ---------------------------------------------------------------------------
# ML v2 — feature store, model registry, predictions, explanations
# ---------------------------------------------------------------------------


class MLFeatureStore(db.TimeStampIntegerMixin):
    """Cached feature vectors per (tournament, granularity, entity, feature_version).

    Granularity is one of ``'round' | 'match' | 'encounter' | 'tournament'``.
    The actual feature dict is stored as JSON for cheap schema evolution; stable
    columns can be promoted to typed columns once the schema stabilises.
    """

    __tablename__ = "ml_features"
    __table_args__ = (
        UniqueConstraint(
            "tournament_id",
            "granularity",
            "entity_id",
            "feature_version",
            name="uq_analytics_ml_features",
        ),
        {"schema": "analytics"},
    )

    tournament_id: Mapped[int] = mapped_column(
        ForeignKey(Tournament.id, ondelete="CASCADE"), index=True
    )
    granularity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    entity_id: Mapped[int] = mapped_column(Integer(), nullable=False, index=True)
    feature_version: Mapped[str] = mapped_column(String(32), nullable=False)
    features: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    log_coverage: Mapped[float] = mapped_column(
        Float(), nullable=False, server_default="0", default=0.0
    )


class MLModelArtifact(db.TimeStampIntegerMixin):
    """Registry of trained ML model artifacts.

    Storage URI points to the serialised booster on disk or S3. One row per
    (algorithm_id, model_kind, role, version) tuple; ``is_active=True`` rows
    are loaded by the inference runner.
    """

    __tablename__ = "ml_model_artifact"
    __table_args__ = (
        UniqueConstraint(
            "algorithm_id",
            "model_kind",
            "role",
            "version",
            name="uq_analytics_ml_model_artifact",
        ),
        {"schema": "analytics"},
    )

    algorithm_id: Mapped[int] = mapped_column(
        ForeignKey(AnalyticsAlgorithm.id, ondelete="CASCADE"), index=True
    )
    model_kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    role: Mapped[str | None] = mapped_column(String(16), nullable=True)
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


class AnalyticsPerformance(db.TimeStampIntegerMixin):
    """Per-player-per-tournament performance v2 prediction.

    Replaces the primitive ``avg(MatchStatistics.PerformancePoints)``.
    ``impact_score`` is the 0-100 percentile within (tournament, role) cohort.
    ``raw_value`` is the predicted residual (observed_win - baseline_win_prob).
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

    tournament_id: Mapped[int] = mapped_column(
        ForeignKey(Tournament.id, ondelete="CASCADE"), index=True
    )
    player_id: Mapped[int] = mapped_column(
        ForeignKey(Player.id, ondelete="CASCADE"), index=True
    )
    algorithm_id: Mapped[int] = mapped_column(
        ForeignKey(AnalyticsAlgorithm.id, ondelete="CASCADE"), index=True
    )
    impact_score: Mapped[float] = mapped_column(Float(), nullable=False)
    raw_value: Mapped[float] = mapped_column(Float(), nullable=False)
    confidence: Mapped[float] = mapped_column(
        Float(), nullable=False, server_default="0", default=0.0
    )
    log_coverage: Mapped[float] = mapped_column(
        Float(), nullable=False, server_default="0", default=0.0
    )
    local_mean: Mapped[float] = mapped_column(
        Float(), nullable=False, server_default="0", default=0.0
    )
    local_std: Mapped[float] = mapped_column(
        Float(), nullable=False, server_default="1", default=1.0
    )
    local_residual: Mapped[float] = mapped_column(
        Float(), nullable=False, server_default="0", default=0.0
    )
    local_zscore: Mapped[float] = mapped_column(
        Float(), nullable=False, server_default="0", default=0.0
    )
    local_percentile: Mapped[float] = mapped_column(
        Float(), nullable=False, server_default="50", default=50.0
    )
    local_reference_n: Mapped[int] = mapped_column(
        Integer(), nullable=False, server_default="0", default=0
    )
    local_band_min_div: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    local_band_max_div: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    top_features: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)

    tournament: Mapped[Tournament] = relationship()
    player: Mapped[Player] = relationship()


class AnalyticsStandingsDistribution(db.TimeStampIntegerMixin):
    """Per-team-per-tournament predicted standings distribution from MC simulation.

    Replaces the deterministic integer ``predicted_place`` from
    ``AnalyticsPredictions``. v1 ``predicted_place`` is kept for backwards
    compatibility; v2 consumers should read these distributional columns.
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

    tournament_id: Mapped[int] = mapped_column(
        ForeignKey(Tournament.id, ondelete="CASCADE"), index=True
    )
    team_id: Mapped[int] = mapped_column(
        ForeignKey(Team.id, ondelete="CASCADE"), index=True
    )
    algorithm_id: Mapped[int] = mapped_column(
        ForeignKey(AnalyticsAlgorithm.id, ondelete="CASCADE"), index=True
    )
    mean_position: Mapped[float] = mapped_column(Float(), nullable=False)
    median_position: Mapped[float] = mapped_column(Float(), nullable=False)
    p10_position: Mapped[float] = mapped_column(Float(), nullable=False)
    p90_position: Mapped[float] = mapped_column(Float(), nullable=False)
    prob_top1: Mapped[float] = mapped_column(Float(), nullable=False, server_default="0", default=0.0)
    prob_top3: Mapped[float] = mapped_column(Float(), nullable=False, server_default="0", default=0.0)
    prob_top8: Mapped[float] = mapped_column(Float(), nullable=False, server_default="0", default=0.0)
    position_histogram: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class AnalyticsMatchQuality(db.TimeStampIntegerMixin):
    """Post-hoc quality score for an encounter + anomaly flags."""

    __tablename__ = "match_quality"
    __table_args__ = (
        UniqueConstraint(
            "encounter_id",
            "algorithm_id",
            name="uq_analytics_match_quality",
        ),
        {"schema": "analytics"},
    )

    encounter_id: Mapped[int] = mapped_column(
        ForeignKey(Encounter.id, ondelete="CASCADE"), index=True
    )
    algorithm_id: Mapped[int] = mapped_column(
        ForeignKey(AnalyticsAlgorithm.id, ondelete="CASCADE"), index=True
    )
    competitiveness: Mapped[float] = mapped_column(Float(), nullable=False)
    predictability: Mapped[float] = mapped_column(Float(), nullable=False)
    skill_balance: Mapped[float] = mapped_column(Float(), nullable=False)
    quality_score: Mapped[float] = mapped_column(Float(), nullable=False)
    anomaly_flags: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)


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

    tournament_id: Mapped[int] = mapped_column(
        ForeignKey(Tournament.id, ondelete="CASCADE"), index=True
    )
    player_id: Mapped[int] = mapped_column(
        ForeignKey(Player.id, ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    score: Mapped[float] = mapped_column(Float(), nullable=False)
    confidence: Mapped[float] = mapped_column(
        Float(), nullable=False, server_default="0", default=0.0
    )
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

    tournament_id: Mapped[int] = mapped_column(
        ForeignKey(Tournament.id, ondelete="CASCADE"), index=True
    )
    player_id: Mapped[int] = mapped_column(
        ForeignKey(Player.id, ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # "confirmed" (true positive) | "dismissed" (false positive)
    verdict: Mapped[str] = mapped_column(String(16), nullable=False)
    reviewer_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    tournament: Mapped[Tournament] = relationship()
    player: Mapped[Player] = relationship()


class AnalyticsExplanation(db.TimeStampIntegerMixin):
    """SHAP-style attribution rows: full list of feature contributions per prediction.

    The top-K contributions are also denormalised into
    ``AnalyticsPerformance.top_features`` for the UI hot path; this table is
    the archive with full contribution detail.
    """

    __tablename__ = "explanation"
    __table_args__ = ({"schema": "analytics"},)

    algorithm_id: Mapped[int] = mapped_column(
        ForeignKey(AnalyticsAlgorithm.id, ondelete="CASCADE"), index=True
    )
    entity_id: Mapped[int] = mapped_column(Integer(), nullable=False, index=True)
    entity_kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    tournament_id: Mapped[int] = mapped_column(
        ForeignKey(Tournament.id, ondelete="CASCADE"), index=True
    )
    base_value: Mapped[float] = mapped_column(Float(), nullable=False)
    contributions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)


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
    tournament_id: Mapped[int] = mapped_column(
        ForeignKey(Tournament.id, ondelete="CASCADE"), index=True
    )
    requested_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # 'compute' | 'train_ml'
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="pending", default="pending"
    )
    algorithms: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    training_workspace_ids: Mapped[list[int] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    progress: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, server_default="{}", default=dict
    )
    error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    started_at: Mapped[Any | None] = mapped_column(
        db.DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[Any | None] = mapped_column(
        db.DateTime(timezone=True), nullable=True
    )
