"""Workspace public profile: tagline, about, and the three community links.

Revision ID: wsprof01
Revises: mixvoice01
Create Date: 2026-10-08 00:00:00.000000

What the public workspace page renders above its tournaments. All nullable:
a workspace that filled nothing in simply shows no tagline, no about block and
no link row. ``about`` is Markdown, so Text, not a width-capped String -- the
4000-character ceiling is a submission rule (``schemas.WorkspaceUpdate``), not
a storage one, and tightening it later must not need a migration.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "wsprof01"
down_revision: str | Sequence[str] | None = "mixvoice01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workspace", sa.Column("tagline", sa.String(length=120), nullable=True))
    op.add_column("workspace", sa.Column("about", sa.Text(), nullable=True))
    for column in ("discord_url", "twitch_url", "boosty_url"):
        op.add_column("workspace", sa.Column(column, sa.String(length=512), nullable=True))


def downgrade() -> None:
    for column in ("boosty_url", "twitch_url", "discord_url", "about", "tagline"):
        op.drop_column("workspace", column)
