import typing
from enum import StrEnum

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db
from shared.models.hero import Hero
from shared.models.tournament import Tournament
from shared.models.user import User

if typing.TYPE_CHECKING:
    from shared.models.match import Match
    from shared.models.workspace import Workspace

__all__ = (
    "AchievementCategory",
    "AchievementGrain",
    "AchievementOverrideAction",
    "AchievementRule",
    "AchievementEvaluationResult",
    "AchievementOverride",
    "AchievementScope",
    "EvaluationRun",
    "EvaluationRunStatus",
    "EvaluationRunTrigger",
    # Keep old models during migration
    "Achievement",
    "AchievementUser",
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class AchievementCategory(StrEnum):
    overall = "overall"
    hero = "hero"
    division = "division"
    team = "team"
    standing = "standing"
    match = "match"


class AchievementScope(StrEnum):
    glob = "global"
    tournament = "tournament"
    match = "match"


class AchievementGrain(StrEnum):
    user = "user"
    user_tournament = "user_tournament"
    user_match = "user_match"


class AchievementOverrideAction(StrEnum):
    grant = "grant"
    revoke = "revoke"


class EvaluationRunTrigger(StrEnum):
    parse_complete = "parse_complete"
    manual = "manual"
    rule_version_bump = "rule_version_bump"


class EvaluationRunStatus(StrEnum):
    running = "running"
    done = "done"
    failed = "failed"
    cancelled = "cancelled"


# ---------------------------------------------------------------------------
# New models
# ---------------------------------------------------------------------------


class AchievementRule(db.TimeStampIntegerMixin):
    """Declarative achievement rule — single source of truth.

    Contains both the achievement metadata (name, description, image)
    and the evaluation logic (condition_tree as JSON).
    """

    __tablename__ = "rule"
    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_achievement_rule_workspace_slug"),
        {"schema": "achievements"},
    )

    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE"), index=True
    )
    slug: Mapped[str] = mapped_column(String(), index=True)
    name: Mapped[str] = mapped_column(String())
    description_ru: Mapped[str] = mapped_column(String())
    description_en: Mapped[str] = mapped_column(String())
    image_url: Mapped[str | None] = mapped_column(String(), nullable=True)
    hero_id: Mapped[int | None] = mapped_column(
        ForeignKey(Hero.id, ondelete="SET NULL"), nullable=True
    )

    category: Mapped[AchievementCategory] = mapped_column(String())
    scope: Mapped[AchievementScope] = mapped_column(String())
    grain: Mapped[AchievementGrain] = mapped_column(String())

    condition_tree: Mapped[dict] = mapped_column(JSON, nullable=False, server_default="{}")
    depends_on: Mapped[list[str]] = mapped_column(JSON, server_default="[]")

    enabled: Mapped[bool] = mapped_column(Boolean(), server_default="true")
    rule_version: Mapped[int] = mapped_column(Integer(), server_default="1")
    min_tournament_id: Mapped[int | None] = mapped_column(Integer(), nullable=True)

    hero: Mapped[Hero | None] = relationship()
    workspace: Mapped["Workspace"] = relationship()
    evaluation_results: Mapped[list["AchievementEvaluationResult"]] = relationship(
        back_populates="rule", passive_deletes=True
    )


