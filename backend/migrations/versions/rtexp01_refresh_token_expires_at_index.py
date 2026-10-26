"""``auth.refresh_token``: index ``expires_at`` for the daily purge.

Revision ID: rtexp01
Revises: authavatar01
Create Date: 2026-10-26 22:00:00.000000

The identity service deletes tokens that expired more than 30 days ago in batches of 5000
(``RefreshTokenRepository.delete_expired_before``); without this index every batch scans the whole table. A plain
``CREATE INDEX`` like ``statrec01``: the table is ~90k narrow rows, so the build blocks token writes for well under a
second, and ``migrations/env.py`` runs the upgrade in one transaction, where ``CONCURRENTLY`` is unavailable.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "rtexp01"
down_revision: str | Sequence[str] | None = "authavatar01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_auth_refresh_token_expires_at ON auth.refresh_token (expires_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS auth.ix_auth_refresh_token_expires_at")
