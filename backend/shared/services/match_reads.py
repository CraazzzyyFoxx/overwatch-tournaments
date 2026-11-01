"""The native match wire assembled from ``shared.repository.stats_reads`` contexts.

One serializer for every embedder -- the public match, the encounter's matches, the admin rows, the user's match rows
and the achievement links -- so none of them rebuilds a participant, a header or a fact on its own.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from shared.disciplines import identity_provider
from shared.repository.stats_reads import (
    MatchReadContext,
    get_match_events,
    get_match_facts,
    get_match_members,
    get_match_segments,
)
from shared.schemas.catalog import CatalogEntityRead
from shared.schemas.identity import PersonDisplayRead
from shared.schemas.match import (
    MatchEventsRead,
    MatchParticipantRead,
    MatchResultRead,
    NativeFact,
    NativeMatchEvent,
    NativeMatchMember,
    NativeMatchStatistics,
    NativeSegment,
)
from shared.schemas.role import RoleRef

__all__ = (
    "match_events_read",
    "match_header_fields",
    "match_statistics_read",
    "participant_reads",
)


def participant_reads(context: MatchReadContext) -> list[MatchParticipantRead]:
    """Every participant in slot order; the official result and the observed team facts stay separate."""
    return [
        MatchParticipantRead(
            encounter_team_id=participant.seat.id,
            slot=participant.seat.slot,
            source_position=participant.source_position,
            tournament_team_id=participant.seat.team_id,
            name=participant.seat.name,
            result=None
            if participant.result is None
            else MatchResultRead(
                score=participant.result.score,
                placement=participant.result.placement,
                starting_side=participant.result.starting_side,
            ),
            team_facts=dict(participant.team_facts),
        )
        for participant in context.participants
    ]


def match_header_fields(
    context: MatchReadContext, *, with_map: bool = False, with_parent: bool = False
) -> dict[str, Any]:
    """The ``MatchRead`` columns of one context; ``map`` and the match's own ``mode`` only on request.

    ``with_parent`` adds the map's catalog parent, which ``get_match_reads`` always loads; a match's mode is ``mode``.
    """
    match, game, job = context.match, context.game, context.job
    return {
        "id": match.id,
        "created_at": match.created_at,
        "updated_at": match.updated_at,
        "played_at": match.played_at,
        "workspace_id": match.workspace_id,
        "discipline": match.discipline,
        "encounter_id": match.encounter_id,
        "encounter_game_id": match.encounter_game_id,
        "map_index": game.position if game is not None else None,
        "map_id": match.map_entity_id,
        "map": CatalogEntityRead.from_entity(context.map, with_parent=with_parent) if with_map else None,
        "mode_id": match.mode_entity_id,
        "mode": CatalogEntityRead.from_entity(context.mode, with_parent=False)
        if with_map and context.mode is not None
        else None,
        "duration_s": match.duration_s,
        "log_name": context.display_filename,
        "raw_status": job.raw_status if job is not None else None,
        "raw_available": job.raw_available if job is not None else False,
        "participants": participant_reads(context),
    }


async def match_statistics_read(session: AsyncSession, match_id: int) -> NativeMatchStatistics:
    """One match's members, segments and facts at every grain, with the characters the facts name."""
    members = await get_match_members(session, match_ids=[match_id])
    segments = await get_match_segments(session, match_ids=[match_id])
    facts = await get_match_facts(session, match_ids=[match_id])
    entities = {row.entity.id: row.entity for row in facts if row.entity is not None}
    return NativeMatchStatistics(
        members=[
            NativeMatchMember(
                encounter_team_id=row.encounter_team_id,
                workspace_member_id=row.workspace_member_id,
                player_id=row.player_id,
                display=PersonDisplayRead.build(
                    canonical=row.player_name,
                    provider=identity_provider(row.discipline),
                    handle=row.game_handle,
                    handle_verified=bool(row.game_handle_verified),
                    workspace_name=row.workspace_name,
                    snapshot=row.handle_snapshot,
                ),
                handle_snapshot=row.handle_snapshot,
                observed_role=None
                if row.role_dimension is None
                else RoleRef(dimension=row.role_dimension, role=row.role_code, parent=row.role_parent_code),
            )
            for row in members
        ],
        segments=[NativeSegment(segment=row.segment, kind=row.kind, attrs=dict(row.attrs or {})) for row in segments],
        facts=[
            NativeFact(
                encounter_team_id=row.encounter_team_id,
                workspace_member_id=row.workspace_member_id,
                entity_id=row.entity_id,
                segment=row.segment,
                stat_code=row.stat_code,
                value=float(row.value),
            )
            for row in facts
        ],
        entities=_entity_reads(entities.values()),
    )


async def match_events_read(session: AsyncSession, context: MatchReadContext) -> MatchEventsRead:
    """The match's whole timeline; interpreting kill/ultimate/resurrect belongs to the discipline's renderer."""
    rows = await get_match_events(session, match_id=context.match.id)
    entities: dict[int, Any] = {}
    events = []
    for event, type_code, entity, related_entity in rows:
        for character in (entity, related_entity):
            if character is not None:
                entities[character.id] = character
        events.append(
            NativeMatchEvent(
                id=event.id,
                segment=event.segment,
                t=event.t,
                type=type_code,
                actor_member_id=event.actor_member_id,
                actor_team_id=event.actor_team_id,
                target_member_id=event.target_member_id,
                target_team_id=event.target_team_id,
                entity_id=event.entity_id if entity is not None else None,
                related_entity_id=event.related_entity_id if related_entity is not None else None,
                data=event.data,
            )
        )
    return MatchEventsRead(
        match_id=context.match.id,
        discipline=context.match.discipline,
        events=events,
        entities=_entity_reads(entities.values()),
    )


def _entity_reads(entities: Iterable[Any]) -> list[CatalogEntityRead]:
    """Characters have no parent; ordered by id."""
    return [CatalogEntityRead.from_entity(entity, with_parent=False) for entity in sorted(entities, key=lambda e: e.id)]
