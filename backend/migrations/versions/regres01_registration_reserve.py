"""Registration reserve flag: the registrant's own "call me in as a sub".

Revision ID: regres01
Revises: chat01
Create Date: 2026-09-21 00:00:00.000000

One boolean column. It is a column and not a custom form answer because the
write paths need it in a predicate: the bulk pool sweeps skip reserves, the
public list counts them, and the admin table filters on them -- none of which
can see inside ``custom_fields_json``.

The ``editable`` per-field flag that ships alongside it needs no migration at
all: it lives inside ``balancer.registration_form_version.schema_json``, where a
document that omits the key picks up the (closed) default on read.

No index: every reader already scans one tournament's registrations.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "regres01"
down_revision: str | Sequence[str] | None = "chat01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "registration",
        sa.Column("is_reserve", sa.Boolean(), server_default="false", nullable=False),
        schema="balancer",
    )


def downgrade() -> None:
    op.drop_column("registration", "is_reserve", schema="balancer")
