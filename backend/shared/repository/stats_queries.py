"""Pushdown-capable native observations; authorization/visibility belongs to each reader."""

import sqlalchemy as sa

from shared import models

__all__ = ("player_facts", "team_scores", "match_context")


def player_facts(*, discipline: str | None) -> sa.Subquery:
    """Player facts at their original segment/entity grain, including historical members; ``None`` spans every game."""
    f, m, d = models.StatsFact, models.StatsMatch, models.StatDef
    wm, e, et = models.WorkspaceMember, models.Encounter, models.EncounterTeam
    mt = models.StatsMatchTeam
    return (
        sa.select(
            *f.__table__.c,
            d.code.label("stat_code"),
            m.workspace_id,
            m.discipline,
            wm.player_id,
            et.team_id.label("tournament_team_id"),
            m.encounter_id,
            e.tournament_id,
            m.duration_s,
            m.map_entity_id,
            m.mode_entity_id,
            mt.source_position,
        )
        .select_from(f)
        .join(m, m.id == f.match_id)
        .join(d, sa.and_(d.id == f.stat_id, d.discipline == m.discipline))
        .join(wm, sa.and_(wm.id == f.workspace_member_id, wm.workspace_id == m.workspace_id))
        # The match/encounter owner of match_team and encounter.team is already pinned by the composite FKs
        # (fk_fact_team, fk_match_team_match, fk_match_team_encounter_team). Restating it as join predicates makes
        # the planner multiply their selectivities as independent, estimate one row and nest-loop millions.
        # Those FKs (on NOT NULL keys) also guarantee exactly one match_team/encounter.team row per fact, so the outer
        # joins return the same rows. Outer, PostgreSQL drops them when a reader projects neither ``source_position``
        # nor ``tournament_team_id``, and never estimates the still-correlated two-column match_team join below the
        # fact rows; inner, it read as one row per match team instead of hundreds, and a one-player hero compare
        # probed every match team of the game past the 30s statement timeout.
        .outerjoin(mt, sa.and_(mt.match_id == f.match_id, mt.encounter_team_id == f.encounter_team_id))
        .join(e, sa.and_(e.id == m.encounter_id, e.workspace_id == m.workspace_id, e.discipline == m.discipline))
        .outerjoin(et, et.id == f.encounter_team_id)
        .where(f.workspace_member_id.is_not(None), *([m.discipline == discipline] if discipline is not None else []))
        .subquery()
    )


def team_scores(*, discipline: str, stat_code: str) -> sa.Subquery:
    """Observed whole-match team values, never the game's official result."""
    f, m, d, mt = models.StatsFact, models.StatsMatch, models.StatDef, models.StatsMatchTeam
    e, et = models.Encounter, models.EncounterTeam
    return (
        sa.select(
            f.match_id,
            f.encounter_team_id,
            mt.source_position,
            et.slot,
            et.team_id.label("tournament_team_id"),
            f.value,
        )
        .select_from(f)
        .join(m, m.id == f.match_id)
        .join(d, sa.and_(d.id == f.stat_id, d.discipline == m.discipline))
        # FK-implied owner predicates omitted for the planner, as in ``player_facts``.
        .join(mt, sa.and_(mt.match_id == f.match_id, mt.encounter_team_id == f.encounter_team_id))
        .join(e, sa.and_(e.id == m.encounter_id, e.workspace_id == m.workspace_id, e.discipline == m.discipline))
        .join(et, et.id == f.encounter_team_id)
        .where(
            m.discipline == discipline,
            d.code == stat_code,
            f.segment == 0,
            f.workspace_member_id.is_(None),
            f.entity_id.is_(None),
        )
        .subquery()
    )


def match_context(*, discipline: str | None = None) -> sa.Subquery:
    """Match headers with their real game position and encounter owner; ``None`` spans every discipline."""
    m, g, e = models.StatsMatch, models.EncounterGame, models.Encounter
    query = (
        sa.select(*m.__table__.c, g.position, e.tournament_id, e.custom_game_id)
        .select_from(m)
        .join(e, sa.and_(e.id == m.encounter_id, e.workspace_id == m.workspace_id, e.discipline == m.discipline))
        .outerjoin(
            g,
            # A hinted match may sit on a game whose map is still empty until its result applies.
            sa.and_(
                g.id == m.encounter_game_id,
                g.encounter_id == m.encounter_id,
                sa.or_(g.map_id.is_(None), g.map_id == m.map_entity_id),
            ),
        )
        .where(sa.or_(m.encounter_game_id.is_(None), g.id.is_not(None)))
    )
    if discipline is not None:
        query = query.where(m.discipline == discipline)
    return query.subquery()
