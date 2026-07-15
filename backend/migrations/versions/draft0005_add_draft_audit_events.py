"""add draft player version and private audit events

Revision ID: draft0005
Revises: iwrefac09
Create Date: 2026-07-14 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "draft0005"
down_revision: str | Sequence[str] | None = "iwrefac09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "draft_session",
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
        schema="balancer",
    )
    op.add_column(
        "draft_session",
        sa.Column("blocked_reason", sa.String(length=64), nullable=True),
        schema="balancer",
    )
    op.add_column(
        "draft_player",
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
        schema="balancer",
    )
    op.create_table(
        "draft_audit_event",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("session_id", sa.BigInteger(), nullable=False),
        sa.Column("actor_auth_user_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("before_json", sa.JSON(), nullable=False),
        sa.Column("after_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_auth_user_id"],
            ["auth.user.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["balancer.draft_session.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="balancer",
    )
    op.create_index(
        "ix_balancer_draft_audit_event_actor_auth_user_id",
        "draft_audit_event",
        ["actor_auth_user_id"],
        unique=False,
        schema="balancer",
    )
    op.create_index(
        "ix_draft_audit_session_created",
        "draft_audit_event",
        ["session_id", "created_at"],
        unique=False,
        schema="balancer",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_draft_audit_session_created",
        table_name="draft_audit_event",
        schema="balancer",
    )
    op.drop_index(
        "ix_balancer_draft_audit_event_actor_auth_user_id",
        table_name="draft_audit_event",
        schema="balancer",
    )
    op.drop_table("draft_audit_event", schema="balancer")
    op.drop_column("draft_player", "version", schema="balancer")
    op.drop_column("draft_session", "blocked_reason", schema="balancer")
    op.drop_column("draft_session", "version", schema="balancer")
