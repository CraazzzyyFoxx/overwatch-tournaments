"""Points per win/draw/loss live on the stage only: copy ``tournament.win_points``/``draw_points``/``loss_points`` down.

A stage member left NULL used to inherit the tournament's value; it now means the fixed default (1 / 0.5 / 0).
Every NULL member whose tournament value differs from that default is written onto the stage, so no existing
table is ranked differently. The tournament columns stay: the previous release's containers still map them
while this migration runs (CONTRIBUTING, destructive migrations); a later revision drops them.

Revision ID: stagepts01
Revises: iswiss02
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# Annotated form on purpose: scripts/export_erd.py finds the chain's head with
# ``^revision:\s*str\s*=`` and silently skips a revision written any other way.
revision: str = "stagepts01"
down_revision: str | Sequence[str] | None = "iswiss02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_POINTS = (("win_points", "1.0"), ("draw_points", "0.5"), ("loss_points", "0.0"))


def upgrade() -> None:
    assignments = ",\n            ".join(
        f"{column} = CASE WHEN s.{column} IS NULL AND t.{column} <> {default} THEN t.{column} ELSE s.{column} END"
        for column, default in _POINTS
    )
    op.execute(
        f"""
        UPDATE tournament.stage AS s SET
            {assignments}
        FROM tournament.tournament AS t
        WHERE t.id = s.tournament_id
        """
    )


def downgrade() -> None:
    # The stage values written by the upgrade stay; the tournament columns were never dropped.
    pass
