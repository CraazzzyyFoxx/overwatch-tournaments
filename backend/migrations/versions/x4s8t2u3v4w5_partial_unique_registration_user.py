"""partial_unique_registration_user

Replaces the plain unique constraint uq_balancer_registration_user
(tournament_id, auth_user_id) with a partial unique index that only
applies to non-deleted rows (deleted_at IS NULL).

This allows soft-deleted registrations to be re-created without
hitting a UniqueViolationError.

Revision ID: x4s8t2u3v4w5
Revises: w3r7s1t2u3v4
Create Date: 2026-04-12
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "x4s8t2u3v4w5"
down_revision: Union[str, None] = "w3r7s1t2u3v4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_balancer_registration_user",
        "registration",
        schema="balancer",
        type_="unique",
    )
    op.create_index(
        "uq_balancer_registration_user",
        "registration",
        ["tournament_id", "auth_user_id"],
        unique=True,
        schema="balancer",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_balancer_registration_user",
        table_name="registration",
        schema="balancer",
    )
    op.create_unique_constraint(
        "uq_balancer_registration_user",
        "registration",
        ["tournament_id", "auth_user_id"],
        schema="balancer",
    )