class AchievementEvaluationResult(db.TimeStampIntegerMixin):
    """Stores which users qualified for an achievement and why."""

    __tablename__ = "evaluation_result"
    __table_args__ = (
        UniqueConstraint(
            "achievement_rule_id",
            "user_id",
            "tournament_id",
            "match_id",
            name="uq_eval_result_rule_user_tournament_match",
        ),
        {"schema": "achievements"},
    )

    achievement_rule_id: Mapped[int] = mapped_column(
        ForeignKey("achievements.rule.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("players.user.id", ondelete="CASCADE"), index=True
    )
    tournament_id: Mapped[int | None] = mapped_column(
        ForeignKey(Tournament.id, ondelete="CASCADE"), nullable=True, index=True
    )
    match_id: Mapped[int | None] = mapped_column(
        ForeignKey("matches.match.id", ondelete="CASCADE"), nullable=True
    )
    qualified_at: Mapped[db.datetime] = mapped_column(
        db.DateTime(timezone=True), server_default=func.now()
    )
    evidence_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    rule_version: Mapped[int] = mapped_column(Integer())
    run_id: Mapped[str | None] = mapped_column(Uuid(), nullable=True, index=True)

    rule: Mapped[AchievementRule] = relationship(back_populates="evaluation_results")
    user: Mapped[User] = relationship()
    tournament: Mapped[Tournament | None] = relationship()
    match: Mapped[typing.Optional["Match"]] = relationship()


class AchievementOverride(db.TimeStampIntegerMixin):
    """Manual grant or revocation of an achievement.

    Overrides live as a separate overlay — they never mutate evaluation results.
    """

    __tablename__ = "override"
    __table_args__ = ({"schema": "achievements"},)

    achievement_rule_id: Mapped[int] = mapped_column(
        ForeignKey("achievements.rule.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("players.user.id", ondelete="CASCADE"), index=True
    )
    tournament_id: Mapped[int | None] = mapped_column(
        ForeignKey(Tournament.id, ondelete="CASCADE"), nullable=True
    )
    match_id: Mapped[int | None] = mapped_column(
        ForeignKey("matches.match.id", ondelete="CASCADE"), nullable=True
    )
    action: Mapped[AchievementOverrideAction] = mapped_column(String())
    reason: Mapped[str] = mapped_column(String())
    granted_by: Mapped[int] = mapped_column(
        ForeignKey("auth.user.id", ondelete="SET NULL")
    )

    rule: Mapped[AchievementRule] = relationship()
    user: Mapped[User] = relationship()


class EvaluationRun(db.TimeStampUUIDMixin):
    """Audit log of achievement evaluation runs."""

    __tablename__ = "evaluation_run"
    __table_args__ = ({"schema": "achievements"},)

    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE"), index=True
    )
    trigger: Mapped[EvaluationRunTrigger] = mapped_column(String())
    tournament_id: Mapped[int | None] = mapped_column(
        ForeignKey(Tournament.id, ondelete="SET NULL"), nullable=True
    )
    rules_evaluated: Mapped[int] = mapped_column(Integer(), server_default="0")
    results_created: Mapped[int] = mapped_column(Integer(), server_default="0")
    results_removed: Mapped[int] = mapped_column(Integer(), server_default="0")
    started_at: Mapped[db.datetime] = mapped_column(
        db.DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[db.datetime | None] = mapped_column(
        db.DateTime(timezone=True), nullable=True
    )
    status: Mapped[EvaluationRunStatus] = mapped_column(String(), server_default="running")
    error_message: Mapped[str | None] = mapped_column(String(), nullable=True)


# ---------------------------------------------------------------------------
# Old models (kept for migration period, will be removed)
# ---------------------------------------------------------------------------


class Achievement(db.TimeStampIntegerMixin):
    __tablename__ = "achievement"
    __table_args__ = ({"schema": "achievements"},)

    name: Mapped[str] = mapped_column(String())
    slug: Mapped[str] = mapped_column(String(), unique=True, index=True)
    description_ru: Mapped[str] = mapped_column(String())
    description_en: Mapped[str] = mapped_column(String())
    image_url: Mapped[str | None] = mapped_column(String(), nullable=True)
    hero_id: Mapped[int | None] = mapped_column(
        ForeignKey(Hero.id, ondelete="CASCADE"), nullable=True
    )

    hero: Mapped[Hero | None] = relationship()


class AchievementUser(db.TimeStampIntegerMixin):
    __tablename__ = "user"
    __table_args__ = ({"schema": "achievements"},)

    user_id: Mapped[int] = mapped_column(ForeignKey("players.user.id", ondelete="CASCADE"))
    achievement_id: Mapped[int] = mapped_column(
        ForeignKey(Achievement.id, ondelete="CASCADE")
    )
    tournament_id: Mapped[int | None] = mapped_column(
        ForeignKey(Tournament.id, ondelete="CASCADE"), nullable=True
    )
    match_id: Mapped[int | None] = mapped_column(
        ForeignKey("matches.match.id", ondelete="CASCADE"), nullable=True
    )

    tournament: Mapped[Tournament] = relationship()
    achievement: Mapped[Achievement] = relationship()
    match: Mapped[typing.Optional["Match"]] = relationship()
    user: Mapped[User] = relationship()
