"""identity refactor: achievements.evaluation_result/override on workspace_member_id

Model change already shipped in ``f6ec5b80`` (feat(achievements): results/
overrides on workspace_member_id (drop user_id)). This migration performs the
matching schema change for both ``achievements.evaluation_result`` and
``achievements.override``:

- adds ``workspace_member_id`` (FK ``public.workspace_member.id``, CASCADE);
- backfills it from each row's ``(workspace_id, user_id)`` pair by joining to
  the ``workspace_member`` row for that player in that workspace;
- safety net: for any row whose ``(workspace_id, user_id)`` has no
  ``workspace_member`` yet (unlikely post-Part5, but not guaranteed), creates
  one — deduped via ``ON CONFLICT (workspace_id, player_id) DO NOTHING`` — and
  re-backfills only the still-NULL rows;
- for ``evaluation_result`` only: drops the old unique constraint
  ``uq_eval_result_rule_user_tournament_match`` (on ``achievement_rule_id,
  user_id, tournament_id, match_id``) so the same name can be reused for the
  new constraint over ``workspace_member_id`` — the model kept the historical
  constraint name unchanged, it just repoints the second column;
- sets ``workspace_member_id`` NOT NULL, creates its FK and index, and (for
  ``evaluation_result``) the new unique constraint;
- drops the old ``user_id`` column (and its now-orphaned single-column index)
  — dropping the column also drops its own FK automatically. ``workspace_id``
  is NOT touched; the model still carries it.

All backfill UPDATEs put ``workspace_member`` in the ``FROM`` clause and only
ever reference the UPDATE target (``a``/``p``) in the ``WHERE`` clause, never
inside a ``JOIN ... ON`` — the pattern that broke ``iwrefac06``'s first cut
(see ``9b84a103``).

Downgrade reverses both tables: re-adds ``user_id`` (nullable Integer, FK
``players.user.id`` CASCADE, matching the column's original physical type),
backfills it from ``workspace_member.player_id``, sets it NOT NULL, restores
the original FK name and single-column index, restores the old unique
constraint on ``evaluation_result`` (dropping the new one first to free the
shared name), then drops the new index/FK/column. Caveat: any
``workspace_member`` rows created by this migration's safety-net INSERT are
left in place on downgrade (same rationale as ``iwrefac06``) — they are
harmless rows in a table this migration does not own.

Revision ID: iwrefac08
Revises: iwrefac07
Create Date: 2026-07-02
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "iwrefac08"
down_revision: Union[str, None] = "iwrefac07"
branch_labels = None
depends_on = None


def _expand_and_backfill(table: str) -> None:
    """Add ``workspace_member_id`` and backfill it from ``(workspace_id, user_id)``."""
    op.add_column(
        table,
        sa.Column("workspace_member_id", sa.BigInteger(), nullable=True),
        schema="achievements",
    )

    op.execute(
        f"""
        UPDATE achievements.{table} a
        SET workspace_member_id = wm.id
        FROM workspace_member wm
        WHERE wm.player_id = a.user_id
          AND wm.workspace_id = a.workspace_id
        """
    )

    # Safety net: create workspace_member rows for any (workspace, player) pairing
    # that doesn't have one yet, deduped per (workspace_id, player_id).
    op.execute(
        f"""
        INSERT INTO workspace_member (workspace_id, player_id, created_at)
        SELECT DISTINCT a.workspace_id, a.user_id, now()
        FROM achievements.{table} a
        LEFT JOIN workspace_member wm
            ON wm.workspace_id = a.workspace_id AND wm.player_id = a.user_id
        WHERE wm.id IS NULL
        ON CONFLICT (workspace_id, player_id) DO NOTHING
        """
    )

    op.execute(
        f"""
        UPDATE achievements.{table} a
        SET workspace_member_id = wm.id
        FROM workspace_member wm
        WHERE wm.player_id = a.user_id
          AND wm.workspace_id = a.workspace_id
          AND a.workspace_member_id IS NULL
        """
    )


def _contract(table: str, fk_name: str, index_name: str) -> None:
    """Enforce NOT NULL, create the new FK/index, drop the old ``user_id`` column."""
    op.alter_column(
        table,
        "workspace_member_id",
        nullable=False,
        schema="achievements",
    )
    op.create_foreign_key(
        fk_name,
        table,
        "workspace_member",
        ["workspace_member_id"],
        ["id"],
        source_schema="achievements",
        referent_schema="public",
        ondelete="CASCADE",
    )
    op.create_index(
        index_name,
        table,
        ["workspace_member_id"],
        schema="achievements",
    )

    # Drops the old user_id -> players.user.id FK automatically along with the
    # column.
    op.drop_column(table, "user_id", schema="achievements")


def upgrade() -> None:
    # --- evaluation_result ---
    _expand_and_backfill("evaluation_result")

    # Old single-column index on user_id; dropped explicitly (rather than left to
    # the implicit column-drop cascade) so downgrade can recreate it precisely.
    op.drop_index(
        "ix_achievements_eval_result_user_id",
        table_name="evaluation_result",
        schema="achievements",
    )
    # Same name as the model's new constraint below — must be dropped first while
    # user_id (its second column) still exists, freeing the name for reuse.
    op.drop_constraint(
        "uq_eval_result_rule_user_tournament_match",
        "evaluation_result",
        schema="achievements",
        type_="unique",
    )

    _contract(
        "evaluation_result",
        "fk_evaluation_result_workspace_member",
        "ix_achievements_evaluation_result_workspace_member_id",
    )

    op.create_unique_constraint(
        "uq_eval_result_rule_user_tournament_match",
        "evaluation_result",
        ["achievement_rule_id", "workspace_member_id", "tournament_id", "match_id"],
        schema="achievements",
    )

    # --- override ---
    _expand_and_backfill("override")

    op.drop_index(
        "ix_achievements_override_user_id",
        table_name="override",
        schema="achievements",
    )

    _contract(
        "override",
        "fk_override_workspace_member",
        "ix_achievements_override_workspace_member_id",
    )


def downgrade() -> None:
    # --- override (reverse order: last upgraded, first downgraded) ---
    op.add_column(
        "override",
        sa.Column("user_id", sa.Integer(), nullable=True),
        schema="achievements",
    )
    op.execute(
        """
        UPDATE achievements.override a
        SET user_id = wm.player_id
        FROM workspace_member wm
        WHERE wm.id = a.workspace_member_id
        """
    )
    op.alter_column(
        "override",
        "user_id",
        nullable=False,
        schema="achievements",
    )
    op.create_foreign_key(
        "override_user_id_fkey",
        "override",
        "user",
        ["user_id"],
        ["id"],
        source_schema="achievements",
        referent_schema="players",
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_achievements_override_user_id",
        "override",
        ["user_id"],
        schema="achievements",
    )

    op.drop_index(
        "ix_achievements_override_workspace_member_id",
        table_name="override",
        schema="achievements",
    )
    op.drop_constraint(
        "fk_override_workspace_member", "override", schema="achievements", type_="foreignkey"
    )
    op.alter_column(
        "override",
        "workspace_member_id",
        nullable=True,
        schema="achievements",
    )
    op.drop_column("override", "workspace_member_id", schema="achievements")

    # --- evaluation_result ---
    op.add_column(
        "evaluation_result",
        sa.Column("user_id", sa.Integer(), nullable=True),
        schema="achievements",
    )
    op.execute(
        """
        UPDATE achievements.evaluation_result a
        SET user_id = wm.player_id
        FROM workspace_member wm
        WHERE wm.id = a.workspace_member_id
        """
    )
    op.alter_column(
        "evaluation_result",
        "user_id",
        nullable=False,
        schema="achievements",
    )
    op.create_foreign_key(
        "evaluation_result_user_id_fkey",
        "evaluation_result",
        "user",
        ["user_id"],
        ["id"],
        source_schema="achievements",
        referent_schema="players",
        ondelete="CASCADE",
    )

    # Same name-reuse concern as upgrade: drop the workspace_member_id-keyed
    # constraint before recreating the user_id-keyed one under the same name.
    op.drop_constraint(
        "uq_eval_result_rule_user_tournament_match",
        "evaluation_result",
        schema="achievements",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_eval_result_rule_user_tournament_match",
        "evaluation_result",
        ["achievement_rule_id", "user_id", "tournament_id", "match_id"],
        schema="achievements",
    )
    op.create_index(
        "ix_achievements_eval_result_user_id",
        "evaluation_result",
        ["user_id"],
        schema="achievements",
    )

    op.drop_index(
        "ix_achievements_evaluation_result_workspace_member_id",
        table_name="evaluation_result",
        schema="achievements",
    )
    op.drop_constraint(
        "fk_evaluation_result_workspace_member",
        "evaluation_result",
        schema="achievements",
        type_="foreignkey",
    )
    op.alter_column(
        "evaluation_result",
        "workspace_member_id",
        nullable=True,
        schema="achievements",
    )
    op.drop_column("evaluation_result", "workspace_member_id", schema="achievements")
