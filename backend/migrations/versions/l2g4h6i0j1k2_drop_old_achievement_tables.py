"""drop_old_achievement_tables

Revision ID: l2g4h6i0j1k2
Revises: k1f3g5h9i0j1
Create Date: 2026-04-09 23:30:00.000000

WARNING: Only run this migration AFTER verifying data parity between
old (achievement, user) and new (rule, evaluation_result) tables.

Drops:
- achievements.user (old AchievementUser)
- achievements.achievement (old Achievement)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "l2g4h6i0j1k2"
down_revision: Union[str, None] = "k1f3g5h9i0j1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("user", schema="achievements")
    op.drop_table("achievement", schema="achievements")


def downgrade() -> None:
    # Recreate old tables
    op.create_table(
        "achievement",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("description_ru", sa.String(), nullable=False),
        sa.Column("description_en", sa.String(), nullable=False),
        sa.Column("image_url", sa.String(), nullable=True),
        sa.Column("hero_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["hero_id"], ["overwatch.hero.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("slug"),
        schema="achievements",
    )
    op.create_index("ix_achievements_achievement_slug", "achievement", ["slug"], schema="achievements")

    op.create_table(
        "user",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("achievement_id", sa.BigInteger(), nullable=False),
        sa.Column("tournament_id", sa.Integer(), nullable=True),
        sa.Column("match_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["players.user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["achievement_id"], ["achievements.achievement.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournament.tournament.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["match_id"], ["matches.match.id"], ondelete="CASCADE"),
        schema="achievements",
    )
