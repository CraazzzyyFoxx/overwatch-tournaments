import typing
from datetime import datetime

from sqlalchemy import Boolean, Enum, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db, enums
from shared.models.tenancy.workspace import Workspace

if typing.TYPE_CHECKING:
    from shared.models.division_grid.division_grid import DivisionGridVersion
    from shared.models.tournament.stage import Stage
    from shared.models.tournament.standings import Standing


__all__ = (
    "Tournament",
    "TournamentGroup",
)


TOURNAMENT_STATUS_ENUM = Enum(
    enums.TournamentStatus,
    values_callable=lambda e: [x.value for x in e],
    name="tournamentstatus",
    schema="tournament",
    create_type=False,
)


class Tournament(db.TimeStampIntegerMixin):
    __tablename__ = "tournament"
    __table_args__ = ({"schema": "tournament"},)

    workspace_id: Mapped[int] = mapped_column(ForeignKey(Workspace.id, ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer(), nullable=True)
    name: Mapped[str] = mapped_column(String())
    description: Mapped[str | None] = mapped_column(String(), nullable=True)
    is_league: Mapped[bool] = mapped_column(Boolean(), default=False, server_default="false", nullable=False)
    is_finished: Mapped[bool] = mapped_column(Boolean(), default=False, server_default="false", nullable=False)
    # How teams are formed for this tournament: "balancer" (auto-balance) or
    # "draft" (live draft). Stored as text (not a PG enum) to stay flexible.
    team_formation: Mapped[str] = mapped_column(String(), default="balancer", server_default="balancer", nullable=False)
    status: Mapped[enums.TournamentStatus] = mapped_column(
        TOURNAMENT_STATUS_ENUM,
        default=enums.TournamentStatus.DRAFT,
        server_default=enums.TournamentStatus.DRAFT.value,
        nullable=False,
    )
    start_date: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True), nullable=True)
    end_date: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True), nullable=True)
    registration_opens_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True), nullable=True)
    registration_closes_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True), nullable=True)
    check_in_opens_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True), nullable=True)
    check_in_closes_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True), nullable=True)
    win_points: Mapped[float] = mapped_column(Float(), default=1.0, server_default="1.0", nullable=False)
    draw_points: Mapped[float] = mapped_column(Float(), default=0.5, server_default="0.5", nullable=False)
    loss_points: Mapped[float] = mapped_column(Float(), default=0.0, server_default="0.0", nullable=False)
    division_grid_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("division_grid_version.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    workspace: Mapped[Workspace] = relationship()
    division_grid_version: Mapped["DivisionGridVersion | None"] = relationship(
        foreign_keys=[division_grid_version_id],
        lazy="selectin",
    )
    groups: Mapped[list["TournamentGroup"]] = relationship(uselist=True, passive_deletes=True)
    stages: Mapped[list["Stage"]] = relationship(uselist=True, passive_deletes=True)
    standings: Mapped[list["Standing"]] = relationship(uselist=True)


class TournamentGroup(db.TimeStampIntegerMixin):
    """Legacy model — being replaced by Stage + StageItem.

    Kept during migration. New code should use Stage/StageItem instead.
    The stage_id FK links this group to its corresponding Stage record.
    """

    __tablename__ = "group"
    __table_args__ = ({"schema": "tournament"},)

    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournament.tournament.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String())
    description: Mapped[str | None] = mapped_column(String(), nullable=True)
    is_groups: Mapped[bool] = mapped_column(Boolean(), default=False)
    # DEPRECATED (Challonge consolidation): superseded by tournament.challonge_source
    # (source_type='group'/'playoff', scoped via stage_id). Kept until dbarch04b is applied.
    challonge_id: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    challonge_slug: Mapped[str | None] = mapped_column(String(), nullable=True)
    stage_id: Mapped[int | None] = mapped_column(ForeignKey("tournament.stage.id", ondelete="SET NULL"), nullable=True)

    tournament: Mapped[Tournament] = relationship(back_populates="groups")
    stage: Mapped["Stage | None"] = relationship(foreign_keys=[stage_id])
