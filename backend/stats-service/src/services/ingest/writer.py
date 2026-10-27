"""The one transaction that publishes a bound document: locks, native replacement, evidence, outbox, done.

Lock order, everywhere: encounter -> game -> ingest job -> existing ``stats.match``; only then are ids, basis and the
claim token validated. Identity advisory locks (materialization) come after these and never lead back to an
encounter/game lock. Nothing here fetches from S3 or decodes: the caller prepared the document first.

``write_observations`` flushes and never commits: replacement, revision, both audit records, the outbox rows and the
job's ``done`` transition become visible together or not at all, and a reader sees the complete old or complete new
observation, never a union.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.disciplines import DISCIPLINES
from shared.disciplines.ingest import BoundMatch
from shared.messaging.config import ACHIEVEMENT_EVALUATE_QUEUE, MATCH_INGESTED_EXCHANGE
from shared.messaging.outbox import enqueue_outbox_event
from shared.repository.roles import CatalogRoleRepository
from shared.repository.stats import IngestJobRepository, StatsMatchRepository
from shared.schemas.events import (
    AchievementEvaluateEvent,
    MatchIngestedEvent,
    MatchIngestExtraParticipant,
    MatchIngestPlacement,
)
from shared.schemas.role import RoleRef
from shared.services.stats_evidence import capture_stats_evidence, owner_scopes, stage_stats_evidence
from src.services.ingest.binding import load_game_seats
from src.services.ingest.jobs import Claim, is_current_claim
from src.services.ingest.validation import ValidatedDocument
from src.services.match_logs.flows import _enqueue_match_log_tournament_events
from src.services.match_logs.log_records import log_records_service, reparse_observation
from src.services.match_logs.objectiveless import resolve_encounter_maps

__all__ = ("ClaimSuperseded", "Locked", "StaleTarget", "lock_owners", "write_observations")

_jobs = IngestJobRepository()
_matches = StatsMatchRepository()
_HANDLE_WIRE_LIMIT = 128


class ClaimSuperseded(RuntimeError):
    """The attempt that is writing is no longer the job's current claim; it must change nothing."""


class StaleTarget(ValueError):
    """What the binding was made against changed before the locks were taken (the game, its seats or its map)."""

    code = "binding_stale"


@dataclass(frozen=True, slots=True)
class Locked:
    """The rows held under the final locks, in lock order."""

    encounter: models.Encounter
    game: models.EncounterGame
    job: models.IngestJob
    match: models.StatsMatch | None


