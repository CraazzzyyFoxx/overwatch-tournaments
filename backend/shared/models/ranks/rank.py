from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.core import db, enums

__all__ = (
    "CareerSnapshot",
    "CharacterRate",
    "GameAccountProfile",
    "RankAccountState",
    "RankFetchLog",
    "UserRankSnapshot",
)

#: One schema for every game's upstream telemetry of game accounts -- ranks, profiles, careers -- and the game's own
#: character rates, isolated from player identity; each row names its game in ``discipline``.
RANK_SCHEMA = "rank"


class UserRankSnapshot(db.Base):
    """One observed CHANGE of a game account's rank (``discipline`` names the game).

    Overwatch: one series per (account, role, platform), OverFast ``division``/``tier``. League of Legends: one series
    per (account, ``queue``) — ``solo``/``flex`` — with ``division`` = league-v4 tier, ``tier`` = 1..4 (apex NULL),
    ``lp``/``wins``/``losses``, no role and no platform. Written only when the poll finds something different from the
    series' last row (migration ``rankdedup01``; ``stats-service`` ``changed_ranks``). The first poll of an account
    records every series, unranked ones included, so every later transition -- ranked to unranked too -- has a row to
    be read against. A poll that changes nothing writes nothing; the state row's ``last_success_at`` is what proves
    the account was checked. Native ``division``/``tier`` are always stored; ``rank_value`` is the game's own ladder
    value (Overwatch: the mapped integer compatible with the DivisionGrid/balancer scale). Attached to the domain
    ``players.user`` -- never to ``auth.user``.

    ``db.Base`` rather than ``TimeStampIntegerMixin``: the mixin's ``created_at`` would duplicate ``captured_at``
    while ``updated_at`` stays NULL on every row of an append-only series.
    """

    __tablename__ = "rank_snapshot"
    __table_args__ = (
        Index("ix_rank_snapshot_user_captured", "user_id", "captured_at"),
        Index("ix_rank_snapshot_series_captured", "social_account_id", "role", "platform", "queue", "captured_at"),
        # The "newest ranked snapshot per (account, role, queue)" probe (registration autofill, native reads): one
        # index descent per pair instead of a sort over the whole history. Partial so an account unranked in a
        # series does not walk its history.
        Index(
            "ix_rank_snapshot_latest_ranked",
            "social_account_id",
            "role",
            "queue",
            text("captured_at DESC"),
            postgresql_where=text("rank_value IS NOT NULL AND is_ranked IS TRUE"),
        ),
        {"schema": RANK_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger(), primary_key=True, sort_order=-1000)
    discipline: Mapped[str] = mapped_column(String(32))
    # Not individually indexed: the composite indexes above cover these columns as their leftmost prefix.
    user_id: Mapped[int] = mapped_column(ForeignKey("players.user.id", ondelete="CASCADE"))
    # The game account's ``players.social_account`` row this rank belongs to.
    social_account_id: Mapped[int] = mapped_column(ForeignKey("players.social_account.id", ondelete="CASCADE"))
    # Denormalized account label ("Name#1234", "Name#TAG") so history survives account deletion.
    handle: Mapped[str] = mapped_column(String(255))

    platform: Mapped[str | None] = mapped_column(String(16), nullable=True)  # OW enums.RankPlatform; LoL NULL
    role: Mapped[str | None] = mapped_column(String(16), nullable=True)  # OW enums.HeroClass.name; LoL NULL
    queue: Mapped[str | None] = mapped_column(String(16), nullable=True)  # LoL "solo" | "flex"; OW NULL

    # Native rank; null when the player is unranked in that series.
    division: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tier: Mapped[int | None] = mapped_column(SmallInteger(), nullable=True)
    season: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    lp: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    wins: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    losses: Mapped[int | None] = mapped_column(Integer(), nullable=True)

    # Ladder integer rank (nullable: native data is kept even if unmapped).
    rank_value: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    mapping_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

    is_ranked: Mapped[bool] = mapped_column(Boolean(), server_default="true")

    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=db.func.now(), index=True)
    source: Mapped[str] = mapped_column(String(32), server_default=enums.RankCollectionSource.scheduled.value)


class RankAccountState(db.TimeStampIntegerMixin):
    """Collection bookkeeping for one game account (one row per ``players.social_account``).

    Kept separate from ``players.social_account`` (identity data) because this row is high-churn — updated on every
    poll — and drives scheduling, backoff and prioritization without touching the identity table or its indexes.
    ``external_id`` is the upstream's own id (OverFast "Name-1234", Riot PUUID); ``region`` the LoL platform.
    """

    __tablename__ = "account_state"
    __table_args__ = (
        Index("ix_account_state_due", "discipline", "status", "next_eligible_at", "last_checked_at"),
        Index("ix_account_state_priority", "priority_tier", "last_checked_at"),
        {"schema": RANK_SCHEMA},
    )

    discipline: Mapped[str] = mapped_column(String(32))
    social_account_id: Mapped[int] = mapped_column(
        ForeignKey("players.social_account.id", ondelete="CASCADE"), unique=True
    )
    handle: Mapped[str] = mapped_column(String(255))
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    region: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # Not individually indexed: covered by the composite indexes above.
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    status: Mapped[str] = mapped_column(String(32), server_default=enums.RankCollectionStatus.pending.value)
    consecutive_failures: Mapped[int] = mapped_column(Integer(), server_default="0")
    next_eligible_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    # 0 = background sweep (all users); higher = registration-driven priority.
    priority_tier: Mapped[int] = mapped_column(SmallInteger(), server_default="0")


