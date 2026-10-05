"""Backfill the Push/Clash map scores the match logs never carried.

Revision ID: objmap01
Revises: pgroom01
Create Date: 2026-10-05 00:00:00.000000

Every parsed Push/Clash map was stored as 0:0: the Workshop log has no result for
those modes. Re-derives them from the accepted per-map result or, failing that,
by exclusion from the completed series score -- the rules are
``shared.domain.objectiveless_maps.resolve_scores``, the same function the parser
now runs on every log and encounter completion. Undecidable maps stay 0:0.

**ONLINE-ONLY**: it reads the data it fixes. Downgrade is a no-op; the 0:0 it
overwrote was never a result.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from shared.domain.objectiveless_maps import (
    OBJECTIVELESS_GAMEMODES,
    AcceptedGame,
    LoggedMap,
    Series,
    resolve_scores,
)

revision: str = "objmap01"
down_revision: str | Sequence[str] | None = "pgroom01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = logging.getLogger("alembic.runtime.migration")

_LOAD_MATCHES = """
SELECT m.id, m.encounter_id, m.map_id, m.home_team_id, m.home_score, m.away_score, g.slug
FROM matches.match m
JOIN overwatch.map mp ON mp.id = m.map_id
JOIN overwatch.gamemode g ON g.id = mp.gamemode_id
WHERE m.encounter_id IN (
    SELECT m2.encounter_id
    FROM matches.match m2
    JOIN overwatch.map mp2 ON mp2.id = m2.map_id
    JOIN overwatch.gamemode g2 ON g2.id = mp2.gamemode_id
    WHERE g2.slug IN :slugs
)
"""

# `status` persists the enum member NAME, hence 'COMPLETED' (see Encounter.status).
_LOAD_ENCOUNTERS = """
SELECT id, home_team_id, away_team_id, status = 'COMPLETED' AS completed, home_score, away_score
FROM tournament.encounter
WHERE id IN :ids
"""

_LOAD_GAMES = """
SELECT encounter_id, map_id, accepted_home_score, accepted_away_score
FROM tournament.encounter_game
WHERE state = 'confirmed' AND format = 'duel' AND encounter_id IN :ids
"""


def upgrade() -> None:
    conn = op.get_bind()
    maps: dict[int, list[LoggedMap]] = defaultdict(list)
    for row in conn.execute(
        sa.text(_LOAD_MATCHES).bindparams(sa.bindparam("slugs", expanding=True)),
        {"slugs": sorted(OBJECTIVELESS_GAMEMODES)},
    ):
        maps[row.encounter_id].append(
            LoggedMap(
                match_id=row.id,
                map_id=row.map_id,
                home_team_id=row.home_team_id,
                home_score=row.home_score,
                away_score=row.away_score,
                objectiveless=row.slug in OBJECTIVELESS_GAMEMODES,
            )
        )
    if not maps:
        return

    ids = {"ids": sorted(maps)}
    series = {
        row.id: Series(
            home_team_id=row.home_team_id,
            away_team_id=row.away_team_id,
            completed=row.completed,
            home_score=row.home_score,
            away_score=row.away_score,
        )
        for row in conn.execute(sa.text(_LOAD_ENCOUNTERS).bindparams(sa.bindparam("ids", expanding=True)), ids)
    }
    games: dict[int, list[AcceptedGame]] = defaultdict(list)
    for row in conn.execute(sa.text(_LOAD_GAMES).bindparams(sa.bindparam("ids", expanding=True)), ids):
        games[row.encounter_id].append(
            AcceptedGame(map_id=row.map_id, home_score=row.accepted_home_score, away_score=row.accepted_away_score)
        )

    current = {m.match_id: (m.home_score, m.away_score) for rows in maps.values() for m in rows}
    updates = [
        {"id": match_id, "home": home, "away": away}
        for encounter_id, rows in maps.items()
        for match_id, (home, away) in resolve_scores(series[encounter_id], rows, games[encounter_id]).items()
        if current[match_id] != (home, away)
    ]
    if updates:
        conn.execute(sa.text("UPDATE matches.match SET home_score = :home, away_score = :away WHERE id = :id"), updates)
    log.info("objmap01: %d Push/Clash map scores filled in across %d encounters", len(updates), len(maps))


def downgrade() -> None:
    pass
