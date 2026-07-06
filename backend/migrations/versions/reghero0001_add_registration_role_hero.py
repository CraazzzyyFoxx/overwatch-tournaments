"""add_registration_role_hero

Normalized junction table for a registration role's ordered "top heroes"
preference (balancer.registration_role_hero). Each row links a
balancer.registration_role entry to an overwatch.hero with a 1-based priority.

Revision ID: reghero0001
Revises: algonames0001
Create Date: 2026-05-31 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "reghero0001"
down_revision: str | None = "algonames0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "registration_role_hero",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("role_id", sa.BigInteger(), nullable=False),
        sa.Column("hero_id", sa.BigInteger(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["role_id"], ["balancer.registration_role.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["hero_id"], ["overwatch.hero.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("role_id", "priority", name="uq_reg_role_hero_role_priority"),
        sa.UniqueConstraint("role_id", "hero_id", name="uq_reg_role_hero_role_hero"),
        schema="balancer",
    )
    op.create_index(
        "ix_balancer_registration_role_hero_role_id",
        "registration_role_hero",
        ["role_id"],
        schema="balancer",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_balancer_registration_role_hero_role_id",
        table_name="registration_role_hero",
        schema="balancer",
    )
    op.drop_table("registration_role_hero", schema="balancer")
