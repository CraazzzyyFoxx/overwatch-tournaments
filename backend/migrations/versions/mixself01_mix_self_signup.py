"""Self-signup switches on a pickup mix: the signup mode and the role-edit flag.

Revision ID: mixself01
Revises: ffa0002
Create Date: 2026-09-25 00:00:00.000000

Two columns on ``balancer.custom_game``. ``self_signup`` is one column with
three states rather than a bool plus a destination enum, so "closed, but onto
the bench" cannot be represented at all -- hence the CHECK rather than a Postgres
ENUM type, which would need its own migration for every future state.

Deploy is a no-op: every existing mix gets ``closed``/``false``, which is exactly
today's behaviour (only the host and co-hosts write a roster), so the previous
release keeps serving unchanged while this runs.

No index: both columns are read only alongside the mix row itself.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "mixself01"
down_revision: str | Sequence[str] | None = "ffa0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "custom_game",
        sa.Column("self_signup", sa.String(length=16), server_default="closed", nullable=False),
        schema="balancer",
    )
    op.add_column(
        "custom_game",
        sa.Column("self_role_edit", sa.Boolean(), server_default="false", nullable=False),
        schema="balancer",
    )
    op.create_check_constraint(
        "ck_custom_game_self_signup",
        "custom_game",
        "self_signup IN ('closed', 'pool', 'benched')",
        schema="balancer",
    )


def downgrade() -> None:
    op.drop_constraint("ck_custom_game_self_signup", "custom_game", schema="balancer", type_="check")
    op.drop_column("custom_game", "self_role_edit", schema="balancer")
    op.drop_column("custom_game", "self_signup", schema="balancer")
