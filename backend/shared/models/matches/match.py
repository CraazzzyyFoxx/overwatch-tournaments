from sqlalchemy import BigInteger, Boolean, Enum, Float, ForeignKey, Index, Integer, column, exists, table, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, column_property, mapped_column, relationship

from shared.core import db, enums
from shared.models.catalog.hero import Hero
from shared.models.catalog.map import Map
from shared.models.identity.user import User
from shared.models.ingestion.log_processing import LogProcessingRecord
from shared.models.tournament.encounter import Encounter
from shared.models.tournament.team import Team

__all__ = (
    "Match",
    "MatchStatistics",
    "MatchKillFeed",
    "MatchEvent",
    "mv_hero_global_stats",
)


class Match(db.TimeStampIntegerMixin):
    __tablename__ = "match"
    __table_args__ = ({"schema": "matches"},)

    home_team_id: Mapped[int] = mapped_column(ForeignKey(Team.id, ondelete="CASCADE"), index=True)
    away_team_id: Mapped[int] = mapped_column(ForeignKey(Team.id, ondelete="CASCADE"), index=True)
    home_score: Mapped[int] = mapped_column(Integer())
    away_score: Mapped[int] = mapped_column(Integer())
    # NULL for a `source=captain_report` row: no log means no measured
    # duration. Always present for `source=log_parser`.
    time: Mapped[float | None] = mapped_column(Float(), nullable=True)
    # The bare log filename as the parser saw it. Kept because the S3 key is
    # built from it (logs/{tournament_id}/{log_name}); provenance itself lives on
    # log_record_id below. NULL for a `source=captain_report` row — there is no
    # file. `source` is the field to branch on, not this nullability.
    log_name: Mapped[str | None] = mapped_column(nullable=True)
    code: Mapped[str | None] = mapped_column(nullable=True)
    # Which ingested log produced this match. Nullable: rows written before this
    # column existed cannot always be matched back, and the backfill leaves those
    # NULL rather than guessing. SET NULL so pruning ingestion history never
    # deletes a played map.
    log_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("log_processing.record.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # `log_parser`: written by MatchLogFlow from an uploaded OW log — `time`/
    # `log_name` populated, kill-feed/stats may follow. `captain_report`:
    # written from the per-map dual captain confirmation with no log — `time`/
    # `log_name` stay NULL, no kill-feed/stats exist. Every row written before
    # this column existed is a real parsed log, hence the `log_parser` default —
    # never re-guessed for the backfill (see the pick-ban engine's migration).
    source: Mapped[enums.MatchSource] = mapped_column(
        Enum(
            enums.MatchSource,
            values_callable=lambda e: [x.value for x in e],
            name="matchsource",
            schema="matches",
        ),
        default=enums.MatchSource.LOG_PARSER,
        server_default=enums.MatchSource.LOG_PARSER.value,
    )

    encounter_id: Mapped[int] = mapped_column(ForeignKey(Encounter.id, ondelete="CASCADE"), index=True)
    map_id: Mapped[int] = mapped_column(ForeignKey("overwatch.map.id", ondelete="CASCADE"), index=True)
    # Which map OF THE SERIES this row is, 1-based in play order (the index
    # ``EncounterMapCode``/``EncounterMapReport`` use). NULL when unknown: every
    # parsed log, and every row written before this column existed. Stamped by
    # ``map_report.submit_map_report`` on the row it reconciles, because a series
    # can play the SAME map twice — without a position the second play's result
    # overwrote the first play's row instead of standing beside it.
    map_index: Mapped[int | None] = mapped_column(Integer(), nullable=True)

    home_team: Mapped[Team] = relationship(foreign_keys=[home_team_id])
    away_team: Mapped[Team] = relationship(foreign_keys=[away_team_id])
    encounter: Mapped[Encounter] = relationship(back_populates="matches")
    map: Mapped[Map] = relationship()
    # lazy="raise": only the admin surfaces need it, and an implicit load here
    # would fire inside async paths that cannot do IO on attribute access.
    log_record: Mapped[LogProcessingRecord | None] = relationship(lazy="raise")


# Derived from ``Match`` existence rather than stored: a persisted boolean
# here would need a writer to keep it in sync with this table (the old
# design had exactly one, set-only-once, never reset back to False on log
# removal). Filtered on ``source == log_parser`` — a ``captain_report`` row
# (``map_report.submit_map_report`` upserts one before any log arrives, with
# no log behind it) must NOT count, or the public "logs available" badge
# would light up on encounters nobody ever uploaded a log for. The EXISTS
# subquery is index-backed via ``encounter_id`` above, computed by Postgres
# in the same SELECT as the rest of the row (no lazy load, so no
# async/greenlet hazard — see ``Team.avg_sr`` for the same pattern), and can
# never drift from the actual match rows.
Encounter.has_logs = column_property(
    exists()
    .where(Match.encounter_id == Encounter.id, Match.source == enums.MatchSource.LOG_PARSER)
    .correlate_except(Match)
)


class MatchStatistics(db.Base):
    __tablename__ = "statistics"

    __table_args__ = (
        Index("ix_match_statistics_user_round_name", "user_id", "round", "name"),
        Index("ix_match_statistics_match_user_round", "match_id", "user_id", "round"),
        Index("ix_match_statistics_match_name_round", "match_id", "name", "round"),
        Index(
            "ix_match_statistics_user_name_r0",
            "user_id",
            "name",
            postgresql_where=text("round = 0 AND hero_id IS NULL"),
        ),
        Index(
            "ix_match_statistics_user_hero_r0",
            "user_id",
            "hero_id",
            "name",
            postgresql_where=text("round = 0 AND hero_id IS NOT NULL"),
        ),
        Index(
            "ix_match_statistics_playtime_r0",
            "match_id",
            "user_id",
            "hero_id",
            # Enum(LogStatsName) persists the member NAME (HeroTimePlayed), not
            # its .value (hero_time_played); this raw predicate bypasses the type.
            postgresql_where=text("round = 0 AND name = 'HeroTimePlayed'"),
        ),
        {"schema": "matches"},
    )

    # Declared here instead of inherited from ``TimeStampIntegerMixin`` so this
    # table carries the surrogate key WITHOUT the mixin's ``created_at`` /
    # ``updated_at``: 16 bytes on every one of 27M rows (425 MB measured on a
    # production restore, migration ``statslim01``) that nothing ever reads. A
    # row's lifetime is its match's — the parser deletes and re-inserts a match's
    # rows wholesale on every log re-parse — so an insertion timestamp answers no
    # question anyone asks, and there is no retention or audit built on it.
    #
    # The PRIMARY KEY constraint behind this column is dropped in the database
    # (migration ``statdrop01``, 585 MB of index no query used); the mapper keeps
    # ``primary_key=True`` because SQLAlchemy requires a primary key at metadata
    # level, and Alembic never autogenerates primary-key changes. Nothing loads
    # this table as an ORM entity, so the identity map is inert either way.
    id: Mapped[int] = mapped_column(BigInteger(), primary_key=True, sort_order=-1000)

    match_id: Mapped[int] = mapped_column(ForeignKey(Match.id, ondelete="CASCADE"))
    # No standalone index on ``round`` / ``hero_id``: both are low-cardinality and
    # dead in production (see migration ``statidx001``); the composite indexes
    # above serve every access pattern that touches them.
    #
    # ``match_id``, ``user_id`` and ``name`` carry no standalone index either
    # (migration ``statdrop01``): the first two are strict prefixes of the
    # composites above, and a lone index on a 48-label enum is never selective
    # enough to be chosen. ``team_id`` keeps its own — it is only ever a join
    # key (``services.user.queries.compare``), never a prefix of anything here.
    round: Mapped[int] = mapped_column(Integer())
    team_id: Mapped[int] = mapped_column(ForeignKey(Team.id, ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey(User.id, ondelete="CASCADE"))
    hero_id: Mapped[int | None] = mapped_column(ForeignKey(Hero.id, ondelete="CASCADE"), nullable=True)

    name: Mapped[enums.LogStatsName] = mapped_column(Enum(enums.LogStatsName))
    value: Mapped[float] = mapped_column(Float())


# Materialized view holding precomputed global per-(hero, stat) records: the
# best value across all players (+ metadata) and the global per-10min average.
# Created and refreshed out-of-band — see migration ``herostatmv01`` and
# ``app-service/src/services/hero_stats_refresh.py`` (app-worker). This is a
# lightweight TableClause for typed reads ONLY; it is deliberately NOT a Base
# model so alembic autogenerate never tries to manage it as a real table.
# ``name`` carries the Enum type so ``.in_(stats)`` binds the stored member
# names and results come back as ``LogStatsName``; ``metadata`` (JSONB) is
# deserialized to a dict by the asyncpg dialect.
mv_hero_global_stats = table(
    "mv_hero_global_stats",
    column("name", Enum(enums.LogStatsName)),
    column("hero_id", BigInteger),
    column("best_value", Float),
    column("avg", Float),
    column("metadata", JSONB),
    schema="matches",
)


class MatchKillFeed(db.TimeStampIntegerMixin):
    __tablename__ = "kill_feed"
    __table_args__ = (
        # FK indexes created CONCURRENTLY by perfidx03 (declared here so the
        # model matches the DB and autogenerate doesn't drift).
        Index("ix_matches_kill_feed_killer_hero_id", "killer_hero_id"),
        Index("ix_matches_kill_feed_killer_team_id", "killer_team_id"),
        Index("ix_matches_kill_feed_victim_team_id", "victim_team_id"),
        Index("ix_matches_kill_feed_victim_hero_id", "victim_hero_id"),
        {"schema": "matches"},
    )

    match_id: Mapped[int] = mapped_column(ForeignKey(Match.id, ondelete="CASCADE"), index=True)
    time: Mapped[float] = mapped_column(Float())
    round: Mapped[int] = mapped_column(Integer())
    fight: Mapped[int] = mapped_column(Integer())
    ability: Mapped[enums.AbilityEvent | None] = mapped_column(Enum(enums.AbilityEvent), nullable=True)
    killer_id: Mapped[int] = mapped_column(ForeignKey(User.id, ondelete="CASCADE"), index=True)
    killer_hero_id: Mapped[int] = mapped_column(ForeignKey(Hero.id, ondelete="CASCADE"))
    killer_team_id: Mapped[int] = mapped_column(ForeignKey(Team.id, ondelete="CASCADE"))
    victim_id: Mapped[int] = mapped_column(ForeignKey(User.id, ondelete="CASCADE"), index=True)
    victim_team_id: Mapped[int] = mapped_column(ForeignKey(Team.id, ondelete="CASCADE"))
    victim_hero_id: Mapped[int] = mapped_column(ForeignKey(Hero.id, ondelete="CASCADE"))
    damage: Mapped[float] = mapped_column(Float())
    is_critical_hit: Mapped[bool] = mapped_column(Boolean())
    is_environmental: Mapped[bool] = mapped_column(Boolean())


class MatchEvent(db.TimeStampIntegerMixin):
    __tablename__ = "event"
    __table_args__ = (
        # FK indexes created CONCURRENTLY by perfidx03.
        Index("ix_matches_assists_hero_id", "hero_id"),
        Index("ix_matches_assists_related_team_id", "related_team_id"),
        Index("ix_matches_assists_related_user_id", "related_user_id"),
        Index("ix_matches_assists_related_hero_id", "related_hero_id"),
        {"schema": "matches"},
    )

    match_id: Mapped[int] = mapped_column(ForeignKey(Match.id, ondelete="CASCADE"), index=True)
    time: Mapped[float] = mapped_column(Float())
    round: Mapped[int] = mapped_column(Integer())
    team_id: Mapped[int] = mapped_column(ForeignKey(Team.id, ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey(User.id, ondelete="CASCADE"), index=True)
    hero_id: Mapped[int | None] = mapped_column(ForeignKey(Hero.id, ondelete="CASCADE"), nullable=True)
    related_team_id: Mapped[int | None] = mapped_column(ForeignKey(Team.id, ondelete="CASCADE"), nullable=True)
    related_user_id: Mapped[int | None] = mapped_column(ForeignKey(User.id, ondelete="CASCADE"), nullable=True)
    related_hero_id: Mapped[int | None] = mapped_column(ForeignKey(Hero.id, ondelete="CASCADE"), nullable=True)
    name: Mapped[enums.MatchEvent] = mapped_column(Enum(enums.MatchEvent))
