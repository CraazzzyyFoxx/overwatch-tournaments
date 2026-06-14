"""add_dynamic_player_sub_roles

Revision ID: c8d2e4f6g8h0
Revises: a7b1c2d3e4f5
Create Date: 2026-04-17 12:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c8d2e4f6g8h0"
down_revision: Union[str, None] = "a7b1c2d3e4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "player",
        sa.Column("sub_role", sa.String(length=128), nullable=True),
        schema="tournament",
    )
    op.create_index(
        "ix_player_tournament_role_sub_role",
        "player",
        ["tournament_id", "role", "sub_role"],
        unique=False,
        schema="tournament",
    )
    op.alter_column(
        "player_role_entry",
        "subtype",
        existing_type=sa.String(length=32),
        type_=sa.String(length=128),
        existing_nullable=True,
        schema="balancer",
    )
    op.alter_column(
        "registration_role",
        "subrole",
        existing_type=sa.String(length=32),
        type_=sa.String(length=128),
        existing_nullable=True,
        schema="balancer",
    )

    op.create_table(
        "player_sub_role",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "role",
            "slug",
            name="uq_player_sub_role_workspace_role_slug",
        ),
        schema="tournament",
    )
    op.create_index(
        "ix_player_sub_role_workspace_id",
        "player_sub_role",
        ["workspace_id"],
        unique=False,
        schema="tournament",
    )
    op.create_index(
        "ix_player_sub_role_workspace_role_active",
        "player_sub_role",
        ["workspace_id", "role", "is_active"],
        unique=False,
        schema="tournament",
    )

    op.execute(
        """
        UPDATE tournament.player
        SET sub_role = CASE
            WHEN lower(role::text) IN ('damage', 'dps')
                AND COALESCE("primary", false) IS TRUE
                AND COALESCE(secondary, false) IS NOT TRUE
                THEN 'hitscan'
            WHEN lower(role::text) IN ('damage', 'dps')
                AND COALESCE(secondary, false) IS TRUE
                AND COALESCE("primary", false) IS NOT TRUE
                THEN 'projectile'
            WHEN lower(role::text) = 'support'
                AND COALESCE("primary", false) IS TRUE
                AND COALESCE(secondary, false) IS NOT TRUE
                THEN 'main_heal'
            WHEN lower(role::text) = 'support'
                AND COALESCE(secondary, false) IS TRUE
                AND COALESCE("primary", false) IS NOT TRUE
                THEN 'light_heal'
            ELSE NULL
        END
        """
    )

    op.execute(
        """
        INSERT INTO tournament.player_sub_role (
            workspace_id,
            role,
            slug,
            label,
            sort_order,
            is_active
        )
        SELECT
            workspace.id,
            defaults.role,
            defaults.slug,
            defaults.label,
            defaults.sort_order,
            true
        FROM workspace
        CROSS JOIN (
            VALUES
                ('damage', 'hitscan', 'Hitscan', 10),
                ('damage', 'projectile', 'Projectile', 20),
                ('support', 'main_heal', 'Main Heal', 10),
                ('support', 'light_heal', 'Light Heal', 20)
        ) AS defaults(role, slug, label, sort_order)
        ON CONFLICT (workspace_id, role, slug) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_player_sub_role_workspace_role_active",
        table_name="player_sub_role",
        schema="tournament",
    )
    op.drop_index(
        "ix_player_sub_role_workspace_id",
        table_name="player_sub_role",
        schema="tournament",
    )
    op.drop_table("player_sub_role", schema="tournament")
    op.alter_column(
        "registration_role",
        "subrole",
        existing_type=sa.String(length=128),
        type_=sa.String(length=32),
        existing_nullable=True,
        schema="balancer",
    )
    op.alter_column(
        "player_role_entry",
        "subtype",
        existing_type=sa.String(length=128),
        type_=sa.String(length=32),
        existing_nullable=True,
        schema="balancer",
    )
    op.drop_index(
        "ix_player_tournament_role_sub_role",
        table_name="player",
        schema="tournament",
    )
    op.drop_column("player", "sub_role", schema="tournament")
