from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db

if TYPE_CHECKING:
    from shared.models.identity.auth_user import AuthUser
    from shared.models.tenancy.workspace import Workspace
    from shared.models.tournament.tournament import Tournament

__all__ = (
    "BalancerBalance",
    "BalancerBalanceVariant",
    "BalancerTeam",
    "BalancerTeamSlot",
    "BalancerTournamentConfig",
    "UserBalancerConfig",
    "WorkspaceBalancerConfig",
)


class BalancerTournamentConfig(db.TimeStampIntegerMixin):
    __tablename__ = "tournament_config"
    __table_args__ = (
        UniqueConstraint("tournament_id", name="uq_balancer_tournament_config_tournament"),
        {"schema": "balancer"},
    )

    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournament.tournament.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"), index=True)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, server_default="{}", default=dict)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True)

    tournament: Mapped[Tournament] = relationship()
    workspace: Mapped[Workspace] = relationship()
    updater: Mapped[AuthUser | None] = relationship()


class WorkspaceBalancerConfig(db.TimeStampIntegerMixin):
    __tablename__ = "workspace_config"
    __table_args__ = (
        UniqueConstraint("workspace_id", name="uq_balancer_workspace_config_workspace"),
        {"schema": "balancer"},
    )

    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"), index=True)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, server_default="{}", default=dict)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True)


class UserBalancerConfig(db.TimeStampIntegerMixin):
    """One account's own mix settings, applied to every mix it hosts.

    These used to sit on the mix (``custom_game.*``), which made a host re-enter
    the same preferences every pickup session -- they describe how this person
    runs their mixes, not what happened in one lobby, so they belong to the
    account. ``config_json`` is exactly the solver-override blob the mix engine
    reads (``mix_comfort_tilt``, ``mix_role_weights``, ``max_result_variants``),
    so it reaches the solver untouched; a knob the user never set is an absent
    key, never an explicit null, and an untouched account stores ``{}``.
    """

    __tablename__ = "user_config"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_balancer_user_config_user"),
        {"schema": "balancer"},
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("auth.user.id", ondelete="CASCADE"), index=True)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}", default=dict)
    # Columns of their own, deliberately NOT keys inside ``config_json``: that
    # blob is handed to the solver verbatim as overrides, and neither of these
    # is one. The roster shape is the shape of the thing being built -- the
    # runtime applies it *after* the overrides so a saved config can never
    # contradict it (``_prepare_balance_context``) -- and the points knob never
    # reaches the solver at all: it moves the host's rank book once a match is
    # recorded. Folding either into the blob would smuggle a non-override key
    # into the engine's input.
    #
    # Normalized on write (``normalize_roster_slots``), so the stored map can
    # never hold a zero count; NULL means "no shape of my own", which falls
    # through to the workspace default and then the built-in Overwatch 5v5.
    role_slots_json: Mapped[dict[str, int] | None] = mapped_column(JSONB, nullable=True)
    # How far a decided match moves both teams' ranks in this host's own book.
    # NULL (the wire's ``0`` or ``null``) means recording a match touches no
    # ranks at all.
    points_per_win: Mapped[int | None] = mapped_column(Integer(), nullable=True)


class BalancerBalance(db.TimeStampIntegerMixin):
    __tablename__ = "balance"
    __table_args__ = (
        UniqueConstraint("tournament_id", name="uq_balancer_balance_tournament"),
        {"schema": "balancer"},
    )

    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournament.tournament.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[int | None] = mapped_column(
        ForeignKey("workspace.id", ondelete="SET NULL"), nullable=True, index=True
    )
    algorithm: Mapped[str | None] = mapped_column(String(32), nullable=True)
    division_grid_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    division_scope: Mapped[str | None] = mapped_column(String(32), nullable=True)
    config_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    saved_by: Mapped[int | None] = mapped_column(ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True)
    saved_at: Mapped[db.DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    exported_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    export_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    export_error: Mapped[str | None] = mapped_column(Text(), nullable=True)

    tournament: Mapped[Tournament] = relationship()
    workspace: Mapped[Workspace | None] = relationship()
    author: Mapped[AuthUser | None] = relationship()
    teams: Mapped[list[BalancerTeam]] = relationship(back_populates="balance")
    variants: Mapped[list[BalancerBalanceVariant]] = relationship(back_populates="balance")


class BalancerTeam(db.TimeStampIntegerMixin):
    __tablename__ = "team"
    __table_args__ = ({"schema": "balancer"},)

    balance_id: Mapped[int] = mapped_column(ForeignKey("balancer.balance.id", ondelete="CASCADE"), index=True)
    variant_id: Mapped[int | None] = mapped_column(
        ForeignKey("balancer.balance_variant.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    exported_team_id: Mapped[int | None] = mapped_column(
        ForeignKey("tournament.team.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255))
    balancer_name: Mapped[str] = mapped_column(String(255))
    captain_battle_tag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avg_sr: Mapped[float] = mapped_column(Float())
    total_sr: Mapped[int] = mapped_column(Integer())
    sort_order: Mapped[int] = mapped_column(Integer(), nullable=False, default=0, server_default="0")

    balance: Mapped[BalancerBalance] = relationship(back_populates="teams")
    variant: Mapped[BalancerBalanceVariant | None] = relationship()
    slots: Mapped[list[BalancerTeamSlot]] = relationship(back_populates="team")


class BalancerBalanceVariant(db.TimeStampIntegerMixin):
    """One solution variant produced by a balancer algorithm run."""

    __tablename__ = "balance_variant"
    __table_args__ = (
        UniqueConstraint("balance_id", "variant_number", name="uq_balancer_balance_variant"),
        {"schema": "balancer"},
    )

    balance_id: Mapped[int] = mapped_column(ForeignKey("balancer.balance.id", ondelete="CASCADE"), index=True)
    variant_number: Mapped[int] = mapped_column(Integer(), nullable=False)
    algorithm: Mapped[str] = mapped_column(String(32), nullable=False)
    objective_score: Mapped[float | None] = mapped_column(Float(), nullable=True)
    statistics_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    is_selected: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)

    balance: Mapped[BalancerBalance] = relationship(back_populates="variants")
    teams: Mapped[list[BalancerTeam]] = relationship(
        primaryjoin="BalancerTeam.variant_id == BalancerBalanceVariant.id",
        viewonly=True,
    )


class BalancerTeamSlot(db.TimeStampIntegerMixin):
    """One player's slot in a balanced team (replaces roster_json)."""

    __tablename__ = "team_slot"
    __table_args__ = ({"schema": "balancer"},)

    team_id: Mapped[int] = mapped_column(ForeignKey("balancer.team.id", ondelete="CASCADE"), index=True)
    # Durable identity link to the balanced player. Registrations are mutable and
    # tournament-scoped, so a saved historical balance keeps the normalized battle
    # tag rather than a hard FK; resolve to a registration at query time if needed.
    battle_tag_normalized: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    assigned_rank: Mapped[int] = mapped_column(Integer(), nullable=False)
    discomfort: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0", default=0)
    is_captain: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false", default=False)
    sort_order: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0", default=0)

    team: Mapped[BalancerTeam] = relationship(back_populates="slots")
