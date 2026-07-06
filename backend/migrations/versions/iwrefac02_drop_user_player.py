"""identity refactor: drop auth.user_player (superseded by players.user.auth_user_id)"""

import sqlalchemy as sa
from alembic import op

revision = "iwrefac02"
down_revision = "iwrefac01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("user_player", schema="auth")


def downgrade() -> None:
    op.create_table(
        "user_player",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("auth_user_id", sa.BigInteger(), nullable=False),
        sa.Column("player_id", sa.BigInteger(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["auth_user_id"], ["auth.user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["player_id"], ["players.user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("player_id"),
        schema="auth",
    )
