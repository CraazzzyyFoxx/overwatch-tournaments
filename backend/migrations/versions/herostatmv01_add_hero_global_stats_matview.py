"""add matches.mv_hero_global_stats materialized view

Precomputes the global "best across all players + global per-10min average"
per (hero, stat) that powers the comparison block on GET /users/{id}/heroes.
The on-demand query scanned all of matches.statistics with a window function
over the full eligible set joined to 5 tables, and blew past statement_timeout
on a cache miss. This view holds the result; the endpoint just SELECTs from it.

The view body uses the deferred-metadata-join rewrite: pick the best row per
(hero, name) on the slim eligible set first, then join the 5 metadata tables
only for the ~(#heroes x #stats) winners; the per-10min average is a separate
hash aggregate. Refresh happens out-of-band (app-worker, REFRESH ... CONCURRENTLY).

Created WITH NO DATA — the first refresh populates it. The endpoint degrades
gracefully (per-user stats without the global comparison) until then.

NOTE: matches.statistics.name stores the LogStatsName member NAME (e.g.
'HeroTimePlayed'), not its value ('hero_time_played') — raw predicates here use
the stored label.

Revision ID: herostatmv01
Revises: statperf001
Create Date: 2026-06-20 00:00:01.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "herostatmv01"
down_revision: str | None = "statperf001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_CREATE_MATVIEW = """
CREATE MATERIALIZED VIEW matches.mv_hero_global_stats AS
WITH qualified AS (
    SELECT DISTINCT s.match_id, s.user_id, s.hero_id
    FROM matches.statistics s
    WHERE s.round = 0 AND s.name = 'HeroTimePlayed' AND s.value > 60
),
eligible AS (
    SELECT st.match_id, st.user_id, st.hero_id, st.name, st.value
    FROM matches.statistics st
    JOIN qualified q
      ON q.match_id = st.match_id AND q.user_id = st.user_id AND q.hero_id = st.hero_id
    WHERE st.round = 0 AND st.hero_id IS NOT NULL
),
agg AS (
    SELECT e.hero_id, e.name,
           sum(e.value) AS sum_value,
           sum(m."time") AS sum_time
    FROM eligible e
    JOIN matches.match m ON m.id = e.match_id
    GROUP BY e.hero_id, e.name
),
ranked AS (
    SELECT e.hero_id, e.name, e.match_id, e.user_id, e.value,
           row_number() OVER (
             PARTITION BY e.hero_id, e.name
             ORDER BY e.value * CASE WHEN e.name IN (
                          'Deaths', 'DamageTaken', 'EnvironmentalDeaths',
                          'ShotsMissed', 'DamageFB', 'Performance'
                      ) THEN -1.0 ELSE 1.0 END DESC,
                      e.match_id DESC
           ) AS rn
    FROM eligible e
),
best AS (
    SELECT r.hero_id, r.name, r.value AS best_value,
           m.encounter_id,
           mp.name AS map_name, mp.image_path AS map_image_path,
           t.name AS tournament_name,
           u.name AS username
    FROM ranked r
    JOIN matches.match m         ON m.id = r.match_id
    JOIN overwatch.map mp        ON mp.id = m.map_id
    JOIN tournament.encounter enc ON enc.id = m.encounter_id
    JOIN tournament.tournament t  ON t.id = enc.tournament_id
    JOIN players."user" u        ON u.id = r.user_id
    WHERE r.rn = 1
)
SELECT
    a.name AS name,
    a.hero_id AS hero_id,
    b.best_value AS best_value,
    (a.sum_value / nullif(a.sum_time, 0)) * 600 AS avg,
    jsonb_build_object(
        'encounter_id', b.encounter_id,
        'map_name', b.map_name,
        'map_image_path', b.map_image_path,
        'tournament_name', b.tournament_name,
        'username', b.username
    ) AS metadata
FROM agg a
JOIN best b ON b.hero_id = a.hero_id AND b.name = a.name
WITH NO DATA
"""

# Unique index is required for REFRESH MATERIALIZED VIEW CONCURRENTLY.
_CREATE_INDEX = (
    "CREATE UNIQUE INDEX ix_mv_hero_global_stats_name_hero "
    "ON matches.mv_hero_global_stats (name, hero_id)"
)


def upgrade() -> None:
    op.execute(_CREATE_MATVIEW)
    op.execute(_CREATE_INDEX)


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS matches.mv_hero_global_stats")
