"""Add ``achievements.evaluation_result.encounter_id`` (series grain).

Revision ID: achenc01
Revises: trules01
Create Date: 2026-09-19 00:00:00.000000

The engine could award a user per tournament or per map, never per series, so
a series-level fact ("swept 2:0", "came back from 0:2") had to be projected
onto one of the maps. This column is the series slot; the ``user_encounter``
grain writes it and leaves ``match_id`` NULL.

The de-dup unique index has to be rebuilt rather than extended: it is a
functional index (``COALESCE(x, 0)``) and ``ON CONFLICT`` only matches an index
whose expression list is syntactically identical to the one the writer names
(``AchievementEvaluationResultRepository._DEDUP_INDEX_ELEMENTS``).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "achenc01"
down_revision: str | Sequence[str] | None = "trules01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "evaluation_result",
        sa.Column("encounter_id", sa.Integer(), nullable=True),
        schema="achievements",
    )
    op.create_foreign_key(
        "fk_eval_result_encounter_id",
        "evaluation_result",
        "encounter",
        ["encounter_id"],
        ["id"],
        source_schema="achievements",
        referent_schema="tournament",
        ondelete="CASCADE",
    )
    op.execute(
        "CREATE INDEX ix_achievements_evaluation_result_encounter_id"
        " ON achievements.evaluation_result (encounter_id)"
        " WHERE encounter_id IS NOT NULL"
    )
    op.execute("DROP INDEX IF EXISTS achievements.uq_eval_result_dedup_coalesced")
    op.execute(
        "CREATE UNIQUE INDEX uq_eval_result_dedup_coalesced ON achievements.evaluation_result"
        " (achievement_rule_id, workspace_member_id, COALESCE(tournament_id, 0),"
        " COALESCE(encounter_id, 0), COALESCE(match_id, 0))"
    )
    op.drop_constraint(
        "uq_eval_result_rule_user_tournament_match",
        "evaluation_result",
        schema="achievements",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_eval_result_rule_user_tournament_match",
        "evaluation_result",
        ["achievement_rule_id", "workspace_member_id", "tournament_id", "encounter_id", "match_id"],
        schema="achievements",
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_eval_result_rule_user_tournament_match",
        "evaluation_result",
        schema="achievements",
        type_="unique",
    )
    op.execute("DROP INDEX IF EXISTS achievements.uq_eval_result_dedup_coalesced")
    # Series-grain rows have no home in the pre-encounter shape.
    op.execute("DELETE FROM achievements.evaluation_result WHERE encounter_id IS NOT NULL")
    op.execute(
        "CREATE UNIQUE INDEX uq_eval_result_dedup_coalesced ON achievements.evaluation_result"
        " (achievement_rule_id, workspace_member_id, COALESCE(tournament_id, 0), COALESCE(match_id, 0))"
    )
    op.execute("DROP INDEX IF EXISTS achievements.ix_achievements_evaluation_result_encounter_id")
    op.drop_constraint("fk_eval_result_encounter_id", "evaluation_result", schema="achievements", type_="foreignkey")
    op.drop_column("evaluation_result", "encounter_id", schema="achievements")
    op.create_unique_constraint(
        "uq_eval_result_rule_user_tournament_match",
        "evaluation_result",
        ["achievement_rule_id", "workspace_member_id", "tournament_id", "match_id"],
        schema="achievements",
    )
