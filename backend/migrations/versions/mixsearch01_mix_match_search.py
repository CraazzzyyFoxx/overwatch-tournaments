"""``stats.match_search``: a pickup mix round's match, looked up by its players.

One row per recorded round of a discipline with a match searcher, enrolled by the stats worker. The worker asks the
module's source for the private matches the round's linked players played between Start and Record and files the one
that fits as an ordinary ``stats.match_fetch``. Undo deletes the round's encounter and the row with it.

Downgrade drops the table; the imports it filed stay.

Revision ID: mixsearch01
Revises: mixfetch01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "mixsearch01"
down_revision: str | Sequence[str] | None = "mixfetch01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "match_search",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "workspace_id",
            sa.BigInteger(),
            sa.ForeignKey("workspace.id", name="fk_match_search_workspace", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "discipline",
            sa.String(32),
            sa.ForeignKey("catalog.discipline.code", name="fk_match_search_discipline"),
            nullable=False,
        ),
        sa.Column(
            "encounter_id",
            sa.BigInteger(),
            sa.ForeignKey("encounter.encounter.id", name="fk_match_search_encounter", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "found",
                "not_found",
                "stopped",
                native_enum=False,
                create_constraint=True,
                name="ck_match_search_status",
                length=16,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("external_id", sa.String(128), nullable=True),
        sa.UniqueConstraint("encounter_id", name="uq_match_search_encounter"),
        schema="stats",
    )
    op.create_index("ix_match_search_due", "match_search", ["status", "next_attempt_at"], schema="stats")


def downgrade() -> None:
    op.drop_table("match_search", schema="stats")
