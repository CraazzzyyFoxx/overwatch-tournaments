"""drop legacy tables — GATED (analytics.predictions v1)

╔══════════════════════════════════════════════════════════════════════════════════════╗
║  ⚠  DO NOT APPLY THIS MIGRATION YET.  IT IS INTENTIONALLY GATED.                        ║
║                                                                                        ║
║  It drops ``analytics.predictions`` (the v1 integer predicted-place table). At the     ║
║  time of writing that table is STILL an active read/write path, so applying this now    ║
║  WILL break prod (UndefinedTable across the v1 flow, the v2 mirror, and the read API).  ║
╚══════════════════════════════════════════════════════════════════════════════════════╝

Dropped by ``upgrade()``:
  * ``analytics.predictions`` (``AnalyticsPredictions`` v1)

PART 2 investigation verdicts
=============================
This migration is the "legacy drops" half of the DB-arch pass. Each candidate
was grepped across every service first:

  * ``achievements.achievement`` + ``achievements.user`` (old Achievement /
    AchievementUser) — ALREADY DROPPED. ``k1f3g5h9i0j1`` migrated their data
    into ``rule`` + ``evaluation_result`` and ``l2g4h6i0j1k2`` dropped both
    tables; both are in-chain ancestors of the current head, so the tables do
    not exist at head. Nothing to drop here. The now-dead ORM models
    (``Achievement``, ``AchievementUser``) and their last guarded reference in
    ``app-service/services/admin/user_merge.py`` were removed as a code-only
    change alongside this migration (no DDL).

  * ``analytics.predictions`` (this migration) — STILL ACTIVE, hence GATED.

PRECONDITIONS — ALL must hold on prod before this may be applied
================================================================
The analytics-service code migration (commit ``0b9206d7``) already satisfied the
code-side preconditions 1-4: the v1 OpenSkill write in ``analytics/flows.py`` and
the v2 mirror in ``ml/inference/runner.py`` are removed; ``get_predicted_places``
now derives ``predicted_place = round(mean_position)`` solely from
``analytics.standings_distribution`` (v2); and the ``AnalyticsPredictions`` model
+ its ``__all__`` entry are removed from ``shared/models/analytics/analytics.py``.

The ONLY remaining gate is deployment ordering: that migrated analytics-service
code must be DEPLOYED to prod and verified (no reads/writes of ``analytics.
predictions``) BEFORE this drop runs — otherwise a still-running old container
would hit ``UndefinedTable``. Apply only in the same maintenance window as the
Phase-1 deploy, with ``OWT_APPLY_PREDICTIONS_DROP=1``.

``downgrade()`` re-creates the table (empty). The v1 flow / v2 mirror repopulate
it on the next recalculate/inference run, so a rollback restores a working v1
read path without a data backfill.

Revision ID: dbarch06
Revises: dbarch04b
Create Date: 2026-07-04
"""

from __future__ import annotations

import os
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "dbarch06"
down_revision: Union[str, None] = "dbarch04b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # GATED — fail-closed (see dbarch04b for the rationale). analytics.predictions
    # v1 is still actively written (analytics/flows + ml runner mirror) and read
    # (get_predicted_places -> predicted_place API), so `alembic upgrade head`
    # must NOT drop it. The drop runs only under OWT_APPLY_PREDICTIONS_DROP=1,
    # set once v1 has no writers/readers left; otherwise this is a no-op stamp.
    if os.environ.get("OWT_APPLY_PREDICTIONS_DROP") != "1":
        return

    # Dropping the table drops its FK constraints + FK indexes with it.
    op.drop_table("predictions", schema="analytics")


def downgrade() -> None:
    # Re-create the v1 predictions table (TimeStampIntegerMixin shape). It comes
    # back empty; the v1 OpenSkill flow + the v2 mirror repopulate it on the next
    # recalculate/inference run.
    op.create_table(
        "predictions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tournament_id", sa.BigInteger(), nullable=False),
        sa.Column("algorithm_id", sa.BigInteger(), nullable=False),
        sa.Column("team_id", sa.BigInteger(), nullable=False),
        sa.Column("predicted_place", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tournament_id"], ["tournament.tournament.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["algorithm_id"], ["analytics.algorithms.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["team_id"], ["tournament.team.id"], ondelete="CASCADE"
        ),
        schema="analytics",
    )
    op.create_index(
        "ix_analytics_predictions_tournament_id",
        "predictions",
        ["tournament_id"],
        schema="analytics",
    )
    op.create_index(
        "ix_analytics_predictions_algorithm_id",
        "predictions",
        ["algorithm_id"],
        schema="analytics",
    )
    op.create_index(
        "ix_analytics_predictions_team_id",
        "predictions",
        ["team_id"],
        schema="analytics",
    )
