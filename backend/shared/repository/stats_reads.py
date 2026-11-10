"""Explicit native observation reads shared by public serializers.

These are read contexts, not mapped legacy matches. Visibility is imposed by the
caller; historical game participants are never filtered by today's active flag.

``get_match_reads`` is the one header reader of every serializer (tournament, admin, user, achievement): arbitrary
participants, the owner's own discipline, no home/away. ``duel_matches`` stays only as the two-participant aggregate
helper of the per-player readers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from shared import models
from shared.repository.stats_queries import match_context, team_scores
from shared.services.person_display import game_handle_of

__all__ = (
    "MatchReadContext",
    "ParticipantContext",
    "duel_matches",
    "get_match_events",
    "get_match_facts",
    "get_match_members",
    "get_match_reads",
    "get_match_segments",
)


def duel_matches(*, discipline: str, match_ids: sa.Select | None = None) -> sa.Subquery:
    """Native headers and observed scores in the owner's historical participation slots.

    ``match_ids`` narrows the duels to those matches before the participant aggregate: the planner estimates that
    aggregate (``HAVING count(*) = 2 ...``) at one row whatever its input, so an unnarrowed one is walked, with its
    score lookups, for every match of the game, and once per outer row when it lands on the inner side of a nested loop.
    """
    context = match_context(discipline=discipline)
    mt, et = models.StatsMatchTeam, models.EncounterTeam
    participants = (
        sa.select(
            mt.match_id,
            sa.func.max(et.id).filter(et.slot == 1).label("home_encounter_team_id"),
            sa.func.max(et.id).filter(et.slot == 2).label("away_encounter_team_id"),
            sa.func.max(et.team_id).filter(et.slot == 1).label("home_tournament_team_id"),
            sa.func.max(et.team_id).filter(et.slot == 2).label("away_tournament_team_id"),
        )
        .select_from(mt)
        .join(context, sa.and_(context.c.id == mt.match_id, context.c.encounter_id == mt.encounter_id))
        .join(et, sa.and_(et.id == mt.encounter_team_id, et.encounter_id == mt.encounter_id))
        .where(*([mt.match_id.in_(match_ids)] if match_ids is not None else []))
        .group_by(mt.match_id)
        .having(sa.func.count() == 2, sa.func.min(et.slot) == 1, sa.func.max(et.slot) == 2)
        .subquery()
    )
    scores = team_scores(discipline=discipline, stat_code="score")
    home, away = scores.alias("home_observed_score"), scores.alias("away_observed_score")
    return (
        sa.select(
            *context.c,
            participants.c.home_encounter_team_id,
            participants.c.away_encounter_team_id,
            participants.c.home_tournament_team_id,
            participants.c.away_tournament_team_id,
            home.c.value.label("home_score"),
            away.c.value.label("away_score"),
        )
        .select_from(context)
        .join(participants, participants.c.match_id == context.c.id)
        .outerjoin(
            home,
            sa.and_(home.c.match_id == context.c.id, home.c.encounter_team_id == participants.c.home_encounter_team_id),
        )
        .outerjoin(
            away,
            sa.and_(away.c.match_id == context.c.id, away.c.encounter_team_id == participants.c.away_encounter_team_id),
        )
        .subquery()
    )


@dataclass(frozen=True, slots=True)
class ParticipantContext:
    """One ``stats.match_team`` row with the participation it names."""

    #: The participation snapshot, live or retired -- never filtered by ``active``.
    seat: models.EncounterTeam
    #: ``stats.match_team`` observation order; never a public slot.
    source_position: int
    #: The bound game's official line; ``None`` when the match is unbound or the game has no line for this seat.
    result: models.EncounterGameTeam | None
    #: Observed segment-0 facts with NULL member and entity, by stat code; an absent key is missing, never zero.
    team_facts: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class MatchReadContext:
    match: models.StatsMatch
    game: models.EncounterGame | None
    encounter: models.Encounter
    map: models.CatalogEntity
    job: models.IngestJob | None
    #: Every ``stats.match_team`` row, ordered by ``(slot, encounter_team_id)``.
    participants: tuple[ParticipantContext, ...]
    display_filename: str | None
    #: The match's own ``mode_entity_id`` entity, never the map's catalog parent; ``None`` without one.
    mode: models.CatalogEntity | None = None


async def get_match_reads(
    session: AsyncSession,
    *,
    match_ids: Sequence[int],
    encounter_options: Sequence[Any] = (),
) -> dict[int, MatchReadContext]:
    """Load an authorized batch: one query each for headers, participants, game lines and team facts."""
    if not match_ids:
        return {}
    m, g, e, entity, job = (
        models.StatsMatch,
        models.EncounterGame,
        models.Encounter,
        models.CatalogEntity,
        models.IngestJob,
    )
    mode = aliased(models.CatalogEntity, name="mode")
    rows = (
        (
            await session.execute(
                sa.select(m, g, e, entity, job, mode)
                .select_from(m)
                .join(
                    e,
                    sa.and_(e.id == m.encounter_id, e.workspace_id == m.workspace_id, e.discipline == m.discipline),
                )
                .outerjoin(
                    g,
                    sa.and_(
                        g.id == m.encounter_game_id,
                        g.encounter_id == m.encounter_id,
                        sa.or_(g.map_id.is_(None), g.map_id == m.map_entity_id),
                    ),
                )
                .join(
                    entity,
                    sa.and_(entity.id == m.map_entity_id, entity.discipline == m.discipline, entity.kind == "map"),
                )
                .outerjoin(
                    job,
                    sa.and_(
                        job.id == m.ingest_job_id, job.workspace_id == m.workspace_id, job.discipline == m.discipline
                    ),
                )
                .outerjoin(mode, mode.id == m.mode_entity_id)
                .where(m.id.in_(match_ids), sa.or_(m.encounter_game_id.is_(None), g.id.is_not(None)))
                .options(selectinload(entity.parent), *encounter_options)
            )
        )
        .unique()
        .all()
    )
    if not rows:
        return {}
    ids = [row[0].id for row in rows]
    mt, et, gt = models.StatsMatchTeam, models.EncounterTeam, models.EncounterGameTeam
    fact, stat = models.StatsFact, models.StatDef
    seats: dict[int, list[tuple[models.EncounterTeam, int]]] = {}
    for match_id, source_position, seat in await session.execute(
        sa.select(mt.match_id, mt.source_position, et)
        .join(et, sa.and_(et.id == mt.encounter_team_id, et.encounter_id == mt.encounter_id))
        .where(mt.match_id.in_(ids))
        .order_by(mt.match_id, et.slot, et.id)
    ):
        seats.setdefault(match_id, []).append((seat, source_position))
    game_ids = {row[1].id for row in rows if row[1] is not None}
    lines: dict[tuple[int, int], models.EncounterGameTeam] = (
        {
            (line.game_id, line.encounter_team_id): line
            for line in await session.scalars(sa.select(gt).where(gt.game_id.in_(game_ids)))
        }
        if game_ids
        else {}
    )
    team_facts: dict[tuple[int, int], dict[str, float]] = {}
    for match_id, encounter_team_id, code, value in await session.execute(
        sa.select(fact.match_id, fact.encounter_team_id, stat.code, fact.value)
        .select_from(fact)
        .join(m, m.id == fact.match_id)
        .join(stat, sa.and_(stat.id == fact.stat_id, stat.discipline == m.discipline))
        .join(mt, sa.and_(mt.match_id == fact.match_id, mt.encounter_team_id == fact.encounter_team_id))
        .where(
            fact.match_id.in_(ids),
            fact.segment == 0,
            fact.workspace_member_id.is_(None),
            fact.entity_id.is_(None),
        )
        .order_by(fact.match_id, fact.encounter_team_id, stat.code)
    ):
        team_facts.setdefault((match_id, encounter_team_id), {})[code] = float(value)
    return {
        match.id: MatchReadContext(
            match=match,
            game=game,
            encounter=encounter,
            map=map_entity,
            mode=mode_entity,
            job=ingest_job,
            participants=tuple(
                ParticipantContext(
                    seat=seat,
                    source_position=source_position,
                    result=lines.get((game.id, seat.id)) if game is not None else None,
                    team_facts=team_facts.get((match.id, seat.id), {}),
                )
                for seat, source_position in seats.get(match.id, ())
            ),
            display_filename=ingest_job.filename if ingest_job is not None else None,
        )
        for match, game, encounter, map_entity, ingest_job, mode_entity in rows
    }


async def get_match_members(session: AsyncSession, *, match_ids: Sequence[int]) -> Sequence[sa.Row]:
    """Every ``stats.match_player`` row, event-only members included, ordered by ``(match, team, member)``.

    Columns: ``match_id, encounter_team_id, workspace_member_id, player_id, player_name, handle_snapshot,
    discipline, played_at, workspace_name, game_handle, game_handle_verified, role_dimension, role_code,
    role_parent_code``. ``played_at`` is the match's ``played_at``, else its ``created_at``.
    ``player_name`` is the global player's canonical, unique ``players.user.name``; ``handle_snapshot`` is what the
    observation recorded; ``workspace_name`` the member's ``display_name``; ``game_handle``/``game_handle_verified``
    the match game's identity-provider handle the match's workspace may show and whether its account is verified
    (``person_display.game_handle``); ``match_reads`` folds them into the shown name. A
    member of another workspace is not a participant of this match and is dropped; an observed role outside the
    owner's ontology reads as no role.
    """
    if not match_ids:
        return []
    p, m, wm, user = models.StatsMatchPlayer, models.StatsMatch, models.WorkspaceMember, models.User
    role, parent, dimension = aliased(models.CatalogRole), aliased(models.CatalogRole), models.RoleDimension
    return (
        await session.execute(
            sa.select(
                p.match_id,
                p.encounter_team_id,
                p.workspace_member_id,
                wm.player_id,
                user.name.label("player_name"),
                p.handle_snapshot,
                m.discipline,
                sa.func.coalesce(m.played_at, m.created_at).label("played_at"),
                wm.display_name.label("workspace_name"),
                *(
                    column.label(name)
                    for column, name in zip(
                        game_handle_of(wm.player_id, m.discipline, m.workspace_id),
                        ("game_handle", "game_handle_verified"),
                        strict=True,
                    )
                ),
                dimension.code.label("role_dimension"),
                role.code.label("role_code"),
                parent.code.label("role_parent_code"),
            )
            .select_from(p)
            .join(m, m.id == p.match_id)
            .join(wm, sa.and_(wm.id == p.workspace_member_id, wm.workspace_id == m.workspace_id))
            .join(user, user.id == wm.player_id)
            .outerjoin(
                role,
                sa.and_(
                    role.id == p.observed_role_id,
                    sa.or_(role.workspace_id.is_(None), role.workspace_id == m.workspace_id),
                ),
            )
            .outerjoin(dimension, sa.and_(dimension.id == role.dimension_id, dimension.discipline == m.discipline))
            .outerjoin(parent, parent.id == role.parent_role_id)
            .where(p.match_id.in_(match_ids))
            .order_by(p.match_id, p.encounter_team_id, p.workspace_member_id)
        )
    ).all()


async def get_match_segments(session: AsyncSession, *, match_ids: Sequence[int]) -> Sequence[models.StatsSegment]:
    """Positive segments only (segment 0 has no row), ordered by ``(match, segment)``."""
    if not match_ids:
        return []
    s = models.StatsSegment
    return (await session.scalars(sa.select(s).where(s.match_id.in_(match_ids)).order_by(s.match_id, s.segment))).all()


async def get_match_facts(session: AsyncSession, *, match_ids: Sequence[int]) -> Sequence[sa.Row]:
    """Every fact at every grain, inactive stats and entities included; never summed across grains.

    Columns: ``match_id, encounter_team_id, workspace_member_id, entity_id, segment, stat_code, value, entity``. A
    member grain needs the member in the match's workspace, an entity grain an entity of the match's discipline; a
    fact failing either is dropped, never relabelled. ``entity`` is the character row (or ``None`` without an entity
    grain). Ordered by ``(match, segment, team, member NULLS FIRST, entity NULLS FIRST, stat_code)``.
    """
    if not match_ids:
        return []
    f, m, d, mt = models.StatsFact, models.StatsMatch, models.StatDef, models.StatsMatchTeam
    wm, entity = models.WorkspaceMember, aliased(models.CatalogEntity, name="entity")
    return (
        await session.execute(
            sa.select(
                f.match_id,
                f.encounter_team_id,
                f.workspace_member_id,
                f.entity_id,
                f.segment,
                d.code.label("stat_code"),
                f.value,
                entity,
            )
            .select_from(f)
            .join(m, m.id == f.match_id)
            .join(d, sa.and_(d.id == f.stat_id, d.discipline == m.discipline))
            .join(mt, sa.and_(mt.match_id == f.match_id, mt.encounter_team_id == f.encounter_team_id))
            .outerjoin(wm, sa.and_(wm.id == f.workspace_member_id, wm.workspace_id == m.workspace_id))
            .outerjoin(
                entity,
                sa.and_(entity.id == f.entity_id, entity.discipline == m.discipline, entity.kind == "character"),
            )
            .where(
                f.match_id.in_(match_ids),
                sa.or_(f.workspace_member_id.is_(None), wm.id.is_not(None)),
                sa.or_(f.entity_id.is_(None), entity.id.is_not(None)),
            )
            .order_by(
                f.match_id,
                f.segment,
                f.encounter_team_id,
                f.workspace_member_id.asc().nulls_first(),
                f.entity_id.asc().nulls_first(),
                d.code,
            )
        )
    ).all()


async def get_match_events(session: AsyncSession, *, match_id: int) -> Sequence[sa.Row]:
    """Every declared event type of one match, ordered by ``(segment, t, id)``.

    Positional columns: the ``StatsEvent`` row, its type code, the character and the related character; a character
    outside the match's discipline reads as ``None``.
    """
    ev, m, kind = models.StatsEvent, models.StatsMatch, models.EventType
    entity, related = aliased(models.CatalogEntity), aliased(models.CatalogEntity)
    return (
        await session.execute(
            sa.select(ev, kind.code.label("type_code"), entity, related)
            .select_from(ev)
            .join(m, m.id == ev.match_id)
            .join(kind, sa.and_(kind.id == ev.type_id, kind.discipline == m.discipline))
            .outerjoin(
                entity,
                sa.and_(entity.id == ev.entity_id, entity.discipline == m.discipline, entity.kind == "character"),
            )
            .outerjoin(
                related,
                sa.and_(
                    related.id == ev.related_entity_id,
                    related.discipline == m.discipline,
                    related.kind == "character",
                ),
            )
            .where(ev.match_id == match_id)
            .order_by(ev.segment, ev.t, ev.id)
        )
    ).all()
