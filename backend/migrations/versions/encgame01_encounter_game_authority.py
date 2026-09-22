"""``tournament.encounter_game``: the series position is the unit of result.

Revision ID: encgame01
Revises: draftot01
Create Date: 2026-09-22 00:00:00.000000

Creates ``encounter_game`` (one row per position of an encounter's series, with
the accepted score and who accepted it), hangs the per-game decision columns off
``encounter_result_audit``, and re-keys ``encounter_map_report`` from
``(encounter_id, map_id, map_index, team_id)`` onto ``(game_id, side)`` — a
series can play the same map twice, so the map was never a key.

**This migration is ONLINE-ONLY.** It SELECTs the legacy per-map rows out of the
database and converts them; it cannot run against an empty schema plan or be
reasoned about from the DDL alone. The conversion itself is a pure function,
``shared.domain.encounter_game_backfill.plan_games``, so the rules live under
test rather than inside this file.

What it converts
----------------
* ``encounter_map_report`` rows, where no captain match covers the position: two
  agreeing sides become a ``confirmed`` game, two disagreeing sides a
  ``disputed`` one, a lone claim ``awaiting_result``.
* ``matches.match`` rows with ``source='captain_report'``: these were written by
  the old ``submit_map_report`` reconciliation purely to carry a score, i.e.
  only once both captains had agreed, so one IS an accepted result (spec §13B)
  and confirms its position whatever reports survived beside it. They are not
  observations of a log, so they become games and are **deleted** (spec §5.1: a
  Match is what a log observed, never what the tournament decided). The deleted
  ids are logged — that log is the dev manifest; production Stage A produces its
  own.
* ``pick_ban_entry.status='played'`` → ``'picked'``. "Played" is now the game's
  state, not the pick's. The ``played`` label stays on the PostgreSQL type
  ``tournament.pickbanentrystatus``: PostgreSQL cannot drop an enum label, and
  rebuilding the type would need an exclusive lock on every table using it.
* Live encounter scores are re-materialised from the confirmed games, for
  encounters that are not yet ``COMPLETED``. A finalized encounter keeps its
  official score — ``shared/services/encounter/finalize.py`` stays its only
  writer.

Ambiguity aborts, it never guesses. A position claimed by two different maps, or
legacy ``map_index=0`` rows that play one map twice with no position to separate
them, raises ``RuntimeError`` and rolls the whole transaction back; an operator
sets ``map_index`` by hand and re-runs (spec §13B).

Downgrade rebuilds the four legacy report columns from ``encounter_game`` (and
the encounter's sides, for ``team_id``) and drops everything this revision
added. It does **not** restore the deleted ``captain_report`` matches, and it
does not restore ``pick_ban_entry.status='played'`` — both are information this
revision deliberately dropped. Per spec §13D there is no lossy automatic
downgrade after cutover; this is the pre-cutover dev path.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from shared.domain.encounter_game_backfill import (
    BackfillPlan,
    EncounterSides,
    LegacyCaptainMatch,
    LegacyReport,
    plan_games,
)

revision: str = "encgame01"
down_revision: str | Sequence[str] | None = "draftot01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = logging.getLogger("alembic.runtime.migration")

GAME_STATES = ("planned", "awaiting_result", "disputed", "confirmed", "cancelled")
RESULT_SOURCES = ("captain_agreement", "admin", "admin_log")
AUDIT_GAME_ACTIONS = ("game_confirm", "game_correct", "game_cancel")

_LOAD_REPORTS = """
SELECT id, encounter_id, map_id, map_index, team_id, home_score, away_score, created_at
FROM tournament.encounter_map_report
"""

_LOAD_MATCHES = """
SELECT id, encounter_id, map_id, map_index, home_score, away_score, created_at
FROM matches.match
WHERE source = 'captain_report'
"""


def _plan(conn) -> BackfillPlan:
    reports = [
        LegacyReport(
            id=row.id,
            encounter_id=row.encounter_id,
            map_id=row.map_id,
            map_index=row.map_index or 0,
            team_id=row.team_id,
            home_score=row.home_score,
            away_score=row.away_score,
            created_at=row.created_at,
        )
        for row in conn.execute(sa.text(_LOAD_REPORTS))
    ]
    matches = [
        LegacyCaptainMatch(
            id=row.id,
            encounter_id=row.encounter_id,
            map_id=row.map_id,
            map_index=row.map_index,
            home_score=row.home_score,
            away_score=row.away_score,
            created_at=row.created_at,
        )
        for row in conn.execute(sa.text(_LOAD_MATCHES))
    ]
    encounter_ids = sorted({row.encounter_id for row in reports} | {match.encounter_id for match in matches})
    sides: dict[int, EncounterSides] = {}
    if encounter_ids:
        rows = conn.execute(
            sa.text(
                "SELECT id, home_team_id, away_team_id FROM tournament.encounter WHERE id IN :ids"
            ).bindparams(sa.bindparam("ids", expanding=True)),
            {"ids": encounter_ids},
        )
        sides = {row.id: EncounterSides(home_team_id=row.home_team_id, away_team_id=row.away_team_id) for row in rows}
    return plan_games(reports, matches, sides)


def _insert_games(conn, plan: BackfillPlan) -> dict[tuple[int, int], int]:
    """Insert the planned games; return ``planner key -> new id``."""
    if not plan.games:
        return {}
    conn.execute(
        sa.text(
            """
            INSERT INTO tournament.encounter_game
                (encounter_id, position, map_id, state, accepted_home_score, accepted_away_score,
                 result_source, confirmed_at)
            VALUES
                (:encounter_id, :position, :map_id, CAST(:state AS tournament.encountergamestate),
                 :accepted_home_score, :accepted_away_score,
                 CAST(:result_source AS tournament.encountergameresultsource), :confirmed_at)
            """
        ),
        [
            {
                "encounter_id": game.encounter_id,
                "position": game.position,
                "map_id": game.map_id,
                "state": game.state,
                "accepted_home_score": game.accepted_home_score,
                "accepted_away_score": game.accepted_away_score,
                # Every accepted score here came from the two captains agreeing,
                # directly or through the match row that agreement wrote.
                "result_source": "captain_agreement" if game.state == "confirmed" else None,
                "confirmed_at": game.confirmed_at,
            }
            for game in plan.games
        ],
    )
    # The table was created empty two statements ago, so reading it back is the
    # whole mapping — cheaper and less dialect-dependent than executemany
    # RETURNING.
    return {
        (row.encounter_id, row.position): row.id
        for row in conn.execute(sa.text("SELECT id, encounter_id, position FROM tournament.encounter_game"))
    }


def upgrade() -> None:
    conn = op.get_bind()

    op.execute(
        "CREATE TYPE tournament.encountergamestate AS ENUM ("
        + ", ".join(f"'{value}'" for value in GAME_STATES)
        + ")"
    )
    op.execute(
        "CREATE TYPE tournament.encountergameresultsource AS ENUM ("
        + ", ".join(f"'{value}'" for value in RESULT_SOURCES)
        + ")"
    )
    # Labels only — PostgreSQL forbids USING a value added to a pre-existing
    # enum inside the transaction that added it, and nothing here writes one.
    for action in AUDIT_GAME_ACTIONS:
        op.execute(f"ALTER TYPE tournament.encounterresultauditaction ADD VALUE IF NOT EXISTS '{action}'")

    op.create_table(
        "encounter_game",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("encounter_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("map_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "state",
            postgresql.ENUM(*GAME_STATES, name="encountergamestate", schema="tournament", create_type=False),
            server_default="planned",
            nullable=False,
        ),
        sa.Column("accepted_home_score", sa.Integer(), nullable=True),
        sa.Column("accepted_away_score", sa.Integer(), nullable=True),
        sa.Column(
            "result_source",
            postgresql.ENUM(
                *RESULT_SOURCES, name="encountergameresultsource", schema="tournament", create_type=False
            ),
            nullable=True,
        ),
        sa.Column("result_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("position >= 1", name="ck_encounter_game_position"),
        sa.CheckConstraint(
            "accepted_home_score IS NULL OR accepted_home_score >= 0", name="ck_encounter_game_home_score"
        ),
        sa.CheckConstraint(
            "accepted_away_score IS NULL OR accepted_away_score >= 0", name="ck_encounter_game_away_score"
        ),
        sa.CheckConstraint(
            "state != 'confirmed' OR (accepted_home_score IS NOT NULL AND accepted_away_score IS NOT NULL "
            "AND result_source IS NOT NULL AND confirmed_at IS NOT NULL)",
            name="ck_encounter_game_confirmed_shape",
        ),
        sa.ForeignKeyConstraint(["encounter_id"], ["tournament.encounter.id"], ondelete="CASCADE"),
        # RESTRICT: deleting a catalog map must not erase a played position's identity.
        sa.ForeignKeyConstraint(["map_id"], ["overwatch.map.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        schema="tournament",
    )
    op.create_index(
        op.f("ix_tournament_encounter_game_encounter_id"),
        "encounter_game",
        ["encounter_id"],
        unique=False,
        schema="tournament",
    )
    op.create_index(
        op.f("ix_tournament_encounter_game_map_id"),
        "encounter_game",
        ["map_id"],
        unique=False,
        schema="tournament",
    )
    # A cancelled game keeps its position as history; the live series has at
    # most one game per position.
    op.create_index(
        "uq_encounter_game_encounter_position",
        "encounter_game",
        ["encounter_id", "position"],
        unique=True,
        schema="tournament",
        postgresql_where=sa.text("state != 'cancelled'"),
    )

    op.add_column(
        "encounter_result_audit", sa.Column("game_id", sa.BigInteger(), nullable=True), schema="tournament"
    )
    op.add_column(
        "encounter_result_audit", sa.Column("game_result_version", sa.Integer(), nullable=True), schema="tournament"
    )
    op.add_column("encounter_result_audit", sa.Column("reason", sa.Text(), nullable=True), schema="tournament")
    op.create_index(
        op.f("ix_tournament_encounter_result_audit_game_id"),
        "encounter_result_audit",
        ["game_id"],
        unique=False,
        schema="tournament",
    )
    op.create_foreign_key(
        "fk_tournament_encounter_result_audit_game_id",
        "encounter_result_audit",
        "encounter_game",
        ["game_id"],
        ["id"],
        source_schema="tournament",
        referent_schema="tournament",
        ondelete="CASCADE",
    )

    plan = _plan(conn)
    if plan.conflicts:
        raise RuntimeError("encgame01 cannot map legacy results unambiguously:\n" + "\n".join(plan.conflicts))
    game_ids = _insert_games(conn, plan)
    log.info("encgame01: planned %d games from legacy per-map results", len(plan.games))

    op.add_column("encounter_map_report", sa.Column("game_id", sa.BigInteger(), nullable=True), schema="tournament")
    op.add_column(
        "encounter_map_report", sa.Column("side", sa.String(length=16), nullable=True), schema="tournament"
    )
    if plan.report_keys:
        conn.execute(
            sa.text("UPDATE tournament.encounter_map_report SET game_id = :game_id, side = :side WHERE id = :id"),
            [
                {"id": report_id, "game_id": game_ids[key], "side": side}
                for report_id, (key, side) in plan.report_keys.items()
            ],
        )
    if plan.orphan_report_ids:
        # Their team is no longer either side of the encounter, so there is no
        # game and no side they could belong to.
        log.info("encgame01: dropping %d orphaned map reports", len(plan.orphan_report_ids))
        conn.execute(
            sa.text("DELETE FROM tournament.encounter_map_report WHERE id IN :ids").bindparams(
                sa.bindparam("ids", expanding=True)
            ),
            {"ids": plan.orphan_report_ids},
        )

    op.alter_column("encounter_map_report", "game_id", nullable=False, schema="tournament")
    op.alter_column("encounter_map_report", "side", nullable=False, schema="tournament")
    op.create_foreign_key(
        "fk_tournament_encounter_map_report_game_id",
        "encounter_map_report",
        "encounter_game",
        ["game_id"],
        ["id"],
        source_schema="tournament",
        referent_schema="tournament",
        ondelete="CASCADE",
    )
    op.create_index(
        op.f("ix_tournament_encounter_map_report_game_id"),
        "encounter_map_report",
        ["game_id"],
        unique=False,
        schema="tournament",
    )
    op.create_unique_constraint(
        "uq_encounter_map_report_game_side", "encounter_map_report", ["game_id", "side"], schema="tournament"
    )
    op.create_check_constraint(
        "ck_encounter_map_report_side", "encounter_map_report", "side IN ('home', 'away')", schema="tournament"
    )

    # DROP COLUMN takes every index and constraint on the dropped columns with
    # it. Naming them would fail on the long-lived databases, whose index names
    # predate ``initial_v6``'s ``op.f()`` spelling (see ``statdrop01``).
    for name in ("encounter_id", "map_id", "map_index", "team_id"):
        op.drop_column("encounter_map_report", name, schema="tournament")

    if plan.deleted_match_ids:
        # The manifest for dev: these rows never observed a log, they only
        # carried a score that now lives on the game.
        log.info(
            "encgame01: deleting %d captain_report matches: %s",
            len(plan.deleted_match_ids),
            plan.deleted_match_ids,
        )
        conn.execute(
            sa.text("DELETE FROM matches.match WHERE id IN :ids").bindparams(
                sa.bindparam("ids", expanding=True)
            ),
            {"ids": plan.deleted_match_ids},
        )

    op.execute("UPDATE tournament.pick_ban_entry SET status = 'picked' WHERE status = 'played'")

    # Live series scores now come from the games. A COMPLETED encounter keeps
    # its official score; finalize.py stays its only writer.
    op.execute(
        """
        UPDATE tournament.encounter e
        SET home_score = s.home_wins, away_score = s.away_wins
        FROM (
          SELECT encounter_id,
                 COUNT(*) FILTER (WHERE accepted_home_score > accepted_away_score) AS home_wins,
                 COUNT(*) FILTER (WHERE accepted_away_score > accepted_home_score) AS away_wins
          FROM tournament.encounter_game WHERE state = 'confirmed' GROUP BY encounter_id
        ) s
        WHERE s.encounter_id = e.id AND e.status <> 'COMPLETED'
        """
    )


def downgrade() -> None:
    """Rebuild the legacy report key from the games, then drop the new objects.

    Deleted ``captain_report`` matches are NOT restored, and pick/ban entries
    that were ``played`` stay ``picked``: both were dropped on purpose going up.
    """
    op.add_column("encounter_map_report", sa.Column("encounter_id", sa.BigInteger(), nullable=True), schema="tournament")
    op.add_column("encounter_map_report", sa.Column("map_id", sa.BigInteger(), nullable=True), schema="tournament")
    op.add_column(
        "encounter_map_report",
        sa.Column("map_index", sa.Integer(), server_default="0", nullable=True),
        schema="tournament",
    )
    op.add_column("encounter_map_report", sa.Column("team_id", sa.BigInteger(), nullable=True), schema="tournament")
    op.execute(
        """
        UPDATE tournament.encounter_map_report r
        SET encounter_id = g.encounter_id,
            map_id = g.map_id,
            map_index = g.position,
            team_id = CASE WHEN r.side = 'home' THEN e.home_team_id ELSE e.away_team_id END
        FROM tournament.encounter_game g
        JOIN tournament.encounter e ON e.id = g.encounter_id
        WHERE g.id = r.game_id
        """
    )
    # A report on a map-less (``planned``) game, or on an encounter whose side
    # is empty, has no legacy shape to go back to.
    op.execute(
        "DELETE FROM tournament.encounter_map_report "
        "WHERE encounter_id IS NULL OR map_id IS NULL OR team_id IS NULL"
    )
    for name in ("encounter_id", "map_id", "map_index", "team_id"):
        op.alter_column("encounter_map_report", name, nullable=False, schema="tournament")

    op.create_foreign_key(
        None,
        "encounter_map_report",
        "encounter",
        ["encounter_id"],
        ["id"],
        source_schema="tournament",
        referent_schema="tournament",
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        None,
        "encounter_map_report",
        "map",
        ["map_id"],
        ["id"],
        source_schema="tournament",
        referent_schema="overwatch",
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        None,
        "encounter_map_report",
        "team",
        ["team_id"],
        ["id"],
        source_schema="tournament",
        referent_schema="tournament",
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        "ck_encounter_map_report_index", "encounter_map_report", "map_index >= 0", schema="tournament"
    )
    op.create_unique_constraint(
        "uq_encounter_map_report_encounter_map_index_team",
        "encounter_map_report",
        ["encounter_id", "map_id", "map_index", "team_id"],
        schema="tournament",
    )
    op.create_index(
        op.f("ix_tournament_encounter_map_report_encounter_id"),
        "encounter_map_report",
        ["encounter_id"],
        unique=False,
        schema="tournament",
    )
    op.create_index(
        op.f("ix_tournament_encounter_map_report_map_id"),
        "encounter_map_report",
        ["map_id"],
        unique=False,
        schema="tournament",
    )
    op.create_index(
        op.f("ix_tournament_encounter_map_report_team_id"),
        "encounter_map_report",
        ["team_id"],
        unique=False,
        schema="tournament",
    )

    op.drop_constraint("ck_encounter_map_report_side", "encounter_map_report", schema="tournament", type_="check")
    op.drop_constraint(
        "uq_encounter_map_report_game_side", "encounter_map_report", schema="tournament", type_="unique"
    )
    op.drop_constraint(
        "fk_tournament_encounter_map_report_game_id",
        "encounter_map_report",
        schema="tournament",
        type_="foreignkey",
    )
    op.drop_index(
        op.f("ix_tournament_encounter_map_report_game_id"), table_name="encounter_map_report", schema="tournament"
    )
    op.drop_column("encounter_map_report", "side", schema="tournament")
    op.drop_column("encounter_map_report", "game_id", schema="tournament")

    op.drop_constraint(
        "fk_tournament_encounter_result_audit_game_id",
        "encounter_result_audit",
        schema="tournament",
        type_="foreignkey",
    )
    op.drop_index(
        op.f("ix_tournament_encounter_result_audit_game_id"),
        table_name="encounter_result_audit",
        schema="tournament",
    )
    op.drop_column("encounter_result_audit", "reason", schema="tournament")
    op.drop_column("encounter_result_audit", "game_result_version", schema="tournament")
    op.drop_column("encounter_result_audit", "game_id", schema="tournament")

    op.drop_index("uq_encounter_game_encounter_position", table_name="encounter_game", schema="tournament")
    op.drop_index(op.f("ix_tournament_encounter_game_map_id"), table_name="encounter_game", schema="tournament")
    op.drop_index(
        op.f("ix_tournament_encounter_game_encounter_id"), table_name="encounter_game", schema="tournament"
    )
    op.drop_table("encounter_game", schema="tournament")
    # The three ``game_*`` labels stay on ``encounterresultauditaction``:
    # PostgreSQL cannot drop an enum label.
    op.execute("DROP TYPE tournament.encountergameresultsource")
    op.execute("DROP TYPE tournament.encountergamestate")
