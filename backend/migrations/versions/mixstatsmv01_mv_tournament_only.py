"""``stats.mv_entity_global_stats`` counts tournament games only (D4: mix stats live only inside the mix).

A mix-owned encounter (``tournament_id IS NULL``) used to feed the per-hero averages, and when a mix game held a
hero/stat's best value the ``best`` join to ``tournament.tournament`` dropped that hero/stat from the view entirely.
The mix games are now excluded in ``qualified``, before ranking; ``eligible`` joins ``qualified``, so everything
downstream sees tournament games only. Everything else in the definition is unchanged.

The view is dropped and recreated populated, with its unique index (``REFRESH ... CONCURRENTLY`` needs it). Downgrade
restores the previous definition.

Revision ID: mixstatsmv01
Revises: impactv202
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "mixstatsmv01"
down_revision: str | Sequence[str] | None = "impactv202"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Copied, not imported: a migration keeps meaning what it meant when it ran. The previous definition
#: (``stats01_stats.NATIVE_MV_SELECT``), restored by ``downgrade``.
_PREVIOUS_SELECT = """
WITH qualified AS (
 SELECT DISTINCT f.match_id,f.workspace_member_id,f.entity_id FROM stats.fact f
 JOIN stats.match m ON m.id=f.match_id
 JOIN stats.stat_def d ON d.id=f.stat_id AND d.discipline=m.discipline AND d.code='hero_time_played'
 WHERE f.segment=0 AND f.value>60
), eligible AS (
 SELECT f.match_id,f.workspace_member_id,f.entity_id,f.stat_id,f.value,m.discipline,d.code
 FROM stats.fact f JOIN qualified q ON q.match_id=f.match_id AND q.workspace_member_id=f.workspace_member_id
 AND q.entity_id=f.entity_id JOIN stats.match m ON m.id=f.match_id
 JOIN stats.stat_def d ON d.id=f.stat_id AND d.discipline=m.discipline
 JOIN catalog.entity ce ON ce.id=f.entity_id AND ce.kind='character' AND ce.discipline=m.discipline
 WHERE f.segment=0 AND f.entity_id IS NOT NULL
), agg AS (
 SELECT e.discipline,e.entity_id,e.stat_id,
 sum(e.value ORDER BY e.match_id,e.workspace_member_id) sum_value,
 sum(m.duration_s ORDER BY e.match_id,e.workspace_member_id) sum_time
 FROM eligible e JOIN stats.match m ON m.id=e.match_id GROUP BY e.discipline,e.entity_id,e.stat_id
), ranked AS (
 SELECT e.*,row_number() OVER (PARTITION BY e.discipline,e.entity_id,e.stat_id ORDER BY e.value *
 CASE WHEN e.code IN ('deaths','damage_taken','environmental_deaths','shots_missed','damage_fb','performance')
 THEN -1.0 ELSE 1.0 END DESC,e.match_id DESC,e.workspace_member_id ASC) rn FROM eligible e
), best AS (
 SELECT r.discipline,r.entity_id,r.stat_id,r.value best_value,m.encounter_id,mp.name map_name,
 mp.image_path map_image_path,t.name tournament_name,u.name username
 FROM ranked r JOIN stats.match m ON m.id=r.match_id
 JOIN catalog.entity mp ON mp.id=m.map_entity_id AND mp.kind='map' AND mp.discipline=m.discipline
 JOIN encounter.encounter enc ON enc.id=m.encounter_id AND enc.workspace_id=m.workspace_id AND enc.discipline=m.discipline
 JOIN tournament.tournament t ON t.id=enc.tournament_id
 JOIN workspace_member wm ON wm.id=r.workspace_member_id AND wm.workspace_id=m.workspace_id
 JOIN players."user" u ON u.id=wm.player_id WHERE r.rn=1
)
SELECT a.discipline,a.stat_id,a.entity_id,b.best_value,(a.sum_value/nullif(a.sum_time,0))*600 AS avg,
 jsonb_build_object('encounter_id',b.encounter_id,'map_name',b.map_name,'map_image_path',b.map_image_path,
 'tournament_name',b.tournament_name,'username',b.username) AS metadata
FROM agg a JOIN best b ON b.discipline=a.discipline AND b.entity_id=a.entity_id AND b.stat_id=a.stat_id
"""

#: The previous definition with one join added to ``qualified``: the match's encounter must have a tournament.
_TOURNAMENT_ONLY_SELECT = _PREVIOUS_SELECT.replace(
    " JOIN stats.match m ON m.id=f.match_id\n JOIN stats.stat_def d ON d.id=f.stat_id AND d.discipline=m.discipline "
    "AND d.code='hero_time_played'\n",
    " JOIN stats.match m ON m.id=f.match_id\n"
    " JOIN encounter.encounter qe ON qe.id=m.encounter_id AND qe.tournament_id IS NOT NULL\n"
    " JOIN stats.stat_def d ON d.id=f.stat_id AND d.discipline=m.discipline AND d.code='hero_time_played'\n",
    1,
)
assert _TOURNAMENT_ONLY_SELECT != _PREVIOUS_SELECT


def _recreate(select: str) -> None:
    op.execute("DROP MATERIALIZED VIEW stats.mv_entity_global_stats")
    op.execute(f"CREATE MATERIALIZED VIEW stats.mv_entity_global_stats AS {select}")
    op.execute(
        "CREATE UNIQUE INDEX uq_mv_entity_global_stats ON stats.mv_entity_global_stats(discipline,stat_id,entity_id)"
    )


def upgrade() -> None:
    _recreate(_TOURNAMENT_ONLY_SELECT)


def downgrade() -> None:
    _recreate(_PREVIOUS_SELECT)
