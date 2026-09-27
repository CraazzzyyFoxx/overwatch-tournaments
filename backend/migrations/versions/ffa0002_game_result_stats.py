"""FFA scoring: per-game ``stats jsonb``, and a stage's own columns + formula.

The organizer now decides what a game records and what it pays: the single
``encounter_game_result.score`` integer becomes a free ``stats`` object, and the
stage's ``ffa_score_points``/``ffa_score_label`` pair becomes ``ffa_columns``
(what is entered per game) plus ``ffa_formula`` (the expression over them).
Every existing stage keeps the arithmetic it had: one ``score`` column and the
formula those two numbers spelled out.

``encounter_game_result.placement`` becomes nullable with them: a place is now
stored only when the organizer entered one, and a game without places is ranked
on every read by the points the current formula pays. The downgrade refuses
while any such row exists.

``encounter_result_audit.ffa_results_json`` is left alone -- it is history, and
new rows are written in the new shape.

Revision ID: ffa0002
Revises: stjson01
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import OperationalError

# Annotated form on purpose: scripts/export_erd.py finds the chain's head with
# ``^revision:\s*str\s*=`` and silently skips a revision written any other way.
revision: str = "ffa0002"
down_revision: str | Sequence[str] | None = "stjson01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RETRYABLE_SQLSTATES = frozenset({"55P03", "40P01"})
LOCK_TIMEOUT = "3s"
LOCK_ATTEMPTS = 40
LOCK_BACKOFF_SECONDS = 6.0
_EXCLUSIVE = "tournament.encounter_game_result, tournament.stage"

#: A stage that configured nothing: one "score" column, points = score.
DEFAULT_COLUMNS = [{"key": "score", "label": "Счёт", "public": True, "better": "higher"}]
DEFAULT_FORMULA = "score"
_DEFAULT_COLUMNS_SQL = json.dumps(DEFAULT_COLUMNS, ensure_ascii=False)

#: The only formulas ``ffa_score_points`` can express again on the way back.
_REVERSIBLE_FORMULA = re.compile(r"^(?:place_pts \+ )?score(?: \* (?P<k>[0-9]+(?:\.[0-9]+)?))?$")


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
        except OperationalError as exc:
            savepoint.rollback()
            if getattr(exc.orig, "sqlstate", None) not in RETRYABLE_SQLSTATES or attempt == LOCK_ATTEMPTS:
                raise
            time.sleep(LOCK_BACKOFF_SECONDS)
        else:
            savepoint.commit()
            return


def _multiplier(points: float) -> str:
    """``score_points`` as the tail of the formula; 1 pays for no ``* 1``.

    ``repr``, never a format spec: ``{:g}`` keeps six significant digits, so
    0.3333333 would migrate to a different tournament than the one that was
    played. A whole number drops its ``.0`` so ``score * 2`` stays what the
    organizer would have written.
    """
    if points == 1:
        return ""
    exact = repr(float(points))
    return f" * {exact[:-2] if exact.endswith('.0') else exact}"


def upgrade() -> None:
    _take_locks()
    bind = op.get_bind()

    # ── results: one integer -> the organizer's object ────────────────────
    op.add_column(
        "encounter_game_result",
        sa.Column("stats", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        schema="tournament",
    )
    op.execute("UPDATE tournament.encounter_game_result SET stats = jsonb_build_object('score', score)")
    op.drop_constraint("ck_encounter_game_result_score", "encounter_game_result", schema="tournament")
    op.drop_column("encounter_game_result", "score", schema="tournament")
    op.create_check_constraint(
        "ck_encounter_game_result_stats",
        "encounter_game_result",
        "jsonb_typeof(stats) = 'object'",
        schema="tournament",
    )
    # A place is stored only when it was entered: a lobby whose formula pays
    # nothing for placement leaves it NULL and every reader ranks the game by
    # the points the CURRENT formula pays. Existing rows keep their value and
    # read back as entered.
    op.alter_column(
        "encounter_game_result",
        "placement",
        existing_type=sa.Integer(),
        nullable=True,
        schema="tournament",
    )

    # ── stage: score_points/score_label -> columns + formula ──────────────
    op.add_column(
        "stage",
        sa.Column(
            "ffa_columns",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text(f"'{_DEFAULT_COLUMNS_SQL}'::jsonb"),
        ),
        schema="tournament",
    )
    op.add_column(
        "stage",
        sa.Column("ffa_formula", sa.String(500), nullable=False, server_default=DEFAULT_FORMULA),
        schema="tournament",
    )
    # A Python loop, not one UPDATE: the formula depends on both numbers and on
    # whether the multiplier is worth writing at all, and ffa_league stages are
    # counted in single digits. ``stage_type::text``, not the enum literal:
    # ffa0001 added that label, and on a database built from scratch its
    # transaction is still the one running here -- Postgres refuses to USE an
    # enum value added in the open transaction (same constraint ffa0001 names).
    for stage_id, placement_points, score_points, score_label in bind.execute(
        sa.text(
            "SELECT id, ffa_placement_points, ffa_score_points, ffa_score_label "
            "FROM tournament.stage WHERE stage_type::text = 'ffa_league'"
        )
    ).all():
        columns = [
            {
                "key": "score",
                "label": (score_label or "").strip() or "Счёт",
                "public": True,
                "better": "higher",
            }
        ]
        tail = _multiplier(float(1 if score_points is None else score_points))
        formula = f"place_pts + score{tail}" if placement_points else f"score{tail}"
        bind.execute(
            sa.text(
                "UPDATE tournament.stage SET ffa_columns = CAST(:columns AS jsonb), ffa_formula = :formula "
                "WHERE id = :id"
            ),
            {"columns": json.dumps(columns, ensure_ascii=False), "formula": formula, "id": stage_id},
        )

    op.drop_constraint("ck_stage_ffa_score_points", "stage", schema="tournament")
    op.drop_column("stage", "ffa_score_points", schema="tournament")
    op.drop_column("stage", "ffa_score_label", schema="tournament")

    # ── the tiebreak metric that named the removed column ─────────────────
    op.execute(
        "UPDATE tournament.stage SET tiebreak_order = array_replace(tiebreak_order, 'ffa_score', 'ffa_stat:score') "
        "WHERE tiebreak_order IS NOT NULL AND 'ffa_score' = ANY(tiebreak_order)"
    )


def downgrade() -> None:
    _take_locks()
    bind = op.get_bind()

    # Every refusal is checked BEFORE the first DDL: a downgrade that cannot be
    # expressed with score_points must leave the database exactly as it was.
    restore: dict[int, tuple[float, str | None]] = {}
    for stage_id, columns, formula in bind.execute(
        sa.text("SELECT id, ffa_columns, ffa_formula FROM tournament.stage WHERE stage_type::text = 'ffa_league'")
    ).all():
        keys = [column.get("key") for column in (columns or [])]
        if keys != ["score"]:
            raise RuntimeError(f"stage {stage_id} scores by {keys}; downgrade would drop those columns")
        match = _REVERSIBLE_FORMULA.match((formula or "").strip())
        if match is None:
            raise RuntimeError(f"stage {stage_id} pays by {formula!r}; ffa_score_points cannot express it")
        # The old shape has no room for either: ``ffa_score`` always ranked
        # higher-first, and the score column was always public.
        better = columns[0].get("better", "higher")
        if better != "higher":
            raise RuntimeError(f"stage {stage_id} ranks score {better}-first; the old ffa_score tiebreak cannot")
        if not columns[0].get("public", True):
            raise RuntimeError(f"stage {stage_id} hides its score column; the old score column is always public")
        label = (columns[0].get("label") or "").strip()
        restore[stage_id] = (float(match.group("k") or 1), None if label in ("", "Счёт") else label)

    stray = bind.execute(
        sa.text("SELECT count(*) FROM tournament.encounter_game_result WHERE stats - 'score' <> '{}'::jsonb")
    ).scalar()
    if stray:
        raise RuntimeError(f"{stray} FFA results hold stats other than 'score'; downgrade would drop them")

    unplaced = bind.execute(
        sa.text("SELECT count(*) FROM tournament.encounter_game_result WHERE placement IS NULL")
    ).scalar()
    if unplaced:
        raise RuntimeError(
            f"{unplaced} FFA results have no entered place; the old column is NOT NULL and the places it "
            "would need are derived from the formula this downgrade removes"
        )

    op.add_column(
        "stage",
        sa.Column("ffa_score_points", sa.Float(), nullable=False, server_default="1"),
        schema="tournament",
    )
    op.add_column("stage", sa.Column("ffa_score_label", sa.String(32), nullable=True), schema="tournament")
    op.create_check_constraint("ck_stage_ffa_score_points", "stage", "ffa_score_points >= 0", schema="tournament")
    for stage_id, (points, label) in restore.items():
        bind.execute(
            sa.text("UPDATE tournament.stage SET ffa_score_points = :points, ffa_score_label = :label WHERE id = :id"),
            {"points": points, "label": label, "id": stage_id},
        )
    op.drop_column("stage", "ffa_formula", schema="tournament")
    op.drop_column("stage", "ffa_columns", schema="tournament")
    op.execute(
        "UPDATE tournament.stage SET tiebreak_order = array_replace(tiebreak_order, 'ffa_stat:score', 'ffa_score') "
        "WHERE tiebreak_order IS NOT NULL AND 'ffa_stat:score' = ANY(tiebreak_order)"
    )

    op.add_column(
        "encounter_game_result",
        sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
        schema="tournament",
    )
    op.execute(
        "UPDATE tournament.encounter_game_result SET score = COALESCE(round((stats ->> 'score')::numeric), 0)::int"
    )
    op.drop_constraint("ck_encounter_game_result_stats", "encounter_game_result", schema="tournament")
    op.drop_column("encounter_game_result", "stats", schema="tournament")
    op.create_check_constraint(
        "ck_encounter_game_result_score", "encounter_game_result", "score >= 0", schema="tournament"
    )
    op.alter_column(
        "encounter_game_result",
        "placement",
        existing_type=sa.Integer(),
        nullable=False,
        schema="tournament",
    )
