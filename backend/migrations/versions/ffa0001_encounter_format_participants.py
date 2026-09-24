"""FFA encounters: encounter.format, lobby participants, per-game results.

``stagetype`` gains ``ffa_league`` as a LABEL only: PostgreSQL refuses to use a
value added to an existing enum inside the transaction that added it, and
nothing here writes one (same constraint as annstat01 / encgame01).

Revision ID: ffa0001
Revises: draftq01
"""

from __future__ import annotations

import time
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import OperationalError

# Annotated form on purpose: scripts/export_erd.py finds the chain's head with
# ``^revision:\s*str\s*=`` and silently skips a revision written any other way.
revision: str = "ffa0001"
down_revision: str | Sequence[str] | None = "draftq01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RETRYABLE_SQLSTATES = frozenset({"55P03", "40P01"})
LOCK_TIMEOUT = "3s"
LOCK_ATTEMPTS = 40
LOCK_BACKOFF_SECONDS = 6.0
_EXCLUSIVE = "tournament.encounter, tournament.encounter_game, tournament.encounter_result_audit"
_REFERENCED = "tournament.team"


def _take_locks() -> None:
    """Take every lock this revision needs, before it changes anything.

    Each attempt is its own SAVEPOINT: a cancelled or deadlocked statement
    aborts the transaction alembic wraps the migration in, and rolling the
    savepoint back both restores that transaction and releases whatever locks
    the attempt did get. ``SET LOCAL`` is issued outside the savepoint so a
    rollback does not also roll back the timeout.
    """
    bind = op.get_bind()
    bind.execute(sa.text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
    for attempt in range(1, LOCK_ATTEMPTS + 1):
        savepoint = bind.begin_nested()
        try:
            bind.execute(sa.text(f"LOCK TABLE {_EXCLUSIVE} IN ACCESS EXCLUSIVE MODE"))
            bind.execute(sa.text(f"LOCK TABLE {_REFERENCED} IN SHARE ROW EXCLUSIVE MODE"))
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
    _take_locks()
    op.execute("ALTER TYPE tournament.stagetype ADD VALUE IF NOT EXISTS 'ffa_league'")

    op.add_column(
        "encounter", sa.Column("format", sa.String(8), nullable=False, server_default="duel"), schema="tournament"
    )
    op.create_check_constraint("ck_encounter_format", "encounter", "format IN ('duel', 'ffa')", schema="tournament")
    op.create_check_constraint(
        "ck_encounter_ffa_has_no_sides",
        "encounter",
        "format = 'duel' OR (home_team_id IS NULL AND away_team_id IS NULL AND home_score = 0 AND away_score = 0)",
        schema="tournament",
    )

    op.add_column(
        "encounter_game",
        sa.Column("format", sa.String(8), nullable=False, server_default="duel"),
        schema="tournament",
    )
    op.create_check_constraint(
        "ck_encounter_game_format", "encounter_game", "format IN ('duel', 'ffa')", schema="tournament"
    )
    op.drop_constraint("ck_encounter_game_confirmed_shape", "encounter_game", schema="tournament")
    op.create_check_constraint(
        "ck_encounter_game_confirmed_shape",
        "encounter_game",
        "state != 'confirmed' OR (result_source IS NOT NULL AND confirmed_at IS NOT NULL AND (format = 'ffa' "
        "OR (accepted_home_score IS NOT NULL AND accepted_away_score IS NOT NULL)))",
        schema="tournament",
    )
    op.create_check_constraint(
        "ck_encounter_game_ffa_has_no_scores",
        "encounter_game",
        "format = 'duel' OR (accepted_home_score IS NULL AND accepted_away_score IS NULL)",
        schema="tournament",
    )

    op.create_table(
        "encounter_participant",
        *_timestamps(),
        sa.Column("encounter_id", sa.BigInteger(), nullable=False),
        sa.Column("team_id", sa.BigInteger(), nullable=False),
        sa.Column("slot", sa.Integer(), nullable=False),
        sa.CheckConstraint("slot >= 1", name="ck_encounter_participant_slot"),
        sa.ForeignKeyConstraint(["encounter_id"], ["tournament.encounter.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["tournament.team.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("encounter_id", "team_id", name="uq_encounter_participant_encounter_team"),
        sa.UniqueConstraint("encounter_id", "slot", name="uq_encounter_participant_encounter_slot"),
        sa.PrimaryKeyConstraint("id"),
        schema="tournament",
    )
    op.create_index("ix_encounter_participant_team_id", "encounter_participant", ["team_id"], schema="tournament")

    op.create_table(
        "encounter_game_result",
        *_timestamps(),
        sa.Column("game_id", sa.BigInteger(), nullable=False),
        sa.Column("encounter_id", sa.BigInteger(), nullable=False),
        sa.Column("team_id", sa.BigInteger(), nullable=False),
        sa.Column("placement", sa.Integer(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("placement >= 1", name="ck_encounter_game_result_placement"),
        sa.CheckConstraint("score >= 0", name="ck_encounter_game_result_score"),
        sa.ForeignKeyConstraint(["game_id"], ["tournament.encounter_game.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["encounter_id", "team_id"],
            ["tournament.encounter_participant.encounter_id", "tournament.encounter_participant.team_id"],
            ondelete="CASCADE",
            name="fk_encounter_game_result_participant",
        ),
        sa.UniqueConstraint("game_id", "team_id", name="uq_encounter_game_result_game_team"),
        sa.PrimaryKeyConstraint("id"),
        schema="tournament",
    )
    op.create_index(
        "ix_encounter_game_result_encounter_team",
        "encounter_game_result",
        ["encounter_id", "team_id"],
        schema="tournament",
    )

    op.alter_column("encounter_result_audit", "home_score_after", nullable=True, schema="tournament")
    op.alter_column("encounter_result_audit", "away_score_after", nullable=True, schema="tournament")
    op.add_column(
        "encounter_result_audit",
        sa.Column("ffa_results_json", postgresql.JSONB(), nullable=True),
        schema="tournament",
    )
    op.create_check_constraint(
        "ck_encounter_result_audit_after_shape",
        "encounter_result_audit",
        "(home_score_after IS NOT NULL AND away_score_after IS NOT NULL) OR ffa_results_json IS NOT NULL",
        schema="tournament",
    )


def downgrade() -> None:
    _take_locks()
    # A downgrade after the first lobby exists would drop real results; refuse
    # instead of silently losing them. The stagetype label stays: PostgreSQL
    # cannot drop an enum value without rebuilding the type (annstat01).
    lobbies = op.get_bind().execute(sa.text("SELECT count(*) FROM tournament.encounter WHERE format = 'ffa'")).scalar()
    if lobbies:
        raise RuntimeError(f"{lobbies} FFA encounters exist; downgrade would drop their results")
    op.drop_constraint("ck_encounter_result_audit_after_shape", "encounter_result_audit", schema="tournament")
    op.drop_column("encounter_result_audit", "ffa_results_json", schema="tournament")
    op.alter_column("encounter_result_audit", "away_score_after", nullable=False, schema="tournament")
    op.alter_column("encounter_result_audit", "home_score_after", nullable=False, schema="tournament")
    op.drop_table("encounter_game_result", schema="tournament")
    op.drop_table("encounter_participant", schema="tournament")
    op.drop_constraint("ck_encounter_game_ffa_has_no_scores", "encounter_game", schema="tournament")
    op.drop_constraint("ck_encounter_game_confirmed_shape", "encounter_game", schema="tournament")
    op.create_check_constraint(
        "ck_encounter_game_confirmed_shape",
        "encounter_game",
        "state != 'confirmed' OR (accepted_home_score IS NOT NULL AND accepted_away_score IS NOT NULL "
        "AND result_source IS NOT NULL AND confirmed_at IS NOT NULL)",
        schema="tournament",
    )
    op.drop_constraint("ck_encounter_game_format", "encounter_game", schema="tournament")
    op.drop_column("encounter_game", "format", schema="tournament")
    op.drop_constraint("ck_encounter_ffa_has_no_sides", "encounter", schema="tournament")
    op.drop_constraint("ck_encounter_format", "encounter", schema="tournament")
    op.drop_column("encounter", "format", schema="tournament")
