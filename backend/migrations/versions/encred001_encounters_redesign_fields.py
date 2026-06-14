"""encounters_redesign_fields

Revision ID: encred001
Revises: mergeheads001
Create Date: 2026-05-18
"""

import sqlalchemy as sa
from alembic import op

revision = "encred001"
down_revision = "mergeheads001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "encounter",
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        schema="tournament",
    )
    op.add_column(
        "encounter",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        schema="tournament",
    )
    op.add_column(
        "encounter",
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        schema="tournament",
    )
    op.add_column(
        "encounter",
        sa.Column("current_map_index", sa.Integer(), nullable=True),
        schema="tournament",
    )
    op.create_index("ix_encounter_scheduled_at", "encounter", ["scheduled_at"], schema="tournament")
    op.create_index("ix_encounter_started_at", "encounter", ["started_at"], schema="tournament")
    op.create_index("ix_encounter_ended_at", "encounter", ["ended_at"], schema="tournament")

    op.create_table(
        "encounter_saved_view",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("auth_user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("filters_json", sa.JSON(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["auth_user_id"], ["auth.user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "auth_user_id",
            "name",
            name="uq_encounter_saved_view_workspace_user_name",
        ),
        schema="tournament",
    )
    op.create_index(
        "ix_encounter_saved_view_workspace_id",
        "encounter_saved_view",
        ["workspace_id"],
        schema="tournament",
    )
    op.create_index(
        "ix_encounter_saved_view_auth_user_id",
        "encounter_saved_view",
        ["auth_user_id"],
        schema="tournament",
    )
    op.create_index(
        "ix_encounter_saved_view_workspace_user",
        "encounter_saved_view",
        ["workspace_id", "auth_user_id"],
        schema="tournament",
    )


def downgrade() -> None:
    op.drop_index("ix_encounter_saved_view_workspace_user", table_name="encounter_saved_view", schema="tournament")
    op.drop_index("ix_encounter_saved_view_auth_user_id", table_name="encounter_saved_view", schema="tournament")
    op.drop_index("ix_encounter_saved_view_workspace_id", table_name="encounter_saved_view", schema="tournament")
    op.drop_table("encounter_saved_view", schema="tournament")

    op.drop_index("ix_encounter_ended_at", table_name="encounter", schema="tournament")
    op.drop_index("ix_encounter_started_at", table_name="encounter", schema="tournament")
    op.drop_index("ix_encounter_scheduled_at", table_name="encounter", schema="tournament")
    op.drop_column("encounter", "current_map_index", schema="tournament")
    op.drop_column("encounter", "ended_at", schema="tournament")
    op.drop_column("encounter", "started_at", schema="tournament")
    op.drop_column("encounter", "scheduled_at", schema="tournament")
