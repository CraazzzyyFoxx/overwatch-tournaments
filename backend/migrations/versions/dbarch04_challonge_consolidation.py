"""challonge consolidation — EXPAND phase: re-backfill the normalized mapping tables

Context
=======
The legacy Challonge state is spread across six columns and one whole table:

  * ``tournament.tournament.challonge_id`` / ``challonge_slug``
  * ``tournament."group".challonge_id``   / ``challonge_slug``   (legacy TournamentGroup)
  * ``tournament.stage.challonge_id``      / ``challonge_slug``
  * ``tournament.encounter.challonge_id``
  * ``tournament.challonge_team``          (whole table)

The purpose-built normalized target already exists (created + first-backfilled by
``chsync0001``, a confirmed ancestor of this head):

  * ``tournament.challonge_source``               (the bracket, scoped to tournament/stage/stage_item)
  * ``tournament.challonge_participant_mapping``  (replaces ``challonge_team``)
  * ``tournament.challonge_match_mapping``        (replaces ``encounter.challonge_id``)

Both tournament-service AND parser-service DUAL-WRITE the mapping tables alongside the
legacy columns today, and the sync engine already reads the mapping tables FIRST with the
legacy columns as a transition-period fallback. So the mapping tables are the clean target,
already populated for historical rows.

What this migration does (and does NOT do)
===========================================
This is the **EXPAND** half of an expand/contract. It ONLY re-runs ``chsync0001``'s
idempotent backfill so that any rows created *after* ``chsync0001`` ran — a tournament linked
via the admin panel but not yet imported, a stage/group/encounter/challonge_team row written
by either service before its ``challonge_source`` existed — are guaranteed to have their
``challonge_source`` / ``challonge_participant_mapping`` / ``challonge_match_mapping`` rows.

It DELIBERATELY does NOT drop the legacy columns or the ``challonge_team`` table. Those are
still an ACTIVE read/write path in BOTH services (source discovery seed, export/auto-sync
gates, API-serialization DTOs, and intentional resolver fallbacks). The destructive drop is
carried in the SEPARATE, gated ``dbarch04b_challonge_drop_legacy`` migration — read its
docstring for the preconditions that must hold on prod before it may be applied.

Safety / offline
================
Pure additive DML — every statement is ``INSERT ... SELECT ... ON CONFLICT DO NOTHING`` (or
``DO UPDATE`` with ``COALESCE`` that only fills NULLs), so re-running is a no-op and nothing
the running app has set is ever overwritten. No DDL, no index work → no ``autocommit_block``
needed; a single atomic transaction is correct here. All statements are static SQL, so this
also renders under ``alembic upgrade --sql`` offline mode.

Revision ID: dbarch04
Revises: dbarch03
Create Date: 2026-07-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "dbarch04"
down_revision: str | None = "dbarch03"
branch_labels = None
depends_on = None


# Verbatim re-run of chsync0001's backfill (idempotent). Kept identical on purpose:
# the same SELECT-from-legacy + ON CONFLICT semantics that seeded historical rows also
# catch any rows created since chsync0001. tournament."group" stays double-quoted
# ("group" is a reserved word); the tournament source is inserted first so a stage/group
# sharing the tournament's challonge_id enriches the SAME source row via COALESCE.
_BACKFILL_SOURCE_FROM_TOURNAMENT = """
    INSERT INTO tournament.challonge_source
        (tournament_id, stage_id, stage_item_id, challonge_tournament_id, slug, source_type, created_at)
    SELECT t.id, NULL, NULL, t.challonge_id, t.challonge_slug, 'tournament', now()
    FROM tournament.tournament t
    WHERE t.challonge_id IS NOT NULL
    ON CONFLICT (tournament_id, challonge_tournament_id) DO NOTHING
"""

_BACKFILL_SOURCE_FROM_STAGE = """
    INSERT INTO tournament.challonge_source
        (tournament_id, stage_id, stage_item_id, challonge_tournament_id, slug, source_type, created_at)
    SELECT
        s.tournament_id,
        s.id,
        (
            SELECT si.id
            FROM tournament.stage_item si
            WHERE si.stage_id = s.id
            ORDER BY si."order", si.id
            LIMIT 1
        ),
        s.challonge_id,
        s.challonge_slug,
        'stage',
        now()
    FROM tournament.stage s
    WHERE s.challonge_id IS NOT NULL
    ON CONFLICT (tournament_id, challonge_tournament_id) DO UPDATE
    SET stage_id = COALESCE(tournament.challonge_source.stage_id, EXCLUDED.stage_id),
        stage_item_id = COALESCE(tournament.challonge_source.stage_item_id, EXCLUDED.stage_item_id),
        slug = COALESCE(tournament.challonge_source.slug, EXCLUDED.slug)
