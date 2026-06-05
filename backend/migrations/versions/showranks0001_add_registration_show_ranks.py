"""add show_ranks to registration_form

Adds a setting to toggle displaying player ranks on the participants page.

Revision ID: showranks0001
Revises: draft0002
Create Date: 2026-06-05 17:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "showranks0001"
down_revision: str | Sequence[str] | None = "draft0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "registration_form",
        sa.Column(
            "show_ranks",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        schema="balancer",
    )


def downgrade() -> None:
    op.drop_column("registration_form", "show_ranks", schema="balancer")
