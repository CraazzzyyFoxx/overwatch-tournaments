"""Add ``auth.api_key.is_superuser``.

Revision ID: apikeysu01
Revises: regidsoc01
Create Date: 2026-10-10 00:00:00.000000

A superuser may mint a key that carries ``is_superuser`` in its token payload;
validation honours it only while the owner is still a superuser.

``auth.api_key`` is read on every API-key request, so take ``lock_timeout``
rather than queueing readers behind an ACCESS EXCLUSIVE wait. ADD COLUMN with a
constant default is metadata-only on PostgreSQL 11+.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "apikeysu01"
down_revision: str | Sequence[str] | None = "regidsoc01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout = '3s'"))
    op.add_column(
        "api_key",
        sa.Column("is_superuser", sa.Boolean(), server_default=sa.false(), nullable=False),
        schema="auth",
    )


def downgrade() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout = '3s'"))
    op.drop_column("api_key", "is_superuser", schema="auth")