class RankFetchLog(db.TimeStampIntegerMixin):
    """Append-only log of worker fetch attempts — the global task history, per game.

    One row per processed fetch; ``created_at`` (from the mixin) is the completion time. Powers the admin task feed.
    """

    __tablename__ = "fetch_log"
    __table_args__ = (
        Index("ix_fetch_log_created_at", "created_at"),
        Index("ix_fetch_log_status_created", "status", "created_at"),
        {"schema": RANK_SCHEMA},
    )

    discipline: Mapped[str] = mapped_column(String(32))
    social_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("players.social_account.id", ondelete="SET NULL"), nullable=True
    )
    handle: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32))  # enums.RankCollectionStatus
    source: Mapped[str] = mapped_column(String(32))  # enums.RankCollectionSource
    error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    snapshots_written: Mapped[int] = mapped_column(Integer(), server_default="0")


class GameAccountProfile(db.TimeStampIntegerMixin):
    """What the game's upstream last showed for one game account: its display name, avatar and attributes.

    Current state, one row per ``players.social_account``, rewritten on every successful poll; no history.
    ``canonical_id`` is the upstream's rename-proof id of the account (Overwatch: the Blizzard career id), resolved
    once and used to keep reading the account after its handle stopped resolving; ``canonical_checked_at`` paces that
    resolution. ``attrs`` holds the game's own profile fields (Overwatch: namecard, title, endorsement level).
    ``is_public`` is whether the last poll saw the career: a closed profile still shows its name and avatar, and what
    was collected while it was open must not be shown while it is closed.
    """

    __tablename__ = "account_profile"
    __table_args__ = ({"schema": RANK_SCHEMA},)

    discipline: Mapped[str] = mapped_column(String(32))
    social_account_id: Mapped[int] = mapped_column(
        ForeignKey("players.social_account.id", ondelete="CASCADE"), unique=True
    )
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text(), nullable=True)
    attrs: Mapped[dict[str, Any]] = mapped_column(JSONB(), default=dict, server_default=text("'{}'::jsonb"))
    canonical_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    canonical_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The upstream's own "profile last changed" moment; ``fetched_at`` is our last successful read.
    upstream_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_public: Mapped[bool] = mapped_column(Boolean(), server_default=text("false"))


class CareerSnapshot(db.Base):
    """One observed CHANGE of a game account's cumulative career statistics for one character.

    A series is (account, ``platform``, ``queue``, ``character``); a row is written only when the poll finds the
    series different from its last row (``season`` + ``digest``), like ``rank_snapshot``. The difference of two rows of
    a series is what the player played between them. ``stats`` is ``{category: {stat key: number}}`` exactly as the
    upstream groups it; ``digest`` is its hash, so a poll compares series without reading the JSON back. ``season`` is
    the season the figures belong to where the upstream shows one season only (Overwatch competitive), else NULL.
    ``character`` is the upstream's character key or its whole-account pseudo key (Overwatch ``all-heroes``).
    """

    __tablename__ = "career_snapshot"
    __table_args__ = (
        Index(
            "ix_career_snapshot_series_captured",
            "social_account_id",
            "platform",
            "queue",
            "character",
            text("captured_at DESC"),
        ),
        {"schema": RANK_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger(), primary_key=True, sort_order=-1000)
    discipline: Mapped[str] = mapped_column(String(32))
    social_account_id: Mapped[int] = mapped_column(ForeignKey("players.social_account.id", ondelete="CASCADE"))
    platform: Mapped[str | None] = mapped_column(String(16), nullable=True)
    queue: Mapped[str | None] = mapped_column(String(16), nullable=True)
    season: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    character: Mapped[str] = mapped_column(String(64))
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB())
    digest: Mapped[str] = mapped_column(String(32))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=db.func.now())


class CharacterRate(db.Base):
    """The game's own pick, win and ban rate of one character in one slice of its ladder, on one day.

    Written at most once a day per slice. ``division`` and ``map`` NULL mean "every division" / "every map";
    ``banrate`` is NULL where the queue has no bans.
    """

    __tablename__ = "character_rate"
    __table_args__ = (
        UniqueConstraint(
            "discipline",
            "captured_on",
            "platform",
            "queue",
            "region",
            "division",
            "map",
            "character",
            name="uq_character_rate_slice",
            postgresql_nulls_not_distinct=True,
        ),
        {"schema": RANK_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger(), primary_key=True, sort_order=-1000)
    discipline: Mapped[str] = mapped_column(String(32))
    captured_on: Mapped[date] = mapped_column(Date())
    platform: Mapped[str | None] = mapped_column(String(16), nullable=True)
    queue: Mapped[str | None] = mapped_column(String(16), nullable=True)
    region: Mapped[str | None] = mapped_column(String(16), nullable=True)
    division: Mapped[str | None] = mapped_column(String(32), nullable=True)
    map: Mapped[str | None] = mapped_column(String(64), nullable=True)
    character: Mapped[str] = mapped_column(String(64))
    pickrate: Mapped[float | None] = mapped_column(Float(), nullable=True)
    winrate: Mapped[float | None] = mapped_column(Float(), nullable=True)
    banrate: Mapped[float | None] = mapped_column(Float(), nullable=True)
