from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.core import db, enums

__all__ = (
    "UserRankSnapshot",
    "BattleTagRankState",
)

#: Logical Postgres schema isolating rank telemetry from player identity.
RANK_SCHEMA = "overwatch_rank"


class UserRankSnapshot(db.TimeStampIntegerMixin):
    """A single observation of a battle.net account's competitive rank.

    One row is written per scheduled run, per battle tag, per role, per
    platform — a full time series (history is "every run"). Native OverFast
    ``division``/``tier`` are always stored; ``rank_value`` is the optional
    mapped integer (see the rank-mapping service) so the value stays compatible
    with the existing DivisionGrid/balancer scale. Attached to the domain
    ``players.user`` — never to ``auth.user``.
    """

    __tablename__ = "rank_snapshot"
    __table_args__ = (
        Index("ix_rank_snapshot_user_captured", "user_id", "captured_at"),
        Index(
            "ix_rank_snapshot_series_captured",
            "battle_tag_id",
            "role",
            "platform",
            "captured_at",
        ),
        {"schema": RANK_SCHEMA},
    )

    # Not individually indexed: the composite indexes below cover these columns
    # as their leftmost prefix.
    user_id: Mapped[int] = mapped_column(
        ForeignKey("players.user.id", ondelete="CASCADE")
    )
    battle_tag_id: Mapped[int] = mapped_column(
        ForeignKey("players.battle_tag.id", ondelete="CASCADE")
    )
    # Denormalized full "Name#1234" so history survives battle-tag deletion.
    battle_tag: Mapped[str] = mapped_column(String(255))

    platform: Mapped[str] = mapped_column(String(16))  # enums.RankPlatform
    role: Mapped[str] = mapped_column(String(16))  # enums.RankRole

    # Native OverFast rank; null when the player is unranked in that role.
    division: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tier: Mapped[int | None] = mapped_column(SmallInteger(), nullable=True)
    season: Mapped[int | None] = mapped_column(Integer(), nullable=True)

    # Mapped integer rank (nullable: native data is kept even if unmapped).
    rank_value: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    mapping_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

    is_ranked: Mapped[bool] = mapped_column(Boolean(), server_default="true")

    # Relevant `competitive` sub-object from /summary (not the whole profile).
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB(), nullable=True)

    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=db.func.now(), index=True
    )
    source: Mapped[str] = mapped_column(
        String(32), server_default=enums.RankCollectionSource.scheduled.value
    )


class BattleTagRankState(db.TimeStampIntegerMixin):
    """Collection bookkeeping for one battle tag (one row per tag).

    Kept separate from ``players.battle_tag`` (identity data) because this row
    is high-churn — updated on every poll — and drives scheduling, backoff and
    prioritization without touching the identity table or its indexes.
    """

    __tablename__ = "battle_tag_state"
    __table_args__ = (
        Index(
            "ix_battle_tag_state_due",
            "status",
            "next_eligible_at",
            "last_checked_at",
        ),
        Index("ix_battle_tag_state_priority", "priority_tier", "last_checked_at"),
        {"schema": RANK_SCHEMA},
    )

    battle_tag_id: Mapped[int] = mapped_column(
        ForeignKey("players.battle_tag.id", ondelete="CASCADE"), unique=True
    )
    battle_tag: Mapped[str] = mapped_column(String(255))
    # Precomputed OverFast player id ("Name-1234").
    player_id_slug: Mapped[str] = mapped_column(String(255))

    # Not individually indexed: covered by the composite indexes below.
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey(f"{RANK_SCHEMA}.rank_snapshot.id", ondelete="SET NULL"),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(32), server_default=enums.RankCollectionStatus.pending.value
    )
    consecutive_failures: Mapped[int] = mapped_column(Integer(), server_default="0")
    next_eligible_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    # 0 = background sweep (all users); higher = registration-driven priority.
    priority_tier: Mapped[int] = mapped_column(SmallInteger(), server_default="0")
