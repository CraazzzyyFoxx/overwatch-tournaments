import typing

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    and_,
    cast,
    func,
    select,
    text,
)
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, column_property, mapped_column, relationship
from sqlalchemy.sql.elements import ColumnElement

from shared.core import db
from shared.models.identity.user import User
from shared.models.tournament.player_role import PlayerRole, rated_role_code
from shared.models.tournament.tournament import Tournament
from shared.schemas.role import RoleRef

if typing.TYPE_CHECKING:
    from shared.models.catalog.role import CatalogRole
    from shared.models.tenancy.workspace import WorkspaceMember
    from shared.models.tournament.standings import Standing

__all__ = ("Team", "Player")


class Team(db.TimeStampIntegerMixin):
    __tablename__ = "team"
    __table_args__ = (
        # Target of ``fk_team_source``: a participation names a team of its own
        # tournament, and the database checks it.
        UniqueConstraint("id", "tournament_id", name="uq_team_id_tournament"),
        {"schema": "tournament"},
    )

    balancer_name: Mapped[str] = mapped_column(String())
    name: Mapped[str] = mapped_column(String())
    #: Public S3 URL of the team's uploaded image, or NULL when it has none.
    #: Readers render the image only when it is set — there is no placeholder.
    image_url: Mapped[str | None] = mapped_column(String(), nullable=True)

    if typing.TYPE_CHECKING:
        # Computed roster aggregates over non-substitute players; mapped via
        # ``column_property`` after ``Player`` is defined (see module tail).
        avg_sr: Mapped[float]
        total_sr: Mapped[int]

    captain_id: Mapped[int | None] = mapped_column(
        ForeignKey("players.user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    tournament_id: Mapped[int] = mapped_column(ForeignKey(Tournament.id, ondelete="CASCADE"), index=True)
    #: The formation node that made the team; NULL is a tournament-wide team (spec §4.6).
    formation_node_id: Mapped[int | None] = mapped_column(
        ForeignKey("tournament.flow_node.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    tournament: Mapped[Tournament] = relationship()

    players: Mapped[list[Player]] = relationship(
        back_populates="team",
        passive_deletes=True,
    )
    captain: Mapped[User | None] = relationship()
    standings: Mapped[list[Standing]] = relationship(passive_deletes=True)


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
        # Self-referencing FK (ondelete=SET NULL); index created CONCURRENTLY
        # by dbarch01.
        Index("ix_player_related_player_id", "related_player_id"),
        {"schema": "tournament"},
    )

    name: Mapped[str] = mapped_column(String())
    # NULL = rank not specified (e.g. 1v1 duels); a specified rank is >= 1.
    rank: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    is_substitution: Mapped[bool] = mapped_column(Boolean(), server_default="false")
    related_player_id: Mapped[int | None] = mapped_column(
        ForeignKey("tournament.player.id", ondelete="SET NULL"), nullable=True
    )
    tournament_id: Mapped[int] = mapped_column(ForeignKey(Tournament.id, ondelete="CASCADE"), index=True)
    #: The formation node of the player's team (same value as ``Team.formation_node_id``); NULL is tournament-wide.
    formation_node_id: Mapped[int | None] = mapped_column(
        ForeignKey("tournament.flow_node.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    is_newcomer: Mapped[bool] = mapped_column(Boolean(), server_default="false")
    is_newcomer_role: Mapped[bool] = mapped_column(Boolean(), server_default="false")

    tournament: Mapped[Tournament] = relationship()
    # Contract step of the workspace-anchoring migration (iwrefac07): ``user_id`` has
    # been dropped and this column is now the sole, NOT NULL anchor for a roster row's
    # identity. ``workspace_member`` lives in the public schema.
    workspace_member_id: Mapped[int] = mapped_column(ForeignKey("workspace_member.id", ondelete="CASCADE"))
    workspace_member: Mapped[WorkspaceMember] = relationship()
    team_id: Mapped[int] = mapped_column(ForeignKey(Team.id, ondelete="CASCADE"))
    team: Mapped[Team] = relationship(back_populates="players")

    #: One leaf per dimension.
    assignments: Mapped[list[PlayerRole]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def _rated_leaf(self) -> CatalogRole | None:
        return next((a.role for a in self.assignments if a.role.dimension.rated), None)

    @hybrid_property
    def role(self) -> str | None:
        """Top-level role code on the rated dimension."""
        leaf = self._rated_leaf
        if leaf is None:
            return None
        return leaf.parent.code if leaf.parent is not None else leaf.code

    @role.inplace.expression
    @classmethod
    def _role_expression(cls) -> ColumnElement[str | None]:
        return rated_role_code(cls.id, top=True).correlate(cls).label("role")  # type: ignore[attr-defined]

    @hybrid_property
    def sub_role(self) -> str | None:
        """The workspace sub-role's leaf code, or None for a top-level assignment."""
        leaf = self._rated_leaf
        return leaf.code if leaf is not None and leaf.parent is not None else None

    @sub_role.inplace.expression
    @classmethod
    def _sub_role_expression(cls) -> ColumnElement[str | None]:
        return rated_role_code(cls.id, top=False).correlate(cls).label("sub_role")  # type: ignore[attr-defined]

    @property
    def role_ref(self) -> RoleRef | None:
        leaf = self._rated_leaf
        return (
            None
            if leaf is None
            else RoleRef(
                dimension=leaf.dimension.code, role=leaf.code, parent=None if leaf.parent is None else leaf.parent.code
            )
        )

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
