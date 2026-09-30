"""Store the draft format on the tournament.

Revision ID: draftfmt01
Revises: noorg01
Create Date: 2026-09-30 00:00:00.000000

The draft format -- snake / linear / custom round rules -- is a rule organizers
announce with the tournament, yet it only ever existed on the draft session,
re-entered in the setup wizard every time. ``draft_format_json`` gives it a home:
``{"format": ..., "round_rules": [...], "avg_tie_seed_reverse": bool}``, written
through ``shared.schemas.draft_format``.

``NULL`` means snake -- today's default -- so no backfill: every existing
tournament keeps behaving exactly as it did, and every existing draft session
already carries its own snapshot of the format it was created with.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "draftfmt01"
down_revision: str | Sequence[str] | None = "noorg01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tournament",
        sa.Column("draft_format_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema="tournament",
    )


def downgrade() -> None:
    op.drop_column("tournament", "draft_format_json", schema="tournament")
