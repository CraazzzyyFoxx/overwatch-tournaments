"""dedupe + guard achievements.evaluation_result against NULL-blind duplicates

``uq_eval_result_rule_user_tournament_match`` on (achievement_rule_id,
workspace_member_id, tournament_id, match_id) does not deduplicate rows
where ``tournament_id`` and/or ``match_id`` are NULL — Postgres treats every
NULL as distinct for uniqueness purposes, so e.g. two "global" evaluation
results (``tournament_id IS NULL``, ``match_id IS NULL``) for the same
rule+member are not rejected by that constraint. The achievement evaluator
can produce exactly this shape of duplicate on re-runs.

This migration:
  1. Deletes existing NULL-blind duplicates, keeping the smallest id per
     (achievement_rule_id, workspace_member_id, COALESCE(tournament_id, 0),
     COALESCE(match_id, 0)).
  2. Adds a UNIQUE functional index on that same COALESCE'd key, built
     CONCURRENTLY (via autocommit_block) so it does not lock writes.

The old ``uq_eval_result_rule_user_tournament_match`` constraint is left in
place — harmless, and dropping it isn't required for this fix.

The DELETE runs as a single (non-batched) statement inside the normal
migration transaction: ``achievements.evaluation_result`` is nowhere near
the size of the tables touched by the iwrefac0[456] backfills, and this only
ever needs to run once (going forward, the new unique index prevents the
duplicates from reappearing).

Revision ID: perfidx05
Revises: perfidx04
Create Date: 2026-07-04 00:00:02.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "perfidx05"
down_revision: str | None = "perfidx04"
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None

_INDEX_NAME = "uq_eval_result_dedup_coalesced"


def upgrade() -> None:
    # 1. Delete NULL-blind duplicates, keeping the lowest id per dedup key.
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY
                           achievement_rule_id,
                           workspace_member_id,
                           COALESCE(tournament_id, 0),
                           COALESCE(match_id, 0)
                       ORDER BY id
                   ) AS rn
            FROM achievements.evaluation_result
        )
        DELETE FROM achievements.evaluation_result
        WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
        """
    )

    # 2. Guard against future NULL-blind duplicates. alembic's create_index cannot
    #    express a functional/COALESCE index, so raw SQL is used (same workaround as
    #    perfidx02's initcap index).
    with op.get_context().autocommit_block():
        op.execute(
            f"""
            CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX_NAME}
            ON achievements.evaluation_result (
                achievement_rule_id,
                workspace_member_id,
                COALESCE(tournament_id, 0),
                COALESCE(match_id, 0)
            )
            """
        )


def downgrade() -> None:
    # Only drops the guard index — does not (and cannot safely) resurrect the
    # duplicate rows removed above.
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS achievements.{_INDEX_NAME}")
