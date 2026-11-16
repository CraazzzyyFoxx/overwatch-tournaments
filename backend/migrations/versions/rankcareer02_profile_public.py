"""Whether an account's profile shows its career now: ``rank.account_profile.is_public``.

Revision ID: rankcareer02_profile_public
Revises: rankcareer01_career_rates
Create Date: 2026-11-16 00:00:00.000000

The collection status ``private`` means "no competitive ranks": it covers closed profiles and open ones with no rank
this season alike. The ladder reads need the difference: a closed profile must not show the career collected while it
was open. The column is set by every poll; the backfill takes "some career was collected" for the rows that exist,
and the next poll (within the collection interval) corrects it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "rankcareer02_profile_public"
down_revision: str | Sequence[str] | None = "rankcareer01_career_rates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "account_profile",
        sa.Column("is_public", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        schema="rank",
    )
    op.execute(
        """
        UPDATE rank.account_profile AS profile
        SET is_public = EXISTS (
            SELECT 1 FROM rank.career_snapshot AS career WHERE career.social_account_id = profile.social_account_id
        )
        """
    )


def downgrade() -> None:
    op.drop_column("account_profile", "is_public", schema="rank")
