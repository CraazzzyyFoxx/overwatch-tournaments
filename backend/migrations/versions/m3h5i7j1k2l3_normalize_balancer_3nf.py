"""normalize_balancer_3nf

Adds normalized tables for the balancer subsystem:
- balancer.player_role_entry (replaces role_entries_json)
- balancer.balance_variant (multi-variant support)
- balancer.team_slot (replaces roster_json)
- balancer.registration_form (custom registration forms)
- balancer.registration (public tournament registration)
- players.external_account (generic external account links)
- analytics.balance_snapshot (balance quality tracking)
- analytics.balance_player_snapshot (per-player balance data)

Also adds new columns to existing tables:
- balancer.balance: workspace_id, algorithm, division_grid_json, division_scope
- balancer.team: variant_id
- balancer.application: registration_id

Revision ID: m3h5i7j1k2l3
Revises: l2g4h6i0j1k2
Create Date: 2026-04-09 23:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "m3h5i7j1k2l3"
down_revision: Union[str, None] = "l2g4h6i0j1k2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # 1. New columns on existing balancer tables
    # -----------------------------------------------------------------------

    # balancer.balance — workspace context, algorithm info, division config
    op.add_column("balance", sa.Column("workspace_id", sa.BigInteger(), nullable=True), schema="balancer")
    op.add_column("balance", sa.Column("algorithm", sa.String(32), nullable=True), schema="balancer")
    op.add_column("balance", sa.Column("division_grid_json", sa.JSON(), nullable=True), schema="balancer")
    op.add_column("balance", sa.Column("division_scope", sa.String(32), nullable=True), schema="balancer")
    op.create_foreign_key(
        "fk_balance_workspace",
        "balance",
        "workspace",
        ["workspace_id"],
        ["id"],
        source_schema="balancer",
        ondelete="SET NULL",
    )
    op.create_index("ix_balancer_balance_workspace_id", "balance", ["workspace_id"], schema="balancer")

    # balancer.team — variant_id
    op.add_column("team", sa.Column("variant_id", sa.BigInteger(), nullable=True), schema="balancer")
    # FK added after balance_variant table is created

    # balancer.application — registration_id
    op.add_column("application", sa.Column("registration_id", sa.BigInteger(), nullable=True), schema="balancer")
    # FK added after registration table is created

    # -----------------------------------------------------------------------
    # 2. balancer.player_role_entry
    # -----------------------------------------------------------------------
    op.create_table(
        "player_role_entry",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("player_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("subtype", sa.String(32), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("rank_value", sa.Integer(), nullable=True),
        sa.Column("division_number", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["player_id"], ["balancer.player.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("player_id", "role", name="uq_balancer_player_role_entry"),
        schema="balancer",
    )
    op.create_index("ix_balancer_player_role_entry_player_id", "player_role_entry", ["player_id"], schema="balancer")
    op.create_index(
        "ix_player_role_entry_role_active", "player_role_entry", ["role", "is_active"], schema="balancer"
    )

    # -----------------------------------------------------------------------
    # 3. balancer.balance_variant
    # -----------------------------------------------------------------------
    op.create_table(
        "balance_variant",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("balance_id", sa.BigInteger(), nullable=False),
        sa.Column("variant_number", sa.Integer(), nullable=False),
        sa.Column("algorithm", sa.String(32), nullable=False),
        sa.Column("objective_score", sa.Float(), nullable=True),
        sa.Column("statistics_json", sa.JSON(), nullable=True),
        sa.Column("is_selected", sa.Boolean(), server_default="false", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["balance_id"], ["balancer.balance.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("balance_id", "variant_number", name="uq_balancer_balance_variant"),
        schema="balancer",
    )
    op.create_index("ix_balancer_balance_variant_balance_id", "balance_variant", ["balance_id"], schema="balancer")

    # Now add FK from team to balance_variant
    op.create_foreign_key(
        "fk_team_variant",
        "team",
        "balance_variant",
        ["variant_id"],
        ["id"],
        source_schema="balancer",
        referent_schema="balancer",
        ondelete="CASCADE",
    )
    op.create_index("ix_balancer_team_variant_id", "team", ["variant_id"], schema="balancer")

    # -----------------------------------------------------------------------
    # 4. balancer.team_slot
    # -----------------------------------------------------------------------
    op.create_table(
        "team_slot",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("team_id", sa.BigInteger(), nullable=False),
        sa.Column("player_id", sa.BigInteger(), nullable=True),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("assigned_rank", sa.Integer(), nullable=False),
        sa.Column("discomfort", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_captain", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["team_id"], ["balancer.team.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["player_id"], ["balancer.player.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("team_id", "player_id", name="uq_balancer_team_slot"),
        schema="balancer",
    )
    op.create_index("ix_balancer_team_slot_team_id", "team_slot", ["team_id"], schema="balancer")
    op.create_index("ix_balancer_team_slot_player_id", "team_slot", ["player_id"], schema="balancer")

    # -----------------------------------------------------------------------
    # 5. balancer.registration_form
    # -----------------------------------------------------------------------
    op.create_table(
        "registration_form",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tournament_id", sa.BigInteger(), nullable=False),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("is_open", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("opens_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closes_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("built_in_fields_json", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("custom_fields_json", sa.JSON(), server_default="[]", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournament.tournament.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tournament_id", name="uq_balancer_registration_form_tournament"),
        schema="balancer",
    )
    op.create_index(
        "ix_balancer_registration_form_tournament_id", "registration_form", ["tournament_id"], schema="balancer"
    )

    # -----------------------------------------------------------------------
    # 6. balancer.registration
    # -----------------------------------------------------------------------
    op.create_table(
        "registration",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tournament_id", sa.BigInteger(), nullable=False),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("auth_user_id", sa.BigInteger(), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("battle_tag", sa.String(255), nullable=True),
        sa.Column("battle_tag_normalized", sa.String(255), nullable=True),
        sa.Column("discord_nick", sa.String(255), nullable=True),
        sa.Column("twitch_nick", sa.String(255), nullable=True),
        sa.Column("stream_pov", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("primary_role", sa.String(16), nullable=True),
        sa.Column("additional_roles_json", sa.JSON(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("custom_fields_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(32), server_default="pending", nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournament.tournament.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["auth_user_id"], ["auth.user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["players.user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["auth.user.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("tournament_id", "auth_user_id", name="uq_balancer_registration_user"),
        schema="balancer",
    )
    op.create_index("ix_balancer_registration_tournament_status", "registration", ["tournament_id", "status"], schema="balancer")
    op.create_index("ix_balancer_registration_auth_user_id", "registration", ["auth_user_id"], schema="balancer")
    op.create_index(
        "ix_registration_battle_tag",
        "registration",
        ["tournament_id", "battle_tag_normalized"],
        schema="balancer",
        postgresql_where=sa.text("battle_tag_normalized IS NOT NULL"),
    )

    # Now add FK from application to registration
    op.create_foreign_key(
        "fk_application_registration",
        "application",
        "registration",
        ["registration_id"],
        ["id"],
        source_schema="balancer",
        referent_schema="balancer",
        ondelete="SET NULL",
    )
    op.create_index("ix_balancer_application_registration_id", "application", ["registration_id"], schema="balancer")

    # -----------------------------------------------------------------------
    # 7. players.external_account
    # -----------------------------------------------------------------------
    op.create_table(
        "external_account",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("url", sa.String(500), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["players.user.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "provider", "username", name="uq_external_account"),
        schema="players",
    )
    op.create_index("ix_players_external_account_user_id", "external_account", ["user_id"], schema="players")
    op.create_index("ix_players_external_account_provider", "external_account", ["provider", "username"], schema="players")

    # -----------------------------------------------------------------------
    # 8. analytics.balance_snapshot
    # -----------------------------------------------------------------------
    op.create_table(
        "balance_snapshot",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tournament_id", sa.BigInteger(), nullable=False),
        sa.Column("balance_id", sa.BigInteger(), nullable=False),
        sa.Column("variant_id", sa.BigInteger(), nullable=True),
        sa.Column("workspace_id", sa.BigInteger(), nullable=True),
        sa.Column("algorithm", sa.String(32), nullable=False),
        sa.Column("division_scope", sa.String(32), nullable=True),
        sa.Column("division_grid_json", sa.JSON(), nullable=True),
        sa.Column("team_count", sa.Integer(), nullable=False),
        sa.Column("player_count", sa.Integer(), nullable=False),
        sa.Column("avg_sr_overall", sa.Float(), nullable=False),
        sa.Column("sr_std_dev", sa.Float(), nullable=False),
        sa.Column("sr_range", sa.Float(), nullable=False),
        sa.Column("total_discomfort", sa.Integer(), server_default="0", nullable=False),
        sa.Column("off_role_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("objective_score", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournament.tournament.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["balance_id"], ["balancer.balance.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["variant_id"], ["balancer.balance_variant.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("tournament_id", "balance_id", name="uq_analytics_balance_snapshot"),
        schema="analytics",
    )
    op.create_index("ix_analytics_balance_snapshot_tournament_id", "balance_snapshot", ["tournament_id"], schema="analytics")

    # -----------------------------------------------------------------------
    # 9. analytics.balance_player_snapshot
    # -----------------------------------------------------------------------
    op.create_table(
        "balance_player_snapshot",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("balance_snapshot_id", sa.BigInteger(), nullable=False),
        sa.Column("tournament_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("team_id", sa.BigInteger(), nullable=True),
        sa.Column("assigned_role", sa.String(16), nullable=False),
        sa.Column("preferred_role", sa.String(16), nullable=True),
        sa.Column("assigned_rank", sa.Integer(), nullable=False),
        sa.Column("discomfort", sa.Integer(), server_default="0", nullable=False),
        sa.Column("division_number", sa.Integer(), nullable=True),
        sa.Column("is_captain", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("was_off_role", sa.Boolean(), server_default="false", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["balance_snapshot_id"], ["analytics.balance_snapshot.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournament.tournament.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["players.user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["team_id"], ["tournament.team.id"], ondelete="SET NULL"),
        schema="analytics",
    )
    op.create_index(
        "ix_analytics_balance_player_snap_tournament", "balance_player_snapshot", ["tournament_id"], schema="analytics"
    )
    op.create_index(
        "ix_analytics_balance_player_snap_user", "balance_player_snapshot", ["user_id"], schema="analytics"
    )

    # -----------------------------------------------------------------------
    # 10. Data migration: populate player_role_entry from role_entries_json
    # -----------------------------------------------------------------------
    op.execute("""
        INSERT INTO balancer.player_role_entry (id, player_id, role, subtype, priority, rank_value, division_number, is_active, created_at)
        SELECT
            nextval('balancer.player_role_entry_id_seq'),
            p.id,
            (entry->>'role')::varchar(16),
            (entry->>'subtype')::varchar(32),
            COALESCE((entry->>'priority')::integer, 1),
            (entry->>'rank_value')::integer,
            (entry->>'division_number')::integer,
            COALESCE((entry->>'is_active')::boolean, true),
            p.created_at
        FROM balancer.player p,
             jsonb_array_elements(p.role_entries_json::jsonb) AS entry
        WHERE p.role_entries_json IS NOT NULL
          AND jsonb_array_length(p.role_entries_json::jsonb) > 0
        ON CONFLICT (player_id, role) DO NOTHING
    """)


def downgrade() -> None:
    # Drop new tables in reverse order
    op.drop_table("balance_player_snapshot", schema="analytics")
    op.drop_table("balance_snapshot", schema="analytics")
    op.drop_table("external_account", schema="players")

    # Drop FKs from existing tables first
    op.drop_constraint("fk_application_registration", "application", schema="balancer", type_="foreignkey")
    op.drop_index("ix_balancer_application_registration_id", "application", schema="balancer")

    op.drop_table("registration", schema="balancer")
    op.drop_table("registration_form", schema="balancer")
    op.drop_table("team_slot", schema="balancer")

    op.drop_constraint("fk_team_variant", "team", schema="balancer", type_="foreignkey")
    op.drop_index("ix_balancer_team_variant_id", "team", schema="balancer")

    op.drop_table("balance_variant", schema="balancer")
    op.drop_table("player_role_entry", schema="balancer")

    # Drop new columns
    op.drop_column("application", "registration_id", schema="balancer")
    op.drop_column("team", "variant_id", schema="balancer")
    op.drop_constraint("fk_balance_workspace", "balance", schema="balancer", type_="foreignkey")
    op.drop_index("ix_balancer_balance_workspace_id", "balance", schema="balancer")
    op.drop_column("balance", "division_scope", schema="balancer")
    op.drop_column("balance", "division_grid_json", schema="balancer")
    op.drop_column("balance", "algorithm", schema="balancer")
    op.drop_column("balance", "workspace_id", schema="balancer")
