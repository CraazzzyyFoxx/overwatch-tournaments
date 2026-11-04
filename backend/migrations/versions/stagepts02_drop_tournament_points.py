"""Drop ``tournament.win_points``/``draw_points``/``loss_points``.

``stagepts01`` (v2.8.0) copied them onto the stages and left them in place while v2.7.0 still mapped them; no
code since v2.8.0 reads them.

Revision ID: stagepts02
Revises: voice01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Annotated form on purpose: scripts/export_erd.py finds the chain's head with
# ``^revision:\s*str\s*=`` and silently skips a revision written any other way.
revision: str = "stagepts02"
down_revision: str | Sequence[str] | None = "voice01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_POINTS = (("win_points", "1.0"), ("draw_points", "0.5"), ("loss_points", "0.0"))


def upgrade() -> None:
    for column, _ in _POINTS:
        op.drop_column("tournament", column, schema="tournament")


def downgrade() -> None:
    # The stage values stagepts01 wrote stay: restored tournament columns only carry the defaults.
    for column, default in _POINTS:
        op.add_column(
            "tournament",
            sa.Column(column, sa.Float(), server_default=default, nullable=False),
            schema="tournament",
        )
