"""add live draft schema (balancer.draft_session/team/player/pick)

Tables backing the Live Draft feature. All live in the ``balancer`` schema
alongside the other balancer tables. Enum-like fields are plain VARCHAR
(matching the balancer-schema convention). The draft_session <-> draft_pick
circular FK (current_pick_id) is added last via ALTER.

Revision ID: draft0001
Revises: fetchlog0001
Create Date: 2026-06-04 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "draft0001"
down_revision: str | Sequence[str] | None = "fetchlog0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "draft_session",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tournament_id", sa.BigInteger(), nullable=False),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="setup", nullable=False),
        sa.Column("format", sa.String(length=16), server_default="snake", nullable=False),
        sa.Column("rounds", sa.Integer(), server_default="4", nullable=False),
        sa.Column("pick_time_seconds", sa.Integer(), server_default="45", nullable=False),
        sa.Column("team_size", sa.Integer(), server_default="5", nullable=False),
        # FK to draft_pick added at the end (circular dependency).
        sa.Column("current_pick_id", sa.BigInteger(), nullable=True),
        sa.Column("pool_source", sa.String(length=32), server_default="balancer_balance", nullable=False),
        sa.Column("source_balance_id", sa.BigInteger(), nullable=True),
        sa.Column("autopick_strategy", sa.String(length=16), server_default="best_fit", nullable=False),
        sa.Column("allow_admin_override", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("exported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("export_status", sa.String(length=32), nullable=True),
        sa.Column("settings_json", sa.JSON(), server_default="{}", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournament.tournament.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_balance_id"], ["balancer.balance.id"], ondelete="SET NULL"),
        schema="balancer",
    )
    op.create_index(
        op.f("ix_balancer_draft_session_workspace_id"),
        "draft_session",
        ["workspace_id"],
        schema="balancer",
    )
    op.create_index(
        op.f("ix_balancer_draft_session_source_balance_id"),
        "draft_session",
        ["source_balance_id"],
        schema="balancer",
    )
    op.create_index(
        "ix_draft_session_tournament_status",
        "draft_session",
        ["tournament_id", "status"],
        schema="balancer",
    )
    op.create_index(
        "ix_draft_session_status_created",
        "draft_session",
        ["status", "created_at"],
        schema="balancer",
    )
    op.create_index(
        "uq_draft_session_active_tournament",
        "draft_session",
        ["tournament_id"],
        unique=True,
        schema="balancer",
        postgresql_where=sa.text("status IN ('setup','ready','live','paused')"),
    )

    op.create_table(
        "draft_team",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("session_id", sa.BigInteger(), nullable=False),
        sa.Column("captain_user_id", sa.BigInteger(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("draft_position", sa.Integer(), nullable=False),
        sa.Column("exported_team_id", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["session_id"], ["balancer.draft_session.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["captain_user_id"], ["players.user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["exported_team_id"], ["tournament.team.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("session_id", "draft_position", name="uq_draft_team_session_position"),
        schema="balancer",
    )
    op.create_index(op.f("ix_balancer_draft_team_session_id"), "draft_team", ["session_id"], schema="balancer")
    op.create_index(
        op.f("ix_balancer_draft_team_captain_user_id"), "draft_team", ["captain_user_id"], schema="balancer"
    )
    op.create_index(
        op.f("ix_balancer_draft_team_exported_team_id"), "draft_team", ["exported_team_id"], schema="balancer"
    )

    op.create_table(
        "draft_player",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("session_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("battle_tag", sa.String(length=255), nullable=True),
        sa.Column("primary_role", sa.String(length=16), nullable=False),
        sa.Column("sub_role", sa.String(length=128), nullable=True),
        sa.Column("is_flex", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("division_number", sa.Integer(), nullable=True),
        sa.Column("rank_value", sa.Integer(), nullable=True),
        sa.Column("source_balancer_player_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="available", nullable=False),
        sa.Column("is_captain", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("drafted_by_team_id", sa.BigInteger(), nullable=True),
        sa.Column("secondary_roles_json", sa.JSON(), nullable=True),
        sa.Column("anomaly_flags", sa.JSON(), server_default="{}", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["session_id"], ["balancer.draft_session.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["players.user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_balancer_player_id"], ["balancer.player.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["drafted_by_team_id"], ["balancer.draft_team.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("session_id", "user_id", name="uq_draft_player_session_user"),
        schema="balancer",
    )
    op.create_index(
        op.f("ix_balancer_draft_player_user_id"), "draft_player", ["user_id"], schema="balancer"
    )
    op.create_index(
        op.f("ix_balancer_draft_player_source_balancer_player_id"),
        "draft_player",
        ["source_balancer_player_id"],
        schema="balancer",
    )
    op.create_index(
        op.f("ix_balancer_draft_player_drafted_by_team_id"),
        "draft_player",
        ["drafted_by_team_id"],
        schema="balancer",
    )
    op.create_index(
        "ix_draft_player_session_status",
        "draft_player",
        ["session_id", "status"],
        schema="balancer",
    )

    op.create_table(
        "draft_pick",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("session_id", sa.BigInteger(), nullable=False),
        sa.Column("overall_no", sa.Integer(), nullable=False),
        sa.Column("round_no", sa.Integer(), nullable=False),
        sa.Column("pick_in_round", sa.Integer(), nullable=False),
        sa.Column("draft_team_id", sa.BigInteger(), nullable=False),
        sa.Column("target_role", sa.String(length=16), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="upcoming", nullable=False),
        sa.Column("picked_player_id", sa.BigInteger(), nullable=True),
        sa.Column("picked_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("is_autopick", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_admin_override", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("clock_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("clock_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("clock_remaining_ms", sa.Integer(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["session_id"], ["balancer.draft_session.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["draft_team_id"], ["balancer.draft_team.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["picked_player_id"], ["balancer.draft_player.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["picked_by_user_id"], ["players.user.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("session_id", "overall_no", name="uq_draft_pick_session_overall"),
        schema="balancer",
    )
    op.create_index(
        op.f("ix_balancer_draft_pick_draft_team_id"), "draft_pick", ["draft_team_id"], schema="balancer"
    )
    op.create_index(
        op.f("ix_balancer_draft_pick_picked_player_id"), "draft_pick", ["picked_player_id"], schema="balancer"
    )
    op.create_index(
        "ix_draft_pick_session_status",
        "draft_pick",
        ["session_id", "status"],
        schema="balancer",
    )

    # Circular FK: draft_session.current_pick_id -> draft_pick.id (added last).
    op.create_foreign_key(
        "fk_draft_session_current_pick",
        "draft_session",
        "draft_pick",
        ["current_pick_id"],
        ["id"],
        source_schema="balancer",
        referent_schema="balancer",
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_draft_session_current_pick", "draft_session", schema="balancer", type_="foreignkey")
    # Dropping the tables cascades their indexes/constraints.
    op.drop_table("draft_pick", schema="balancer")
    op.drop_table("draft_player", schema="balancer")
    op.drop_table("draft_team", schema="balancer")
    op.drop_table("draft_session", schema="balancer")
