"""add balancer.draft_team.captain_auth_user_id

Stores the auth account that registered as captain, so captain gating works
independently of public-player linking.

Revision ID: draft0003
Revises: 31dfe32fc171
Create Date: 2026-06-05 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "draft0003"
down_revision: str | Sequence[str] | None = "31dfe32fc171"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "draft_team",
        sa.Column("captain_auth_user_id", sa.BigInteger(), nullable=True),
        schema="balancer",
    )
    op.create_index(
        op.f("ix_balancer_draft_team_captain_auth_user_id"),
        "draft_team",
        ["captain_auth_user_id"],
        schema="balancer",
    )
    op.create_foreign_key(
        "fk_draft_team_captain_auth_user",
        "draft_team",
        "user",
        ["captain_auth_user_id"],
        ["id"],
        source_schema="balancer",
        referent_schema="auth",
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_draft_team_captain_auth_user", "draft_team", schema="balancer", type_="foreignkey")
    op.drop_index(
        op.f("ix_balancer_draft_team_captain_auth_user_id"), table_name="draft_team", schema="balancer"
    )
    op.drop_column("draft_team", "captain_auth_user_id", schema="balancer")
