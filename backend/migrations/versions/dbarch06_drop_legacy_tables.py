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
1. **The v1 OpenSkill flow no longer WRITES it.** ``analytics-service/src/
   services/analytics/flows.py`` deletes + re-inserts ``AnalyticsPredictions``
   rows for the OpenSkill v1 algorithm on every recalculate.
2. **The v2 inference runner no longer MIRRORS into it.** ``analytics-service/
   src/services/ml/inference/runner.py`` deletes + re-inserts a legacy
   ``predicted_place`` mirror from the Standings-MC v2 simulation
   "so v1 integer-place consumers stay live".
3. **The read API no longer READS it.** ``analytics-service/src/services/
   analytics_read/service.py::get_predicted_places`` reads this table (falling
   back to it beneath ``standings_distribution``) and the result is surfaced as
   ``predicted_place`` in the team read + placement-delta
   (``analytics_read/flows.py`` + ``schemas/analytics_read.py``).
   Each of these must first be switched to read/write
   ``analytics.standings_distribution`` (the v2 replacement) exclusively.

4. **The ORM model still declares the table.** ``AnalyticsPredictions`` is kept
   (with a deprecation docstring) in ``shared/models/analytics/analytics.py`` so
   model<->DB stay consistent while this migration is unapplied. When this
   migration is applied, that model + its ``__all__`` entry MUST be removed in
   the same change.

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
