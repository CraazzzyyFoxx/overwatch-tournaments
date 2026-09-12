"""Registration-list visibility toggle and advisory capacity.

Revision ID: reghide01
Revises: mixvar01
Create Date: 2026-09-13 00:00:00.000000

``hide_registrations`` collapses the public participants list to an aggregate.
It lives on the form next to ``show_ranks`` because it is the same kind of
decision -- what the public roster publishes -- and it is enforced in the read
model, not in the client: that payload is cached per tournament with no viewer
in the key.

``max_participants`` is INFORMATIONAL. Deliberately nullable with no default and
no check constraint against the live registration count: it is a number an
organizer announces, not a gate. Nothing on the write path reads it, and a
registration submitted past it is accepted.

Both columns default to the current behaviour, so every existing tournament
publishes exactly what it published before this revision.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "reghide01"
down_revision: str | Sequence[str] | None = "mixvar01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "registration_form",
        sa.Column("hide_registrations", sa.Boolean(), server_default="false", nullable=False),
        schema="balancer",
    )
    op.add_column(
        "registration_form",
        sa.Column("max_participants", sa.Integer(), nullable=True),
        schema="balancer",
    )


def downgrade() -> None:
    op.drop_column("registration_form", "max_participants", schema="balancer")
    op.drop_column("registration_form", "hide_registrations", schema="balancer")
