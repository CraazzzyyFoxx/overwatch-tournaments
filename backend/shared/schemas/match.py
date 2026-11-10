"""Native match wire: arbitrary participants, native facts, no home/away.

Served by tournament-service (``/api/v1/matches/{id}``, its kill-feed, the encounter's matches, the admin rows) and
embedded by app-service (user match rows, achievement links); ``shared.services.match_reads`` builds every one of them.

Scale and grain rules the consumers rely on:

* A fact is one observation at one grain: ``segment`` 0 is the whole match (it has no ``NativeSegment`` row),
  ``workspace_member_id=None`` a team fact, ``entity_id=None`` no entity grain. Grains are never summed together.
* ``team_facts`` carries observed segment-0 facts with NULL member and entity; an absent key is missing, not zero.
* ``duration_s`` and every ``duration`` stat are seconds; a ``percent`` stat is a 0-1 fraction.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from shared.models.stats.ingest import RawSourceStatus
from shared.schemas.base import BaseRead
from shared.schemas.catalog import CatalogEntityRead
from shared.schemas.identity import PersonDisplayRead
from shared.schemas.role import RoleRef

__all__ = (
    "MatchEventsRead",
    "MatchParticipantRead",
    "MatchRead",
    "MatchResultRead",
    "NativeFact",
    "NativeMatchEvent",
    "NativeMatchMember",
    "NativeMatchStatistics",
    "NativeSegment",
)


class MatchResultRead(BaseModel):
    """The official result, from the bound ``encounter.game_team``."""

    score: int | None
    placement: int | None
    starting_side: str | None


class MatchParticipantRead(BaseModel):
    encounter_team_id: int
    #: Encounter seat (public order).
    slot: int
    #: ``stats.match_team`` observation order; never a public slot.
    source_position: int
    #: ``None``: mix/scrim participant or a deleted source team; the row is kept.
    tournament_team_id: int | None
    #: The participation snapshot.
    name: str
    #: ``None`` when the match is not bound to a game.
    result: MatchResultRead | None
    #: Observed segment-0 facts with NULL member and entity; an absent key is missing.
    team_facts: dict[str, float]


class MatchRead(BaseRead):
    #: The observation row's ``created_at``.
    created_at: datetime
    updated_at: datetime | None
    #: ``stats.match.played_at``; never inferred from ``created_at``.
    played_at: datetime | None
    workspace_id: int
    discipline: str
    encounter_id: int
    encounter_game_id: int | None
    #: The bound game's position only.
    map_index: int | None
    #: Catalog entity of kind ``map``.
    map_id: int
    #: Expanded by ``entities=map``; ``map.parent`` is the map's catalog parent, not necessarily the match's mode.
    map: CatalogEntityRead | None = None
    #: The match's own catalog ``mode`` (Deadlock plays several on one map); ``None``: the catalog has no mode.
    mode_id: int | None = None
    #: Expanded with ``map``.
    mode: CatalogEntityRead | None = None
    #: Seconds.
    duration_s: float | None
    #: Raw provenance, unchanged names.
    log_name: str | None
    raw_status: RawSourceStatus | None
    raw_available: bool
    #: Every ``stats.match_team`` row, ordered by slot.
    participants: list[MatchParticipantRead]


class NativeMatchMember(BaseModel):
    encounter_team_id: int
    workspace_member_id: int
    #: The workspace member's global player; a member outside the match's workspace is never listed.
    player_id: int
    #: The name this match's game shows: the workspace's name, the game handle, then the observed handle, then the
    #: canonical ``players.user.name`` (``display.canonical``: what a profile link is built from).
    display: PersonDisplayRead
    #: The exact handle the observation recorded; data, never a link target.
    handle_snapshot: str
    #: From ``observed_role_id`` through the owner ontology.
    observed_role: RoleRef | None
    #: The member's rank on the game's own ladder on the match date (``DisciplineSpec.native_rank_at``); ``None``
    #: when the game keeps no native rank or none was known by then.
    rank_value: int | None = None


class NativeFact(BaseModel):
    encounter_team_id: int
    #: ``None`` is a team fact.
    workspace_member_id: int | None
    #: ``None`` is no entity grain.
    entity_id: int | None
    #: 0 is the whole match.
    segment: int
    stat_code: str
    value: float


class NativeSegment(BaseModel):
    #: At least 1; segment 0 has no row.
    segment: int
    kind: str
    attrs: dict[str, Any]


class NativeMatchStatistics(BaseModel):
    #: Every ``stats.match_player`` row, event-only members included; ordered by ``(encounter_team_id,
    #: workspace_member_id)``.
    members: list[NativeMatchMember]
    #: Ordered by segment.
    segments: list[NativeSegment]
    #: All grains; ordered by ``(segment, encounter_team_id, member NULLS FIRST, entity NULLS FIRST, stat_code)``.
    facts: list[NativeFact]
    #: Every entity referenced by a fact, same discipline.
    entities: list[CatalogEntityRead]


class NativeMatchEvent(BaseModel):
    id: int
    segment: int
    t: float
    #: ``stats.event_type.code``.
    type: str
    actor_member_id: int | None
    #: ``encounter_team_id``.
    actor_team_id: int | None
    target_member_id: int | None
    target_team_id: int | None
    entity_id: int | None
    related_entity_id: int | None
    data: dict[str, Any] | None


class MatchEventsRead(BaseModel):
    match_id: int
    discipline: str
    #: Every declared type, ordered by ``(segment, t, id)``.
    events: list[NativeMatchEvent]
    entities: list[CatalogEntityRead]
