"""Add ``tournament.stage.bracket_template``.

Revision ID: btmpl01
Revises: bsplit01
Create Date: 2026-10-01 00:00:00.000000

Spec §5.3. The bracket an organizer drew by hand, stored as the format-neutral
blueprint of ``shared.services.bracket.template``: matches with ``U#``/``L#``
seed placeholders and winner/loser edges between them. Every path that builds a
bracket shape for the stage -- planned rounds, the preview and generation --
reads it instead of running the format's generator.

Nullable with no default and no backfill: NULL means "the format draws it",
which is what every existing stage does.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Annotated form on purpose: scripts/export_erd.py finds the chain's head with
# ``^revision:\s*str\s*=`` and silently skips a revision written any other way.
revision: str = "btmpl01"
down_revision: str | Sequence[str] | None = "bsplit01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("stage", sa.Column("bracket_template", postgresql.JSONB(), nullable=True), schema="tournament")


def downgrade() -> None:
    op.drop_column("stage", "bracket_template", schema="tournament")
