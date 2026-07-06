"""purge_legacy_balancer_player_application

Full legacy purge of the balancer ingestion chain now that BalancerRegistration is
the single source of truth (data was already migrated by w3r7s1t2u3v4):

- Drops balancer.player_role_entry, balancer.player, balancer.application,
  balancer.tournament_sheet.
- Repoints balancer.team_slot off the deleted player table: adds
  battle_tag_normalized (backfilled from player) and drops player_id.
- Drops balancer.draft_player.source_balancer_player_id (legacy link to player).
- Drops the stored balancer.registration.is_flex column (now the is_flex_computed
  hybrid, derived from roles).
- Drops balancer.team.roster_json (normalized into balancer.team_slot).

Revision ID: purge0001
Revises: wsbcfg0002
Create Date: 2026-06-10 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "purge0001"
down_revision: str | None = "wsbcfg0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. team_slot: add durable battle-tag link, backfill from player, drop player_id.
    op.add_column(
        "team_slot",
        sa.Column("battle_tag_normalized", sa.String(length=255), nullable=True),
        schema="balancer",
    )
    op.create_index(
        "ix_balancer_team_slot_battle_tag_normalized",
        "team_slot",
        ["battle_tag_normalized"],
        schema="balancer",
    )
    op.execute(
        """
        UPDATE balancer.team_slot AS ts
           SET battle_tag_normalized = p.battle_tag_normalized
          FROM balancer.player AS p
         WHERE ts.player_id = p.id
        """
    )
    # Dropping player_id cascades its unique constraint (uq_balancer_team_slot),
    # index and inline FK in PostgreSQL.
    op.drop_constraint("uq_balancer_team_slot", "team_slot", schema="balancer", type_="unique")
    op.drop_index("ix_balancer_team_slot_player_id", table_name="team_slot", schema="balancer")
    op.drop_column("team_slot", "player_id", schema="balancer")

    # 2. draft_player: drop legacy link to balancer.player.
    op.drop_index(
        "ix_balancer_draft_player_source_balancer_player_id",
        table_name="draft_player",
        schema="balancer",
    )
    op.drop_column("draft_player", "source_balancer_player_id", schema="balancer")

    # 3. Drop legacy ingestion tables (children first; FK-safe order).
    op.drop_table("player_role_entry", schema="balancer")
    op.drop_table("player", schema="balancer")
    op.drop_table("application", schema="balancer")
    op.drop_table("tournament_sheet", schema="balancer")

    # 4. registration.is_flex -> derived is_flex_computed hybrid.
    op.drop_column("registration", "is_flex", schema="balancer")

    # 5. team.roster_json -> normalized team_slot rows.
    op.drop_column("team", "roster_json", schema="balancer")


def downgrade() -> None:
    # Best-effort schema restore only. Legacy row data (applications, players,
    # role entries, tournament sheets, team rosters) is NOT recoverable.

    # 5. team.roster_json
    op.add_column(
        "team",
        sa.Column("roster_json", sa.JSON(), nullable=True),
        schema="balancer",
    )

    # 4. registration.is_flex
    op.add_column(
        "registration",
        sa.Column("is_flex", sa.Boolean(), server_default="false", nullable=False),
        schema="balancer",
    )

    # 3. Recreate legacy tables (parents first).
    op.create_table(
        "tournament_sheet",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tournament_id", sa.BigInteger(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("sheet_id", sa.String(255), nullable=False),
        sa.Column("gid", sa.String(64), nullable=True),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("header_row_json", sa.JSON(), nullable=True),
        sa.Column("column_mapping_json", sa.JSON(), nullable=True),
        sa.Column("role_mapping_json", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_status", sa.String(32), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournament.tournament.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tournament_id", name="uq_balancer_tournament_sheet_tournament"),
        schema="balancer",
    )
    op.create_index(
        "ix_balancer_tournament_sheet_tournament_id", "tournament_sheet", ["tournament_id"], schema="balancer"
    )

    op.create_table(
        "application",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tournament_id", sa.BigInteger(), nullable=False),
        sa.Column("tournament_sheet_id", sa.BigInteger(), nullable=False),
        sa.Column("registration_id", sa.BigInteger(), nullable=True),
        sa.Column("battle_tag", sa.String(255), nullable=False),
        sa.Column("battle_tag_normalized", sa.String(255), nullable=False),
        sa.Column("smurf_tags_json", sa.JSON(), nullable=True),
        sa.Column("twitch_nick", sa.String(255), nullable=True),
        sa.Column("discord_nick", sa.String(255), nullable=True),
        sa.Column("stream_pov", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("last_tournament_text", sa.Text(), nullable=True),
        sa.Column("primary_role", sa.String(64), nullable=True),
        sa.Column("additional_roles_json", sa.JSON(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("raw_row_json", sa.JSON(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournament.tournament.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tournament_sheet_id"], ["balancer.tournament_sheet.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["registration_id"], ["balancer.registration.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("tournament_id", "battle_tag_normalized", name="uq_balancer_application_tournament_tag"),
        schema="balancer",
    )
    op.create_index("ix_balancer_application_tournament_id", "application", ["tournament_id"], schema="balancer")
    op.create_index(
        "ix_balancer_application_tournament_sheet_id", "application", ["tournament_sheet_id"], schema="balancer"
    )
    op.create_index("ix_balancer_application_registration_id", "application", ["registration_id"], schema="balancer")
    op.create_index(
        "ix_balancer_application_battle_tag_normalized", "application", ["battle_tag_normalized"], schema="balancer"
    )

    op.create_table(
        "player",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tournament_id", sa.BigInteger(), nullable=False),
        sa.Column("application_id", sa.BigInteger(), nullable=False),
        sa.Column("battle_tag", sa.String(255), nullable=False),
        sa.Column("battle_tag_normalized", sa.String(255), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("role_entries_json", sa.JSON(), nullable=True),
        sa.Column("is_flex", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("primary_role", sa.String(32), nullable=True),
        sa.Column("secondary_roles_json", sa.JSON(), nullable=True),
        sa.Column("division_number", sa.Integer(), nullable=True),
        sa.Column("rank_value", sa.Integer(), nullable=True),
        sa.Column("is_in_pool", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("admin_notes", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournament.tournament.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["application_id"], ["balancer.application.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["players.user.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("application_id", name="uq_balancer_player_application"),
        schema="balancer",
    )
    op.create_index("ix_balancer_player_tournament_id", "player", ["tournament_id"], schema="balancer")
    op.create_index("ix_balancer_player_application_id", "player", ["application_id"], schema="balancer")
    op.create_index("ix_balancer_player_battle_tag_normalized", "player", ["battle_tag_normalized"], schema="balancer")
    op.create_index("ix_balancer_player_user_id", "player", ["user_id"], schema="balancer")

    op.create_table(
        "player_role_entry",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("player_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("subtype", sa.String(128), nullable=True),
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
    op.create_index("ix_player_role_entry_role_active", "player_role_entry", ["role", "is_active"], schema="balancer")

    # 2. draft_player.source_balancer_player_id
    op.add_column(
        "draft_player",
        sa.Column("source_balancer_player_id", sa.BigInteger(), nullable=True),
        schema="balancer",
    )
    op.create_foreign_key(
        "fk_draft_player_source_balancer_player",
        "draft_player",
        "player",
        ["source_balancer_player_id"],
        ["id"],
        source_schema="balancer",
        referent_schema="balancer",
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_balancer_draft_player_source_balancer_player_id",
        "draft_player",
        ["source_balancer_player_id"],
        schema="balancer",
    )

    # 1. team_slot.player_id
    op.add_column(
        "team_slot",
        sa.Column("player_id", sa.BigInteger(), nullable=True),
        schema="balancer",
    )
    op.create_foreign_key(
        "fk_team_slot_player",
        "team_slot",
        "player",
        ["player_id"],
        ["id"],
        source_schema="balancer",
        referent_schema="balancer",
        ondelete="SET NULL",
    )
    op.create_index("ix_balancer_team_slot_player_id", "team_slot", ["player_id"], schema="balancer")
    op.create_unique_constraint("uq_balancer_team_slot", "team_slot", ["team_id", "player_id"], schema="balancer")
    op.drop_index("ix_balancer_team_slot_battle_tag_normalized", table_name="team_slot", schema="balancer")
    op.drop_column("team_slot", "battle_tag_normalized", schema="balancer")
