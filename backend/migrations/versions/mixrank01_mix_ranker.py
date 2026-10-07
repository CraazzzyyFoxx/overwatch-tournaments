"""Mix ranker: hidden ratings, the host's rating mode, the workspace's knobs, undo deltas.

Revision ID: mixrank01
Revises: plrole01
Create Date: 2026-10-07 00:00:00.000000

* ``balancer.member_hidden_rating`` -- the ranker's hidden ``(mu, sigma)`` per
  workspace member and role. Derived from ``casual.match``; starts empty and is
  filled by recorded matches or by the workspace admin's "rebuild from history".
* ``balancer.user_config.rating_mode`` -- ``points`` (today's flat
  ``points_per_win``) or ``ranker``. Every existing host stays on ``points``.
* ``balancer.workspace_config.ranker_json`` -- the workspace's ranker knobs;
  NULL means the defaults.
* ``casual.player.rank_delta_applied`` -- how far a ranker-mode recording moved
  that seat's rank, so undo gives back exactly that. NULL for every row written
  in points mode, including all existing ones.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "mixrank01"
down_revision: str | Sequence[str] | None = "plrole01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "member_hidden_rating",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("workspace_member_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("mu", sa.Float(), nullable=False),
        sa.Column("sigma", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_member_id"], ["workspace_member.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_member_id", "role", name="uq_member_hidden_rating_member_role"),
        schema="balancer",
    )
    op.create_index(
        op.f("ix_balancer_member_hidden_rating_workspace_id"),
        "member_hidden_rating",
        ["workspace_id"],
        unique=False,
        schema="balancer",
    )
    op.add_column(
        "user_config",
        sa.Column("rating_mode", sa.String(length=16), server_default="points", nullable=False),
        schema="balancer",
    )
    op.create_check_constraint(
        "ck_balancer_user_config_rating_mode",
        "user_config",
        "rating_mode IN ('points', 'ranker')",
        schema="balancer",
    )
    op.add_column(
        "workspace_config",
        sa.Column("ranker_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema="balancer",
    )
    op.add_column("player", sa.Column("rank_delta_applied", sa.Integer(), nullable=True), schema="casual")


def downgrade() -> None:
    op.drop_column("player", "rank_delta_applied", schema="casual")
    op.drop_column("workspace_config", "ranker_json", schema="balancer")
    # The CHECK names only this column, so Postgres drops it with the column.
    op.drop_column("user_config", "rating_mode", schema="balancer")
    op.drop_index(
        op.f("ix_balancer_member_hidden_rating_workspace_id"), table_name="member_hidden_rating", schema="balancer"
    )
    op.drop_table("member_hidden_rating", schema="balancer")
