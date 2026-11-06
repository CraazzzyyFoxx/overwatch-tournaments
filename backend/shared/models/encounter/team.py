"""Participation: one seat of one encounter, and the roster behind it.

A participation is append-only. Replacing an occupant writes a NEW row and sets
the old one ``active = false``; nothing ever flips it back, and nothing ever
deletes it on its own -- the games it played, the claims it filed and the
journal all point here, which is what makes "who played this" answerable after
a slot changes hands. ``team_id`` is the *source* tournament team and may go
NULL when that team is deleted; ``name`` is the snapshot that survives it.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    select,
    text,
)
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import ColumnElement

from shared.core import db
from shared.models.catalog.role import CatalogRole, RoleDimension
from shared.models.encounter.encounter import Encounter

__all__ = ("EncounterTeam", "EncounterTeamMember", "EncounterTeamMemberRole")


class EncounterTeam(db.TimeStampIntegerMixin):
    __tablename__ = "team"
    __table_args__ = (
        # One occupant per slot and one participation per source team, among the
        # ACTIVE rows only -- the replaced ones stay as history.
        Index("uq_team_active_slot", "encounter_id", "slot", unique=True, postgresql_where=text("active")),
        Index(
            "uq_team_active_source",
            "encounter_id",
            "team_id",
            unique=True,
            postgresql_where=text("active AND team_id IS NOT NULL"),
        ),
        #: "every encounter of this team", in place of the old home/away indexes.
        Index("ix_team_team_id", "team_id"),
        UniqueConstraint("id", "encounter_id", name="uq_team_id_encounter"),
        # Target of ``fk_team_member_team``: the roster's ``active`` rides along
        # with this row's through ON UPDATE CASCADE.
        UniqueConstraint("id", "encounter_id", "active", name="uq_team_id_encounter_active"),
        ForeignKeyConstraint(
            ["encounter_id", "tournament_id"],
            ["encounter.encounter.id", "encounter.encounter.tournament_id"],
            ondelete="CASCADE",
            name="fk_team_encounter_tournament",
            deferrable=True,
            initially="IMMEDIATE",
        ),
        # Deleting the source team empties the pointer and keeps the
        # participation, its games and its roster.
        ForeignKeyConstraint(
            ["team_id", "tournament_id"],
            ["tournament.team.id", "tournament.team.tournament_id"],
            ondelete="SET NULL (team_id)",
            name="fk_team_source",
            deferrable=True,
            initially="IMMEDIATE",
        ),
        CheckConstraint("slot >= 1", name="ck_team_slot"),
        CheckConstraint("placement IS NULL OR placement >= 1", name="ck_team_placement"),
        CheckConstraint("score NOT IN ('NaN', 'Infinity', '-Infinity')", name="ck_team_score_finite"),
        {"schema": "encounter"},
    )

    encounter_id: Mapped[int] = mapped_column(ForeignKey(Encounter.id, ondelete="CASCADE"))
    #: Copy of the encounter's owner, so the source team can be checked against
    #: the same tournament (V2: NULL for mixes and scrims).
    tournament_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    #: ``1..encounter.slot_count``; the participation writer checks the range.
    slot: Mapped[int] = mapped_column(Integer())
    #: The source ``tournament.team``; NULL when there is no roster behind the
    #: seat, or when the source team has been deleted.
    team_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    seed: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean(), default=True, server_default="true")
    #: The materialized result inside the encounter: under the
    #: ``wins`` preset this is the number of games won.
    score: Mapped[float] = mapped_column(Float(), default=0.0, server_default="0")
    #: Place inside the encounter; NULL while there is no result.
    placement: Mapped[int | None] = mapped_column(Integer(), nullable=True)

    encounter: Mapped[Encounter] = relationship(back_populates="teams", foreign_keys=[encounter_id])


class EncounterTeamMember(db.TimeStampIntegerMixin):
    """The roster of one participation, snapshotted.

    ``active`` is a copy of the participation's, carried by the composite FK's
    ``ON UPDATE CASCADE`` -- that is what lets a partial unique index say "one
    active seat per member per encounter" without a trigger (A2).
    """

    __tablename__ = "team_member"
    __table_args__ = (
        Index(
            "uq_team_member_active_member",
            "encounter_id",
            "workspace_member_id",
            unique=True,
            postgresql_where=text("active"),
        ),
        Index("ix_team_member_workspace_member_id", "workspace_member_id"),
        UniqueConstraint("encounter_team_id", "workspace_member_id", name="uq_team_member_member"),
        ForeignKeyConstraint(
            ["encounter_team_id", "encounter_id", "active"],
            ["encounter.team.id", "encounter.team.encounter_id", "encounter.team.active"],
            onupdate="CASCADE",
            name="fk_team_member_team",
            deferrable=True,
            initially="DEFERRED",
        ),
        {"schema": "encounter"},
    )

    encounter_id: Mapped[int] = mapped_column(ForeignKey(Encounter.id, ondelete="CASCADE"))
    encounter_team_id: Mapped[int] = mapped_column(BigInteger())
    active: Mapped[bool] = mapped_column(Boolean())
    # NO ACTION, deferred: the workspace member is the anchor a roster snapshot
    # is written against and must not be deleted out from under it --
    # ``remove_member`` sets ``removed_at`` instead. Deferred so deleting the
    # whole workspace, which removes both sides at once, still works.
    workspace_member_id: Mapped[int] = mapped_column(
        ForeignKey("workspace_member.id", name="fk_team_member_workspace_member", deferrable=True, initially="DEFERRED")
    )
    display_name_snapshot: Mapped[str] = mapped_column(String(255))
    #: Rank snapshot taken on the member's rating role.
    rank: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    is_substitute: Mapped[bool] = mapped_column(Boolean(), default=False, server_default="false")
    #: Captained the team that took this seat, as it stood when the seat was filled: the lineup captain of a mix
    #: match, ``tournament.team.captain_id`` of a tournament seat. A moved seat carries it with its snapshot.
    is_captain: Mapped[bool] = mapped_column(Boolean(), default=False, server_default="false")


class EncounterTeamMemberRole(db.Base):
    """A roster member's leaf catalog role; snapshots read its dimension and leaf codes."""

    __tablename__ = "team_member_role"
    __table_args__ = (
        ForeignKeyConstraint(
            ["role_id", "dimension_id"],
            ["catalog.role.id", "catalog.role.dimension_id"],
            name="fk_team_member_role_role",
            deferrable=True,
            initially="DEFERRED",
        ),
        {"schema": "encounter"},
    )

    team_member_id: Mapped[int] = mapped_column(
        ForeignKey(EncounterTeamMember.id, ondelete="CASCADE", name="fk_team_member_role_member"), primary_key=True
    )
    dimension_id: Mapped[int] = mapped_column(BigInteger())
    role_id: Mapped[int] = mapped_column(BigInteger(), primary_key=True, autoincrement=False, index=True)

    catalog_role: Mapped[CatalogRole] = relationship(
        primaryjoin="foreign(EncounterTeamMemberRole.role_id) == CatalogRole.id", foreign_keys=[role_id], lazy="joined"
    )

    @hybrid_property
    def dimension(self) -> str:
        return self.catalog_role.dimension.code

    @dimension.inplace.expression
    @classmethod
    def _dimension_expression(cls) -> ColumnElement[str]:
        return (
            select(RoleDimension.code)
            .where(RoleDimension.id == cls.dimension_id)
            .correlate(cls)
            .scalar_subquery()
            .label("dimension")
        )

    @hybrid_property
    def role(self) -> str:
        return self.catalog_role.code

    @role.inplace.expression
    @classmethod
    def _role_expression(cls) -> ColumnElement[str]:
        return (
            select(CatalogRole.code).where(CatalogRole.id == cls.role_id).correlate(cls).scalar_subquery().label("role")
        )
