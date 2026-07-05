"""challonge consolidation — CONTRACT phase: DROP the legacy Challonge columns + table

╔══════════════════════════════════════════════════════════════════════════════════════╗
║  ⚠  DO NOT APPLY THIS MIGRATION YET.  IT IS INTENTIONALLY GATED.                        ║
║                                                                                        ║
║  This is the destructive contract half of the Challonge consolidation. It drops the    ║
║  six legacy columns and the whole ``challonge_team`` table. At the time of writing      ║
║  those are STILL an active read/write path, so applying this now WILL break prod.       ║
╚══════════════════════════════════════════════════════════════════════════════════════╝

Dropped by ``upgrade()``:
  * ``tournament.tournament.challonge_id`` / ``challonge_slug``
  * ``tournament."group".challonge_id``    / ``challonge_slug``
  * ``tournament.stage.challonge_id``       / ``challonge_slug``
  * ``tournament.encounter.challonge_id``
  * ``tournament.challonge_team``           (whole table + its 3 perfidx03 FK indexes)

PRECONDITIONS — ALL must hold on prod before this may be applied
================================================================
1. **parser-service is done with the legacy columns.** parser-service still owns a
   near-identical *duplicate* of the Challonge sync engine (``parser-service/src/services/
   challonge/sync.py`` + ``services/team/flows.py`` + ``services/encounter/*``) that READS and
   WRITES every one of these legacy columns. The "parser migration" that removes this
   duplicate is planned but NOT started. Dropping these columns while parser still references
   them is an immediate ``UndefinedColumn`` crash across match-log / encounter flows.

2. **tournament-service readers/writers have been migrated off the legacy columns.** Still
   live in ``tournament-service`` at the time of writing:
     - ``services/challonge/sync.py``: ``discover_sources`` / ``_collect_legacy_import_sources``
       seed ``challonge_source`` FROM the legacy Tournament/Stage/Group columns; the export
       path and ``list_active_challonge_tournament_ids`` GATE on ``encounter.challonge_id`` /
       ``tournament.challonge_id``; ``_resolve_export_target`` / ``_resolve_winner_challonge_id``
       fall back to ``encounter.challonge_id`` / ``challonge_team``.
     - ``services/admin/tournament.py``: the tournament→Challonge link entry-point WRITES
       ``tournament.challonge_id`` / ``challonge_slug`` (it does not create a
       ``challonge_source`` directly — discovery does that lazily on the next import).
     - ``services/tournament/flows.py`` serialization (``to_pydantic`` / ``to_pydantic_group``)
       and the ``TournamentRead`` / ``TournamentGroupRead`` / ``StageRead`` schemas EXPOSE
       ``challonge_id`` / ``challonge_slug`` in the public API — an API-contract dependency the
       frontend may consume.
     - ``services/team/service.py::get_by_tournament_challonge_id`` reads ``challonge_team``.
   Each of these must first be switched to read/write ``challonge_source`` /
   ``challonge_participant_mapping`` / ``challonge_match_mapping`` (and the admin entry-point
   must create a ``challonge_source`` row), preserving behavior exactly.

3. **The ORM model still declares these columns/table.** They are kept (with deprecation
   comments) in ``shared/models/tournament/{tournament,stage,encounter,challonge}.py`` so
   model↔DB stay consistent while this migration is unapplied. When this migration is applied,
   those model attributes and the ``Team.challonge`` relationship + ``schemas.team.ChallongeTeam``
   (and the app-service / balancer-service model re-exports) MUST be removed in the same change.

4. **Mapping-table parity verified on prod.** Run ``dbarch04`` (the expand backfill) first,
   then confirm zero orphans, e.g.:
     - every ``encounter.challonge_id IS NOT NULL`` has a ``challonge_match_mapping`` row;
     - every ``challonge_team`` row has a ``challonge_participant_mapping`` row;
     - every Tournament/Stage/Group with a non-null ``challonge_id`` has a ``challonge_source`` row.
   Only when those counts are 0 is the legacy data fully represented in the normalized tables.

``downgrade()`` re-creates the columns/table/indexes and best-effort re-backfills them FROM
the mapping tables (using the FROM-clause-only UPDATE pattern), so a rollback restores a
working legacy read path. Group/challonge_team re-derivation is best-effort (documented inline).

Revision ID: dbarch04b
Revises: dbarch05
Create Date: 2026-07-04
"""

from __future__ import annotations

import os
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "dbarch04b"
down_revision: Union[str, None] = "dbarch05"
branch_labels = None
depends_on = None


_CHALLONGE_TEAM_INDEXES = (
    ("ix_tournament_challonge_team_team_id", "team_id"),
    ("ix_tournament_challonge_team_tournament_id", "tournament_id"),
    ("ix_tournament_challonge_team_group_id", "group_id"),
)


