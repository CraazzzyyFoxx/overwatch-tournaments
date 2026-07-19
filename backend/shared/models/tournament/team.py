import typing

from sqlalchemy import (
    Boolean,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    and_,
    cast,
    func,
    select,
    text,
)
from sqlalchemy.orm import Mapped, column_property, mapped_column, relationship

from shared.core import db, enums
from shared.models.identity.user import User
from shared.models.tournament.tournament import Tournament

if typing.TYPE_CHECKING:
    from shared.models.tenancy.workspace import WorkspaceMember
    from shared.models.tournament.standings import Standing

__all__ = ("Team", "Player", "PlayerSubRole")


class Team(db.TimeStampIntegerMixin):
    __tablename__ = "team"
    __table_args__ = ({"schema": "tournament"},)

    balancer_name: Mapped[str] = mapped_column(String())
    name: Mapped[str] = mapped_column(String())

    if typing.TYPE_CHECKING:
        # Computed roster aggregates over non-substitute players; mapped via
        # ``column_property`` after ``Player`` is defined (see module tail).
        avg_sr: Mapped[float]
        total_sr: Mapped[int]

    captain_id: Mapped[int | None] = mapped_column(
        ForeignKey("players.user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    tournament_id: Mapped[int] = mapped_column(ForeignKey(Tournament.id, ondelete="CASCADE"), index=True)
    tournament: Mapped[Tournament] = relationship()

    players: Mapped[list["Player"]] = relationship(
        back_populates="team",
        passive_deletes=True,
    )
    captain: Mapped["User | None"] = relationship()
    standings: Mapped[list["Standing"]] = relationship(passive_deletes=True)


class Player(db.TimeStampIntegerMixin):
    __tablename__ = "player"

    __table_args__ = (
        Index("ix_player_workspace_member_tournament", "workspace_member_id", "tournament_id"),
        Index("ix_player_team_workspace_member", "team_id", "workspace_member_id"),
        Index(
            "ix_player_member_not_sub",
            "workspace_member_id",
            "tournament_id",
            postgresql_where=text("is_substitution = false"),
        ),
        Index("ix_player_tournament_role_sub_role", "tournament_id", "role", "sub_role"),
        # Self-referencing FK (ondelete=SET NULL); index created CONCURRENTLY
        # by dbarch01.
        Index("ix_player_related_player_id", "related_player_id"),
        {"schema": "tournament"},
    )

    name: Mapped[str] = mapped_column(String())
    sub_role: Mapped[str | None] = mapped_column(String(128), nullable=True)
    rank: Mapped[int] = mapped_column(Integer())
    role: Mapped[enums.HeroClass | None] = mapped_column(Enum(enums.HeroClass), nullable=True)
    is_substitution: Mapped[bool] = mapped_column(Boolean(), server_default="false")
    related_player_id: Mapped[int | None] = mapped_column(
        ForeignKey("tournament.player.id", ondelete="SET NULL"), nullable=True
    )
    tournament_id: Mapped[int] = mapped_column(ForeignKey(Tournament.id, ondelete="CASCADE"), index=True)
    is_newcomer: Mapped[bool] = mapped_column(Boolean(), server_default="false")
    is_newcomer_role: Mapped[bool] = mapped_column(Boolean(), server_default="false")

    tournament: Mapped[Tournament] = relationship()
    # Contract step of the workspace-anchoring migration (iwrefac07): ``user_id`` has
    # been dropped and this column is now the sole, NOT NULL anchor for a roster row's
    # identity. ``workspace_member`` lives in the public schema.
    workspace_member_id: Mapped[int] = mapped_column(ForeignKey("workspace_member.id", ondelete="CASCADE"))
    workspace_member: Mapped["WorkspaceMember"] = relationship()
    team_id: Mapped[int] = mapped_column(ForeignKey(Team.id, ondelete="CASCADE"))
    team: Mapped["Team"] = relationship(back_populates="players")

    def __repr__(self):
        return f"<Player name={self.name} role={self.role}>"


# ``avg_sr``/``total_sr`` are computed from the roster (non-substitute players
# only) instead of being stored: substitutes are extra rows linked to the slot
# they cover via ``related_player_id``, so including them would double-count
# replaced slots. The correlated subquery ships in every ``SELECT team`` and is
# usable in SQL expressions (e.g. ``func.avg(Team.avg_sr)``).
_active_roster = and_(Player.team_id == Team.id, Player.is_substitution.is_(False))

Team.avg_sr = column_property(
    select(cast(func.coalesce(func.avg(Player.rank), 0.0), Float()))
    .where(_active_roster)
    .correlate_except(Player)
    .scalar_subquery()
)
Team.total_sr = column_property(
    select(func.coalesce(func.sum(Player.rank), 0)).where(_active_roster).correlate_except(Player).scalar_subquery()
)


class PlayerSubRole(db.TimeStampIntegerMixin):
    __tablename__ = "player_sub_role"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "role",
            "slug",
            name="uq_player_sub_role_workspace_role_slug",
        ),
        Index(
            "ix_player_sub_role_workspace_role_active",
            "workspace_id",
            "role",
            "is_active",
        ),
        Index("ix_player_sub_role_workspace_id", "workspace_id"),
        {"schema": "tournament"},
    )

    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(64))
    slug: Mapped[str] = mapped_column(String(128))
    label: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer(), server_default="0", default=0)
    is_active: Mapped[bool] = mapped_column(Boolean(), server_default="true", default=True)
