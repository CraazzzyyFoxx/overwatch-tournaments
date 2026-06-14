"""limit visible analytics algorithms

Revision ID: algonames0001
Revises: trainws0001
Create Date: 2026-05-19 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "algonames0001"
down_revision: str | Sequence[str] | None = "trainws0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE analytics.algorithms
            SET name = 'Linear', produces_shifts = true
            WHERE name = 'Linear Stable'
              AND NOT EXISTS (
                  SELECT 1 FROM analytics.algorithms WHERE name = 'Linear'
              )
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE analytics.algorithms
            SET name = 'OpenSkill + ML', produces_shifts = true
            WHERE name = 'OpenSkill+LGBM v2'
              AND NOT EXISTS (
                  SELECT 1 FROM analytics.algorithms WHERE name = 'OpenSkill + ML'
              )
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO analytics.algorithms (name, produces_shifts)
            VALUES
              ('Linear', true),
              ('Points', true),
              ('OpenSkill + ML', true)
            ON CONFLICT (name) DO UPDATE
            SET produces_shifts = true
            """
        )
    )
    op.execute(
        sa.text(
            """
            DELETE FROM analytics.algorithms
            WHERE name IN (
              'Linear Stable',
              'Linear Trend',
              'Linear Hybrid',
              'Open Skill',
              'OpenSkill+LGBM v2'
            )
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE analytics.algorithms
            SET name = 'Linear Stable', produces_shifts = true
            WHERE name = 'Linear'
              AND NOT EXISTS (
                  SELECT 1 FROM analytics.algorithms WHERE name = 'Linear Stable'
              )
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE analytics.algorithms
            SET name = 'OpenSkill+LGBM v2', produces_shifts = true
            WHERE name = 'OpenSkill + ML'
              AND NOT EXISTS (
                  SELECT 1 FROM analytics.algorithms WHERE name = 'OpenSkill+LGBM v2'
              )
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO analytics.algorithms (name, produces_shifts)
            VALUES
              ('Linear Trend', true),
              ('Linear Hybrid', true),
              ('Open Skill', true)
            ON CONFLICT (name) DO UPDATE
            SET produces_shifts = true
            """
        )
    )
