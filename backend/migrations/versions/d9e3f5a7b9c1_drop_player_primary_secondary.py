"""drop_player_primary_secondary

Revision ID: d9e3f5a7b9c1
Revises: c8d2e4f6g8h0
Create Date: 2026-04-17 18:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "d9e3f5a7b9c1"
down_revision = "c8d2e4f6g8h0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("player", "secondary", schema="tournament")
    op.drop_column("player", "primary", schema="tournament")


def downgrade() -> None:
    op.add_column(
        "player",
        sa.Column("primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema="tournament",
    )
    op.add_column(
        "player",
        sa.Column("secondary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema="tournament",
    )

    op.execute(
        """
        UPDATE tournament.player
        SET
            "primary" = CASE
                WHEN lower(coalesce(sub_role, '')) IN ('hitscan', 'main_heal') THEN TRUE
                ELSE FALSE
            END,
            secondary = CASE
                WHEN lower(coalesce(sub_role, '')) IN ('projectile', 'light_heal') THEN TRUE
                ELSE FALSE
            END
        """
    )

    op.alter_column(
        "player",
        "primary",
        server_default=None,
        schema="tournament",
    )
    op.alter_column(
        "player",
        "secondary",
        server_default=None,
        schema="tournament",
    )
