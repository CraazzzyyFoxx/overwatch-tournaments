"""add_achievement_engine_tables

Revision ID: j0e2f4g8h9i0
Revises: i9d1e3f7g8h9
Create Date: 2026-04-09 22:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "j0e2f4g8h9i0"
down_revision: Union[str, None] = "i9d1e3f7g8h9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- achievement_rule ---
    op.create_table(
        "rule",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description_ru", sa.String(), nullable=False),
        sa.Column("description_en", sa.String(), nullable=False),
        sa.Column("image_url", sa.String(), nullable=True),
        sa.Column("hero_id", sa.Integer(), nullable=True),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("grain", sa.String(), nullable=False),
        sa.Column("condition_tree", sa.JSON(), nullable=False),
        sa.Column("depends_on", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("rule_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("min_tournament_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["hero_id"], ["overwatch.hero.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("workspace_id", "slug", name="uq_achievement_rule_workspace_slug"),
        schema="achievements",
    )
    op.create_index(
        "ix_achievements_rule_workspace_id",
        "rule",
        ["workspace_id"],
        schema="achievements",
    )
    op.create_index(
        "ix_achievements_rule_slug",
        "rule",
        ["slug"],
        schema="achievements",
    )

    # --- evaluation_result ---
    op.create_table(
        "evaluation_result",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("achievement_rule_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tournament_id", sa.Integer(), nullable=True),
        sa.Column("match_id", sa.Integer(), nullable=True),
        sa.Column(
            "qualified_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("evidence_json", sa.JSON(), nullable=True),
        sa.Column("rule_version", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["achievement_rule_id"], ["achievements.rule.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["players.user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tournament_id"], ["tournament.tournament.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["match_id"], ["matches.match.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "achievement_rule_id",
            "user_id",
            "tournament_id",
            "match_id",
            name="uq_eval_result_rule_user_tournament_match",
        ),
        schema="achievements",
    )
    op.create_index(
        "ix_achievements_eval_result_rule_id",
        "evaluation_result",
        ["achievement_rule_id"],
        schema="achievements",
    )
    op.create_index(
        "ix_achievements_eval_result_user_id",
        "evaluation_result",
        ["user_id"],
        schema="achievements",
    )
    op.create_index(
        "ix_achievements_eval_result_tournament_id",
        "evaluation_result",
        ["tournament_id"],
        schema="achievements",
    )
    op.create_index(
        "ix_achievements_eval_result_run_id",
        "evaluation_result",
        ["run_id"],
        schema="achievements",
    )

    # --- override ---
    op.create_table(
        "override",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("achievement_rule_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tournament_id", sa.Integer(), nullable=True),
        sa.Column("match_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("granted_by", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["achievement_rule_id"], ["achievements.rule.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["players.user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tournament_id"], ["tournament.tournament.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["match_id"], ["matches.match.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by"], ["auth.user.id"], ondelete="SET NULL"),
        schema="achievements",
    )
    op.create_index(
        "ix_achievements_override_rule_id",
        "override",
        ["achievement_rule_id"],
        schema="achievements",
    )
    op.create_index(
        "ix_achievements_override_user_id",
        "override",
        ["user_id"],
        schema="achievements",
    )

    # --- evaluation_run ---
    op.create_table(
        "evaluation_run",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.func.gen_random_uuid(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("trigger", sa.String(), nullable=False),
        sa.Column("tournament_id", sa.Integer(), nullable=True),
        sa.Column("rules_evaluated", sa.Integer(), server_default="0", nullable=False),
        sa.Column("results_created", sa.Integer(), server_default="0", nullable=False),
        sa.Column("results_removed", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(), server_default="running", nullable=False),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tournament_id"], ["tournament.tournament.id"], ondelete="SET NULL"
        ),
        schema="achievements",
    )
    op.create_index(
        "ix_achievements_eval_run_workspace_id",
        "evaluation_run",
        ["workspace_id"],
        schema="achievements",
    )


def downgrade() -> None:
    op.drop_table("evaluation_run", schema="achievements")
    op.drop_table("override", schema="achievements")
    op.drop_table("evaluation_result", schema="achievements")
    op.drop_table("rule", schema="achievements")
