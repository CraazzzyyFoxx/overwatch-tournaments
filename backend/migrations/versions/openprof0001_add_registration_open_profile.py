"""add open-profile admission settings to registration_form

Adds a per-tournament admission requirement: the registrant's Overwatch
profile(s) must be public. ``open_profile_scope`` controls whether only the main
registered battle tag or all accounts (incl. smurfs) must be open.

Revision ID: openprof0001
Revises: 0659e015558b
Create Date: 2026-06-02 00:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "openprof0001"
down_revision: str | Sequence[str] | None = "0659e015558b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "registration_form",
        sa.Column(
            "require_open_profile",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        schema="balancer",
    )
    op.add_column(
        "registration_form",
        sa.Column(
            "open_profile_scope",
            sa.String(length=8),
            server_default="main",
            nullable=False,
        ),
        schema="balancer",
    )


def downgrade() -> None:
    op.drop_column("registration_form", "open_profile_scope", schema="balancer")
    op.drop_column("registration_form", "require_open_profile", schema="balancer")
