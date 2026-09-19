"""Add ``tournament.tournament.rules``.

Revision ID: trules01
Revises: roledps01
Create Date: 2026-09-18 00:00:00.000000

The organizer-published regulations (format, code of conduct, tiebreakers) as
Markdown text. ``description`` stays what it was -- the one-paragraph "what is
this tournament" line shown in the overview's format card; this is a document
with its own public page.

Nullable with no default and no backfill: NULL means "this organizer published
no regulations", which is what every existing tournament is, and the public
Rules tab is absent rather than empty in that state.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "trules01"
down_revision: str | Sequence[str] | None = "roledps01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tournament", sa.Column("rules", sa.Text(), nullable=True), schema="tournament")


def downgrade() -> None:
    op.drop_column("tournament", "rules", schema="tournament")
