"""add hidden tournaments: Tournament.is_hidden + tournament_preview_access

Existing rows default to visible (is_hidden=false). The allowlist keys on
auth.user so a preview invitee must be logged in.

Revision ID: hidden0001
Revises: mvpimp0001
"""

import sqlalchemy as sa
from alembic import op

revision = "hidden0001"
down_revision = "mvpimp0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tournament",
        sa.Column("is_hidden", sa.Boolean(), server_default="false", nullable=False),
        schema="tournament",
    )
    op.create_index("ix_tournament_is_hidden", "tournament", ["is_hidden"], schema="tournament")

    op.create_table(
        "tournament_preview_access",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tournament_id", sa.BigInteger(), nullable=False),
        sa.Column("auth_user_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournament.tournament.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["auth_user_id"], ["auth.user.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "tournament_id", "auth_user_id", name="uq_tournament_preview_access_tournament_user"
        ),
        schema="tournament",
    )
    op.create_index(
        "ix_tournament_preview_access_tournament",
        "tournament_preview_access",
        ["tournament_id"],
        schema="tournament",
    )
    op.create_index(
        "ix_tournament_preview_access_auth_user",
        "tournament_preview_access",
        ["auth_user_id"],
        schema="tournament",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tournament_preview_access_auth_user", table_name="tournament_preview_access", schema="tournament"
    )
    op.drop_index(
        "ix_tournament_preview_access_tournament", table_name="tournament_preview_access", schema="tournament"
    )
    op.drop_table("tournament_preview_access", schema="tournament")
    op.drop_index("ix_tournament_is_hidden", table_name="tournament", schema="tournament")
    op.drop_column("tournament", "is_hidden", schema="tournament")
