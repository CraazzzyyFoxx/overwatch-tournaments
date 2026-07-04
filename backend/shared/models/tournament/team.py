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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db, enums
from shared.models.identity.user import User
from shared.models.tournament.tournament import Tournament

if typing.TYPE_CHECKING:
    from shared.models.tenancy.workspace import WorkspaceMember
    from shared.models.tournament.challonge import ChallongeTeam
    from shared.models.tournament.standings import Standing

__all__ = ("Team", "Player", "PlayerSubRole")


class Team(db.TimeStampIntegerMixin):
    __tablename__ = "team"
    __table_args__ = ({"schema": "tournament"},)

    balancer_name: Mapped[str] = mapped_column(String())
    name: Mapped[str] = mapped_column(String())
    avg_sr: Mapped[float] = mapped_column(Float())
    total_sr: Mapped[int] = mapped_column(Integer())

    captain_id: Mapped[int | None] = mapped_column(
        ForeignKey("players.user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    tournament_id: Mapped[int] = mapped_column(
        ForeignKey(Tournament.id, ondelete="CASCADE"), index=True
    )
    tournament: Mapped[Tournament] = relationship()

    players: Mapped[list["Player"]] = relationship(
        back_populates="team",
        passive_deletes=True,
    )
    captain: Mapped["User | None"] = relationship()
    standings: Mapped[list["Standing"]] = relationship(passive_deletes=True)
    challonge: Mapped[list["ChallongeTeam"]] = relationship(passive_deletes=True)


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
        {"schema": "tournament"},
    )

    name: Mapped[str] = mapped_column(String())
    sub_role: Mapped[str | None] = mapped_column(String(128), nullable=True)
    rank: Mapped[int] = mapped_column(Integer())
    role: Mapped[enums.HeroClass | None] = mapped_column(
        Enum(enums.HeroClass), nullable=True
    )
    is_substitution: Mapped[bool] = mapped_column(Boolean(), server_default="false")
    related_player_id: Mapped[int | None] = mapped_column(
        ForeignKey("tournament.player.id", ondelete="SET NULL"), nullable=True
    )
    tournament_id: Mapped[int] = mapped_column(
        ForeignKey(Tournament.id, ondelete="CASCADE"), index=True
    )
    is_newcomer: Mapped[bool] = mapped_column(Boolean(), server_default="false")
    is_newcomer_role: Mapped[bool] = mapped_column(Boolean(), server_default="false")

    tournament: Mapped[Tournament] = relationship()
    # Contract step of the workspace-anchoring migration (iwrefac07): ``user_id`` has
    # been dropped and this column is now the sole, NOT NULL anchor for a roster row's
    # identity. ``workspace_member`` lives in the public schema.
    workspace_member_id: Mapped[int] = mapped_column(
        ForeignKey("workspace_member.id", ondelete="CASCADE")
    )
    workspace_member: Mapped["WorkspaceMember"] = relationship()
    team_id: Mapped[int] = mapped_column(ForeignKey(Team.id, ondelete="CASCADE"))
    team: Mapped["Team"] = relationship(back_populates="players")

    def __repr__(self):
        return f"<Player name={self.name} role={self.role}>"


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

    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(64))
    slug: Mapped[str] = mapped_column(String(128))
    label: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer(), server_default="0", default=0)
    is_active: Mapped[bool] = mapped_column(
        Boolean(), server_default="true", default=True
    )