"""

_BACKFILL_SOURCE_FROM_GROUP = """
    INSERT INTO tournament.challonge_source
        (tournament_id, stage_id, stage_item_id, challonge_tournament_id, slug, source_type, created_at)
    SELECT
        g.tournament_id,
        g.stage_id,
        (
            SELECT si.id
            FROM tournament.stage_item si
            WHERE si.stage_id = g.stage_id
            ORDER BY si."order", si.id
            LIMIT 1
        ),
        g.challonge_id,
        g.challonge_slug,
        CASE WHEN g.is_groups THEN 'group' ELSE 'playoff' END,
        now()
    FROM tournament."group" g
    WHERE g.challonge_id IS NOT NULL
    ON CONFLICT (tournament_id, challonge_tournament_id) DO UPDATE
    SET stage_id = COALESCE(tournament.challonge_source.stage_id, EXCLUDED.stage_id),
        stage_item_id = COALESCE(tournament.challonge_source.stage_item_id, EXCLUDED.stage_item_id),
        slug = COALESCE(tournament.challonge_source.slug, EXCLUDED.slug)
"""

_BACKFILL_PARTICIPANT_MAPPING = """
    INSERT INTO tournament.challonge_participant_mapping
        (source_id, challonge_participant_id, team_id, created_at)
    SELECT DISTINCT ON (src.id, ct.challonge_id)
        src.id, ct.challonge_id, ct.team_id, now()
    FROM tournament.challonge_team ct
    LEFT JOIN tournament."group" g ON g.id = ct.group_id
    JOIN tournament.challonge_source src
      ON src.tournament_id = ct.tournament_id
     AND src.challonge_tournament_id = COALESCE(g.challonge_id, (
        SELECT t.challonge_id
        FROM tournament.tournament t
        WHERE t.id = ct.tournament_id
     ))
    ORDER BY src.id, ct.challonge_id, ct.id
    ON CONFLICT (source_id, challonge_participant_id) DO NOTHING
"""

_BACKFILL_MATCH_MAPPING = """
    INSERT INTO tournament.challonge_match_mapping
        (source_id, challonge_match_id, encounter_id, created_at)
    SELECT DISTINCT ON (src.id, e.challonge_id)
        src.id, e.challonge_id, e.id, now()
    FROM tournament.encounter e
    LEFT JOIN tournament.stage s ON s.id = e.stage_id
    LEFT JOIN tournament."group" g ON g.id = e.tournament_group_id
    JOIN tournament.challonge_source src
      ON src.tournament_id = e.tournament_id
     AND src.challonge_tournament_id = COALESCE(s.challonge_id, g.challonge_id, (
        SELECT t.challonge_id
        FROM tournament.tournament t
        WHERE t.id = e.tournament_id
     ))
    WHERE e.challonge_id IS NOT NULL
    ORDER BY src.id, e.challonge_id, e.id
    ON CONFLICT (source_id, challonge_match_id) DO NOTHING
"""


def upgrade() -> None:
    conn = op.get_bind()
    # Order matters: sources must exist before the participant/match mappings that JOIN them.
    conn.execute(sa.text(_BACKFILL_SOURCE_FROM_TOURNAMENT))
    conn.execute(sa.text(_BACKFILL_SOURCE_FROM_STAGE))
    conn.execute(sa.text(_BACKFILL_SOURCE_FROM_GROUP))
    conn.execute(sa.text(_BACKFILL_PARTICIPANT_MAPPING))
    conn.execute(sa.text(_BACKFILL_MATCH_MAPPING))


def downgrade() -> None:
    # No-op: this migration is purely additive drift-catch backfill. The backfilled rows are
    # indistinguishable from rows the running app writes, and the mapping tables themselves are
    # owned by chsync0001 (which drops them on its own downgrade). Removing rows here could
    # delete live app data, so downgrade intentionally does nothing.
    pass