def upgrade() -> None:
    # GATED — fail-closed. This migration is on the linear chain so `alembic
    # upgrade head` reaches (and version-stamps) it, but the destructive drops
    # only run when explicitly opted in via OWT_APPLY_CHALLONGE_DROP=1. Without
    # the flag this is a no-op stamp, so a normal deploy reaches head WITHOUT
    # dropping the still-live legacy Challonge columns/table. Only set the flag
    # once the preconditions in this module's docstring hold (parser migration
    # done, tournament-service readers/writers migrated, model attrs removed,
    # mapping-table parity verified). If it was already stamped as a no-op, the
    # real drop must be authored as a fresh follow-up migration (alembic will
    # not re-run an applied revision).
    if os.environ.get("OWT_APPLY_CHALLONGE_DROP") != "1":
        return

    # Order is irrelevant for column drops (no cross-references), but drop the table last.
    op.drop_column("encounter", "challonge_id", schema="tournament")

    op.drop_column("stage", "challonge_slug", schema="tournament")
    op.drop_column("stage", "challonge_id", schema="tournament")

    op.drop_column("tournament", "challonge_slug", schema="tournament")
    op.drop_column("tournament", "challonge_id", schema="tournament")

    # NOTE: group.challonge_id/challonge_slug are intentionally NOT dropped. That
    # column stores Challonge's per-group `match.group_id` used to route matches to
    # a local TournamentGroup; it has no challonge_source equivalent (sources are
    # per-bracket, keyed by stage_id) and is still actively read/written by both
    # tournament-service and parser-service. Dropping it needs a dedicated mapping
    # table first (separate future work).

    # Dropping the table drops its FK constraints + the three perfidx03 indexes with it.
    op.drop_table("challonge_team", schema="tournament")


def downgrade() -> None:
    # 1. Re-create the legacy columns (all nullable, matching the pre-drop model).
    op.add_column(
        "tournament",
        sa.Column("challonge_id", sa.Integer(), nullable=True),
        schema="tournament",
    )
    op.add_column(
        "tournament",
        sa.Column("challonge_slug", sa.String(), nullable=True),
        schema="tournament",
    )
    # (group.challonge_id/slug are never dropped by upgrade() — nothing to restore.)
    op.add_column(
        "stage",
        sa.Column("challonge_id", sa.Integer(), nullable=True),
        schema="tournament",
    )
    op.add_column(
        "stage",
        sa.Column("challonge_slug", sa.String(), nullable=True),
        schema="tournament",
    )
    op.add_column(
        "encounter",
        sa.Column("challonge_id", sa.Integer(), nullable=True),
        schema="tournament",
    )

    # 2. Re-create the challonge_team table + its perfidx03 FK indexes.
    op.create_table(
        "challonge_team",
        # Identity so re-created table can accept inserts (the reverse-backfill below
        # and the app both omit id). The original mixin used a BigInteger identity PK.
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("challonge_id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.BigInteger(), nullable=False),
        sa.Column("group_id", sa.BigInteger(), nullable=True),
        sa.Column("tournament_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["tournament.group.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["tournament.team.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournament.tournament.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="tournament",
    )
    for index_name, column in _CHALLONGE_TEAM_INDEXES:
        op.create_index(index_name, "challonge_team", [column], schema="tournament")

    # 3. Best-effort reverse backfill FROM the normalized mapping tables so the restored legacy
    #    read path works again. FROM-clause-only UPDATE pattern (target only in SET/WHERE).
    conn = op.get_bind()

    conn.execute(sa.text("""
        UPDATE tournament.tournament t
        SET challonge_id = cs.challonge_tournament_id,
            challonge_slug = cs.slug
        FROM tournament.challonge_source cs
        WHERE cs.tournament_id = t.id
          AND cs.source_type = 'tournament'
    """))
    conn.execute(sa.text("""
        UPDATE tournament.stage s
        SET challonge_id = cs.challonge_tournament_id,
            challonge_slug = cs.slug
        FROM tournament.challonge_source cs
        WHERE cs.stage_id = s.id
          AND cs.source_type = 'stage'
    """))
    # group.challonge_id/slug are NOT touched by upgrade() (they hold Challonge's
    # per-group match-routing id, not a source id) — so downgrade must NOT overwrite
    # them from challonge_source either.
    conn.execute(sa.text("""
        UPDATE tournament.encounter e
        SET challonge_id = mm.challonge_match_id
        FROM tournament.challonge_match_mapping mm
        WHERE mm.encounter_id = e.id
    """))
    # challonge_team re-derivation is best-effort: group_id is recovered by matching the
    # source's stage to a group on that stage (may be NULL for tournament-scoped sources).
    conn.execute(sa.text("""
        INSERT INTO tournament.challonge_team
            (challonge_id, team_id, group_id, tournament_id, created_at)
        SELECT DISTINCT ON (cs.tournament_id, pm.challonge_participant_id, pm.team_id)
            pm.challonge_participant_id,
            pm.team_id,
            (
                SELECT g.id
                FROM tournament."group" g
                WHERE g.stage_id = cs.stage_id
                ORDER BY g.id
                LIMIT 1
            ),
            cs.tournament_id,
            now()
        FROM tournament.challonge_participant_mapping pm
        JOIN tournament.challonge_source cs ON cs.id = pm.source_id
        ORDER BY cs.tournament_id, pm.challonge_participant_id, pm.team_id, pm.id
    """))