async def lock_owners(
    session: AsyncSession, *, job_id: int, workspace_id: int, discipline: str, encounter_id: int, game_id: int
) -> Locked:
    """Encounter, game, job, then the game's observation, each ``FOR UPDATE`` and re-read (never a stale instance)."""
    encounter = (
        await session.scalars(
            sa.select(models.Encounter)
            .where(
                models.Encounter.id == encounter_id,
                models.Encounter.workspace_id == workspace_id,
                models.Encounter.discipline == discipline,
            )
            .with_for_update(of=models.Encounter)
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    game = (
        await session.scalars(
            sa.select(models.EncounterGame)
            .where(models.EncounterGame.id == game_id, models.EncounterGame.encounter_id == encounter_id)
            .with_for_update(of=models.EncounterGame)
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    if encounter is None or game is None:
        raise StaleTarget("the target game no longer exists")
    job = await _jobs.get_for_update(session, job_id, workspace_id=workspace_id)
    if job is None:
        raise ClaimSuperseded("the ingest job no longer exists")
    match = await _matches.get_for_game(
        session, encounter_game_id=game_id, workspace_id=workspace_id, discipline=discipline, for_update=True
    )
    return Locked(encounter=encounter, game=game, job=job, match=match)


def _rows(
    doc: ValidatedDocument, binding: BoundMatch, member_of: dict[str, int], match_id: int
) -> dict[str, list[dict]]:
    """Every native child row of the document's observation; teams keep the canonical array order."""
    document = doc.doc
    team_of = binding.team_ids
    seat_of = {person.key: team_of[person.team] for person in document.participants}
    teams = [
        {
            "match_id": match_id,
            "encounter_id": binding.encounter_id,
            "encounter_team_id": team_of[team.key],
            "source_position": position,
        }
        for position, team in enumerate(document.teams, start=1)
    ]
    players = [
        {
            "match_id": match_id,
            "workspace_member_id": member_of[person.key],
            "encounter_team_id": team_of[person.team],
            "handle_snapshot": person.identity.id[:255],
            "observed_role_id": (
                None if person.role is None else doc.role_ids[(person.role.dimension, person.role.role)]
            ),
        }
        for person in document.participants
    ]
    segments = [
        {"match_id": match_id, "segment": segment.index, "kind": segment.kind, "attrs": dict(segment.attrs)}
        for segment in document.segments
    ]
    facts = [
        {
            "match_id": match_id,
            "segment": fact.segment,
            "encounter_team_id": team_of[fact.team] if fact.participant is None else seat_of[fact.participant],
            "workspace_member_id": None if fact.participant is None else member_of[fact.participant],
            "entity_id": None if fact.entity is None else doc.entity_ids[fact.entity],
            "stat_id": doc.stat_ids[fact.stat],
            "value": fact.value,
        }
        for fact in document.facts
    ]

    def event_team(team: str | None, person: str | None) -> int | None:
        if team is not None:
            return team_of[team]
        return None if person is None else seat_of[person]

    events = [
        {
            "match_id": match_id,
            "t": event.t,
            "segment": event.segment,
            "type_id": doc.event_type_ids[event.type],
            "actor_member_id": None if event.actor is None else member_of[event.actor],
            "actor_team_id": event_team(event.actor_team, event.actor),
            "target_member_id": None if event.target is None else member_of[event.target],
            "target_team_id": event_team(event.target_team, event.target),
            "entity_id": None if event.entity is None else doc.entity_ids[event.entity],
            "related_entity_id": None if event.related_entity is None else doc.entity_ids[event.related_entity],
            "entity_kind": "character",
            "data": event.data or None,
        }
        for event in document.events
    ]
    return {"teams": teams, "players": players, "segments": segments, "facts": facts, "events": events}


async def _extras(
    session: AsyncSession, doc: ValidatedDocument, binding: BoundMatch, member_of: dict[str, int], roster
) -> list[MatchIngestExtraParticipant]:
    """Participants whose member is not on the roster of the seat they played for: the match layer decides on them."""
    extras = []
    ontology = None
    for person in doc.doc.participants:
        seat = binding.team_ids[person.team]
        if member_of[person.key] in roster.members.get(seat, frozenset()):
            continue
        observed = None
        if person.role is not None:
            ontology = ontology or await CatalogRoleRepository().ontology(
                session, discipline=binding.discipline, workspace_id=binding.workspace_id
            )
            observed = RoleRef.of_node(ontology, ontology.node(person.role.dimension, person.role.role))
        extras.append(
            MatchIngestExtraParticipant(
                encounter_team_id=seat,
                workspace_member_id=member_of[person.key],
                handle_snapshot=person.identity.id[:_HANDLE_WIRE_LIMIT],
                observed_role=observed,
            )
        )
    return extras


async def write_observations(
    session: AsyncSession,
    *,
    job: models.IngestJob,
    claim_token: tuple[int, datetime],
    doc: ValidatedDocument,
    binding: BoundMatch,
    document_ref: str | None = None,
    producers: Mapping[int, str],
) -> models.StatsMatch:
    """Replace the game's observations with ``doc`` and finish ``job``, all in the caller's transaction.

    ``binding.participants`` carries the materialized member of every document participant. ``document_ref``, when
    the job just gained its decoded envelope, is stored by the same ``done`` transition. ``producers`` (job id ->
    ``canonical|decoded``, read before the locks, including this job) decides which observations the raw Push/Clash
    score normalization may touch.
    """
    locked = await lock_owners(
        session,
        job_id=job.id,
        workspace_id=binding.workspace_id,
        discipline=binding.discipline,
        encounter_id=binding.encounter_id,
        game_id=binding.encounter_game_id,
    )
    job, encounter, game, match = locked.job, locked.encounter, locked.game, locked.match
    if not is_current_claim(job, Claim(job.id, job.workspace_id, *claim_token)):
        raise ClaimSuperseded("the ingest claim was superseded before observations were written")
    if (job.workspace_id, job.discipline) != (binding.workspace_id, binding.discipline) or (
        doc.workspace_id,
        doc.discipline,
    ) != (binding.workspace_id, binding.discipline):
        raise ValueError("the job, document and binding belong to different owners")
    if game.map_id not in (None, doc.map_id) or (
        None not in (game.mode_id, doc.mode_id) and game.mode_id != doc.mode_id
    ):
        raise StaleTarget("the game is played on another map or mode than the document's")
    # The match header is immutable. Evidence refuses a reparse that changes the map; the frozen evidence projection
    # has no mode, so this check is the only guard on it. A mode the match never knew stays unknown.
    if match is not None and (
        match.map_entity_id != doc.map_id
        or (None not in (match.mode_entity_id, doc.mode_id) and match.mode_entity_id != doc.mode_id)
    ):
        raise StaleTarget("the game is already observed on another map or mode than the document's")
    roster = await load_game_seats(
        session, workspace_id=binding.workspace_id, discipline=binding.discipline, game_ids=[game.id]
    )
    if not roster or set(roster[0].seats) != set(binding.team_ids.values()):
        raise StaleTarget("the game's participating teams changed")
    roster = roster[0]
    member_of = {key: seat.member_id for key, seat in binding.participants.items()}
    if set(member_of) != {person.key for person in doc.doc.participants}:
        raise ValueError("every participant needs a bound workspace member")
    if len(set(member_of.values())) != len(member_of):
        raise ValueError("A player has multiple observed handles or teams in the same log")

    if match is not None and match.ingest_job_id != job.id:
        previous = await _jobs.get(session, match.ingest_job_id) if match.ingest_job_id else None
        if (
            previous is None
            or previous.source_kind == "historical_reference"
            or (previous.external_id or "").startswith("legacy:")
        ):
            raise ValueError("Another source cannot overwrite a historical observation")
        await reparse_observation(session, previous)
    created = match is None
    match_id = (
        await session.scalar(sa.text("SELECT nextval(pg_get_serial_sequence('stats.match', 'id'))"))
        if created
        else match.id
    )
    scopes = owner_scopes("match", (match_id,))
    before = await capture_stats_evidence(session, scopes=scopes)
    if created:
        match = models.StatsMatch(
            id=match_id,
            workspace_id=binding.workspace_id,
            discipline=binding.discipline,
            encounter_id=encounter.id,
            encounter_game_id=game.id,
            map_entity_id=doc.map_id,
            map_kind="map",
            mode_entity_id=doc.mode_id,
            revision=1,
        )
        await _matches.add(session, match)
    match.ingest_job_id = job.id
    match.duration_s = doc.doc.duration_s
    match.played_at = doc.doc.played_at
    await session.flush()

    rows = _rows(doc, binding, member_of, match.id)
    await _matches.replace_observations(session, match=match, **rows)
    if not created:
        match.revision += 1
    match.updated_at = datetime.now(UTC)
    await session.flush()
    after = await capture_stats_evidence(session, scopes=scopes)
    await stage_stats_evidence(
        session,
        operation="stats.reparse",
        before=before,
        after=after,
        workspace_id=binding.workspace_id,
        entity_type="stats_match",
        entity_id=match.id,
    )

    if DISCIPLINES[binding.discipline].derive_match is not None:  # Workshop-log repair: raw-log disciplines only
        await resolve_encounter_maps(session, encounter.id, producers=producers)
    if encounter.tournament_id is not None:
        await _enqueue_match_log_tournament_events(session, encounter)
        await enqueue_outbox_event(
            session,
            AchievementEvaluateEvent(
                event_id=f"achievement:{binding.workspace_id}:{encounter.tournament_id}:match:{match.id}:{match.revision}",
                workspace_id=binding.workspace_id,
                tournament_id=encounter.tournament_id,
                changed_tables=["stats.match", "stats.fact", "stats.event"],
                source_service="stats-service",
            ),
            exchange="",
            routing_key=ACHIEVEMENT_EVALUATE_QUEUE.name,
        )
    event_id = f"match.ingested:{match.id}:{match.revision}"
    await enqueue_outbox_event(
        session,
        MatchIngestedEvent(
            event_id=event_id,
            source_service="stats-service",
            workspace_id=binding.workspace_id,
            discipline=binding.discipline,
            encounter_id=encounter.id,
            encounter_game_id=game.id,
            evidence_id=match.id,
            revision=match.revision,
            ingest_job_id=job.id,
            basis_game_result_version=game.result_version,
            map_id=doc.map_id,
            mode_id=doc.mode_id,
            placements=[
                MatchIngestPlacement(encounter_team_id=binding.team_ids[team.key], placement=team.placement)
                for team in doc.doc.teams
            ],
            extra_participants=await _extras(session, doc, binding, member_of, roster),
        ),
        exchange=MATCH_INGESTED_EXCHANGE,
        routing_key="match.ingested",
        event_id=event_id,
    )
    await log_records_service.transition(session, job, models.IngestJobStatus.DONE, document_ref=document_ref)
    return match
