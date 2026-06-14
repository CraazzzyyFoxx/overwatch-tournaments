from sqlalchemy import Boolean, Enum, Float, ForeignKey, Index, Integer, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db, enums
from shared.models import Team, Encounter, Map, User, Hero

__all__ = (
    "Match",
    "MatchStatistics",
    "MatchKillFeed",
    "MatchEvent",
)


class Match(db.TimeStampIntegerMixin):
    __tablename__ = "match"
    __table_args__ = ({"schema": "matches"},)

    home_team_id: Mapped[int] = mapped_column(
        ForeignKey(Team.id, ondelete="CASCADE"), index=True
    )
    away_team_id: Mapped[int] = mapped_column(
        ForeignKey(Team.id, ondelete="CASCADE"), index=True
    )
    home_score: Mapped[int] = mapped_column(Integer())
    away_score: Mapped[int] = mapped_column(Integer())
    time: Mapped[float] = mapped_column(Float())
    log_name: Mapped[str] = mapped_column()
    code: Mapped[str | None] = mapped_column(nullable=True)

    encounter_id: Mapped[int] = mapped_column(
        ForeignKey(Encounter.id, ondelete="CASCADE"), index=True
    )
    map_id: Mapped[int] = mapped_column(
        ForeignKey("overwatch.map.id", ondelete="CASCADE"), index=True
    )

    home_team: Mapped["Team"] = relationship(foreign_keys=[home_team_id])
    away_team: Mapped["Team"] = relationship(foreign_keys=[away_team_id])
    encounter: Mapped["Encounter"] = relationship(back_populates="matches")
    map: Mapped["Map"] = relationship()


class MatchStatistics(db.TimeStampIntegerMixin):
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
        {"schema": "matches"},
    )

    match_id: Mapped[int] = mapped_column(
        ForeignKey(Match.id, ondelete="CASCADE"), index=True
    )
    round: Mapped[int] = mapped_column(Integer(), index=True)
    team_id: Mapped[int] = mapped_column(
        ForeignKey(Team.id, ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey(User.id, ondelete="CASCADE"), index=True
    )
    hero_id: Mapped[int | None] = mapped_column(
        ForeignKey(Hero.id, ondelete="CASCADE"), nullable=True, index=True
    )

    name: Mapped[enums.LogStatsName] = mapped_column(
        Enum(enums.LogStatsName), index=True
    )
    value: Mapped[float] = mapped_column(Float())


class MatchKillFeed(db.TimeStampIntegerMixin):
    __tablename__ = "kill_feed"
    __table_args__ = ({"schema": "matches"},)

    match_id: Mapped[int] = mapped_column(
        ForeignKey(Match.id, ondelete="CASCADE"), index=True
    )
    time: Mapped[float] = mapped_column(Float())
    round: Mapped[int] = mapped_column(Integer())
    fight: Mapped[int] = mapped_column(Integer())
    ability: Mapped[enums.AbilityEvent | None] = mapped_column(
        Enum(enums.AbilityEvent), nullable=True
    )
    killer_id: Mapped[int] = mapped_column(
        ForeignKey(User.id, ondelete="CASCADE"), index=True
    )
    killer_hero_id: Mapped[int] = mapped_column(
        ForeignKey(Hero.id, ondelete="CASCADE")
    )
    killer_team_id: Mapped[int] = mapped_column(
        ForeignKey(Team.id, ondelete="CASCADE")
    )
    victim_id: Mapped[int] = mapped_column(
        ForeignKey(User.id, ondelete="CASCADE"), index=True
    )
    victim_team_id: Mapped[int] = mapped_column(
        ForeignKey(Team.id, ondelete="CASCADE")
    )
    victim_hero_id: Mapped[int] = mapped_column(
        ForeignKey(Hero.id, ondelete="CASCADE")
    )
    damage: Mapped[float] = mapped_column(Float())
    is_critical_hit: Mapped[bool] = mapped_column(Boolean())
    is_environmental: Mapped[bool] = mapped_column(Boolean())


class MatchEvent(db.TimeStampIntegerMixin):
    __tablename__ = "assists"
    __table_args__ = ({"schema": "matches"},)

    match_id: Mapped[int] = mapped_column(
        ForeignKey(Match.id, ondelete="CASCADE"), index=True
    )
    time: Mapped[float] = mapped_column(Float())
    round: Mapped[int] = mapped_column(Integer())
    team_id: Mapped[int] = mapped_column(
        ForeignKey(Team.id, ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey(User.id, ondelete="CASCADE"), index=True
    )
    hero_id: Mapped[int | None] = mapped_column(
        ForeignKey(Hero.id, ondelete="CASCADE"), nullable=True
    )
    related_team_id: Mapped[int | None] = mapped_column(
        ForeignKey(Team.id, ondelete="CASCADE"), nullable=True
    )
    related_user_id: Mapped[int | None] = mapped_column(
        ForeignKey(User.id, ondelete="CASCADE"), nullable=True
    )
    related_hero_id: Mapped[int | None] = mapped_column(
        ForeignKey(Hero.id, ondelete="CASCADE"), nullable=True
    )
    name: Mapped[enums.MatchEvent] = mapped_column(Enum(enums.MatchEvent))
