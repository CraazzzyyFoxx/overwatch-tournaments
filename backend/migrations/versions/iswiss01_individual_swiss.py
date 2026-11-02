"""Individual Swiss: the ``individual_swiss`` stage type and the personal standings tables.

``tournament.stage`` gains ``pairing_mode`` / ``playoff_team_count`` (NULL for every other
stage type); ``tournament.player_standing`` holds one row per player per stage and
``tournament.player_standing_pin`` the organizer's fixed places in it.

``stagetype`` gains ``individual_swiss`` as a LABEL only, added outside the migration's
transaction (``autocommit_block``): PostgreSQL refuses to use a value added to an enum
inside the transaction that added it, and nothing here writes one.

Downgrade drops the tables and columns; the enum label stays (PostgreSQL cannot drop one).

Revision ID: iswiss01
Revises: mixsearch01
"""

from __future__ import annotations

import time
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.exc import OperationalError

# Annotated form on purpose: scripts/export_erd.py finds the chain's head with
# ``^revision:\s*str\s*=`` and silently skips a revision written any other way.
revision: str = "iswiss01"
down_revision: str | Sequence[str] | None = "mixsearch01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RETRYABLE_SQLSTATES = frozenset({"55P03", "40P01"})
LOCK_TIMEOUT = "3s"
LOCK_ATTEMPTS = 40
LOCK_BACKOFF_SECONDS = 6.0
_EXCLUSIVE = "tournament.stage"


def _take_locks() -> None:
    """Take the stage table's lock before altering it, retrying a busy table.

    Each attempt is its own SAVEPOINT: a cancelled or deadlocked statement aborts the
    transaction alembic wraps the migration in, and rolling the savepoint back both
    restores that transaction and releases whatever the attempt locked. ``SET LOCAL``
    is issued outside the savepoint so a rollback does not also roll back the timeout.
    """
    bind = op.get_bind()
    bind.execute(sa.text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
    for attempt in range(1, LOCK_ATTEMPTS + 1):
        savepoint = bind.begin_nested()
        try:
            bind.execute(sa.text(f"LOCK TABLE {_EXCLUSIVE} IN ACCESS EXCLUSIVE MODE"))
        except OperationalError as exc:
            savepoint.rollback()
            if getattr(exc.orig, "sqlstate", None) not in RETRYABLE_SQLSTATES or attempt == LOCK_ATTEMPTS:
                raise
            time.sleep(LOCK_BACKOFF_SECONDS)
        else:
            savepoint.commit()
            return


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE tournament.stagetype ADD VALUE IF NOT EXISTS 'individual_swiss'")
    _take_locks()

    op.add_column("stage", sa.Column("pairing_mode", sa.String(16), nullable=True), schema="tournament")
    op.add_column("stage", sa.Column("playoff_team_count", sa.Integer(), nullable=True), schema="tournament")
    op.create_check_constraint(
        "ck_stage_pairing_mode",
        "stage",
        "pairing_mode IS NULL OR pairing_mode IN ('score', 'balance')",
        schema="tournament",
    )
    op.create_check_constraint(
        "ck_stage_playoff_team_count",
        "stage",
        "playoff_team_count IS NULL OR playoff_team_count >= 1",
        schema="tournament",
    )

    op.create_table(
        "player_standing",
        *_timestamps(),
        sa.Column("tournament_id", sa.BigInteger(), nullable=False),
        sa.Column("stage_id", sa.BigInteger(), nullable=False),
        sa.Column("registration_id", sa.BigInteger(), nullable=True),
        sa.Column("workspace_member_id", sa.BigInteger(), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("points", sa.Float(), server_default="0", nullable=False),
        sa.Column("wins", sa.Integer(), server_default="0", nullable=False),
        sa.Column("draws", sa.Integer(), server_default="0", nullable=False),
        sa.Column("losses", sa.Integer(), server_default="0", nullable=False),
        sa.Column("matches_played", sa.Integer(), server_default="0", nullable=False),
        sa.Column("maps_won", sa.Float(), server_default="0", nullable=False),
        sa.Column("maps_lost", sa.Float(), server_default="0", nullable=False),
        sa.Column("buchholz", sa.Float(), server_default="0", nullable=False),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("is_qualified", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_captain", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_pinned", sa.Boolean(), server_default="false", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournament.tournament.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["stage_id"], ["tournament.stage.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["registration_id"], ["registration.registration.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_member_id"], ["workspace_member.id"]),
        sa.UniqueConstraint("stage_id", "workspace_member_id", name="uq_player_standing_stage_member"),
        schema="tournament",
    )
    op.create_index("ix_player_standing_tournament_id", "player_standing", ["tournament_id"], schema="tournament")

    op.create_table(
        "player_standing_pin",
        *_timestamps(),
        sa.Column("stage_id", sa.BigInteger(), nullable=False),
        sa.Column("workspace_member_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["stage_id"], ["tournament.stage.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_member_id"], ["workspace_member.id"]),
        sa.CheckConstraint("position >= 1", name="ck_player_standing_pin_position"),
        sa.UniqueConstraint("stage_id", "workspace_member_id", name="uq_player_standing_pin_stage_member"),
        schema="tournament",
    )


def downgrade() -> None:
    op.drop_table("player_standing_pin", schema="tournament")
    op.drop_table("player_standing", schema="tournament")
    op.drop_constraint("ck_stage_playoff_team_count", "stage", schema="tournament")
    op.drop_constraint("ck_stage_pairing_mode", "stage", schema="tournament")
    op.drop_column("stage", "playoff_team_count", schema="tournament")
    op.drop_column("stage", "pairing_mode", schema="tournament")
