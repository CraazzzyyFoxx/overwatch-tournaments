"""add_auto_approve

Adds balancer.registration_form.auto_approve flag.
When enabled, registrations skip the pending review stage.

Revision ID: p6k8l0m4n5o6
Revises: o5j7k9l3m4n5
Create Date: 2026-04-10 03:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "p6k8l0m4n5o6"
down_revision: str | None = "o5j7k9l3m4n5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "registration_form",
        sa.Column("auto_approve", sa.Boolean(), server_default="false", nullable=False),
        schema="balancer",
    )


def downgrade() -> None:
    op.drop_column("registration_form", "auto_approve", schema="balancer")
