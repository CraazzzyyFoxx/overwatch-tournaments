"""Challonge source discovery and the Challonge-id <-> local-id mapping tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.core.errors import BaseAPIException as HTTPException
from shared.repository import (
    ChallongeMatchMappingRepository,
    ChallongeParticipantMappingRepository,
    ChallongeSourceRepository,
    TeamRepository,
    TournamentRepository,
)
from src import schemas
from src.services.challonge.sync._types import (
    _ImportSource,
    _MatchLookup,
    _source_lookup_key,
    _SourceFetch,
    _TeamLookup,
)
from src.services.challonge.sync.helpers import _fetch_all_sources, _first_loaded_stage_item_id, _normalize_team_name
from src.services.challonge.sync.sync_log import ChallongeSyncLogService, sync_log_service
from src.services.team.service import team_service

_AMBIGUOUS = -1


class ChallongeMappingService:
    """Source discovery plus the Challonge-id <-> local-id mapping tables.

    ``challonge_source`` is the single source of truth for "this tournament is
    mirrored on Challonge"; ``challonge_participant_mapping`` and
    ``challonge_match_mapping`` translate Challonge's participant/match ids to
    local team/encounter ids under one source.
    """

    def __init__(
        self,
        *,
        source_repo: ChallongeSourceRepository = ChallongeSourceRepository(),
        participant_mapping_repo: ChallongeParticipantMappingRepository = ChallongeParticipantMappingRepository(),
        match_mapping_repo: ChallongeMatchMappingRepository = ChallongeMatchMappingRepository(),
        tournament_repo: TournamentRepository = TournamentRepository(),
        team_repo: TeamRepository = TeamRepository(),
        sync_log: ChallongeSyncLogService = sync_log_service,
    ) -> None:
        self.source_repo = source_repo
        self.participant_mapping_repo = participant_mapping_repo
        self.match_mapping_repo = match_mapping_repo
        self.tournament_repo = tournament_repo
        self.team_repo = team_repo
        self.sync_log = sync_log

    async def discover_sources(self, session: AsyncSession, tournament: models.Tournament) -> list[_ImportSource]:
        """Discover Challonge sources from the normalized ``challonge_source`` table.

        Stage comes from ``ChallongeSource.stage``. Read-only: the admin link
        entry-point owns source creation.
        """
        # Sorted by id: ``_resolve_export_target`` picks ``candidates[0]`` out of
        # this list, so a stable order is part of which Challonge source an
        # unmapped encounter is attributed to.
        source_rows = sorted(
            await self.source_repo.list_by_tournament(
                session,
                tournament.id,
                options=[
                    selectinload(models.ChallongeSource.stage)
                    .selectinload(models.Stage.items)
                    .selectinload(models.StageItem.inputs),
                    selectinload(models.ChallongeSource.stage_item),
                ],
            ),
            key=lambda row: row.id,
        )
        return [
            _ImportSource(
                challonge_id=row.challonge_tournament_id,
                source_id=row.id,
                source_type=row.source_type,
                stage=row.stage,
                stage_item_id=row.stage_item_id or _first_loaded_stage_item_id(row.stage),
                slug=row.slug,
            )
            for row in source_rows
        ]

    async def _build_team_name_index(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> dict[str, int]:
        """Build a normalized-name → team_id index for auto-mapping.

        Collisions (two teams with the same normalized name) are marked _AMBIGUOUS.
        balancer_name is used as a fallback only when name produces no entry.
        """
        teams = await self.team_repo.list_by_tournament(session, tournament_id)
        index: dict[str, int] = {}

        for team in teams:
            key = _normalize_team_name(team.name)
            if not key:
                continue
            if key in index and index[key] != team.id:
                index[key] = _AMBIGUOUS
                logger.warning(
                    "Ambiguous team name for Challonge auto-mapping",
                    key=key,
                    tournament_id=tournament_id,
                )
            elif key not in index:
                index[key] = team.id

        for team in teams:
            key = _normalize_team_name(getattr(team, "balancer_name", None))
            if not key or key in index:
                continue
            index[key] = team.id

        return index

    async def _auto_map_participants(
        self,
        session: AsyncSession,
        tournament: models.Tournament,
        fetches: list[tuple[_ImportSource, _SourceFetch]],
        existing_source_mappings: list[models.ChallongeParticipantMapping],
        name_index: dict[str, int],
        *,
        dry_run: bool = False,
    ) -> list[models.ChallongeParticipantMapping]:
        """Auto-create ``ChallongeParticipantMapping`` rows by matching participant
        names to local teams.

        Existing mappings always win; ambiguous name matches are skipped. Both the
        participant id and every ``group_player_id`` alias are mapped, scoped to
        the source.
        """
        existing_source_keys: set[tuple[int, int]] = {
            (mapping.source_id, mapping.challonge_participant_id) for mapping in existing_source_mappings
        }
        # (mapping, participant_name, source_group_id) — group id only for the sync log.
        created: list[tuple[models.ChallongeParticipantMapping, str, int | None]] = []
        pending: list[models.ChallongeParticipantMapping] = []

        total_participants = sum(len(f.participants) for _, f in fetches)
        logger.info(
            "Auto-mapping participants",
            tournament_id=tournament.id,
            total_participants=total_participants,
            name_index_size=len(name_index),
            existing_mappings=len(existing_source_mappings),
        )

        for source, fetch in fetches:
            if source.source_id is None:
                continue
            source_group_id = None

            for participant in fetch.participants:
                key = _normalize_team_name(participant.name)
                if not key:
                    continue

                team_id = name_index.get(key)
                if team_id is None:
                    logger.debug(
                        "No local team matches Challonge participant",
                        participant_name=participant.name,
                        challonge_id=participant.id,
                        tournament_id=tournament.id,
                    )
                    continue
                if team_id == _AMBIGUOUS:
                    logger.warning(
                        "Ambiguous team name; skipping Challonge auto-map",
                        participant_name=participant.name,
                        challonge_id=participant.id,
                    )
                    continue

                for challonge_participant_id in (participant.id, *participant.group_player_ids):
                    source_key = (source.source_id, challonge_participant_id)
                    if source_key in existing_source_keys:
                        continue
                    mapping = models.ChallongeParticipantMapping(
                        source_id=source.source_id,
                        challonge_participant_id=challonge_participant_id,
                        team_id=team_id,
                    )
                    if not dry_run:
                        pending.append(mapping)
                    created.append((mapping, participant.name, source_group_id))
                    existing_source_keys.add(source_key)

        if dry_run:
            logger.info(
                "Auto-mapping dry-run complete",
                tournament_id=tournament.id,
                auto_mapped=len(created),
            )
            return []

        if created:
            await self.participant_mapping_repo.create_many(session, pending)
            for mapping, participant_name, source_group_id in created:
                await self.sync_log._log_sync(
                    session,
                    tournament.id,
                    "import",
                    "participant",
                    mapping.team_id,
                    mapping.challonge_participant_id,
                    "success",
                    source_id=mapping.source_id,
                    operation="auto_map_participant",
                    payload={
                        "action": "auto_mapped",
                        "participant_name": participant_name,
                        "group_id": source_group_id,
                    },
                )

        logger.info(
            "Auto-mapping complete",
            tournament_id=tournament.id,
            auto_mapped=len(created),
        )
        return [mapping for mapping, _name, _group_id in created]

    async def _build_team_lookup(
        self,
        session: AsyncSession,
        tournament: models.Tournament,
        fetches: list[tuple[_ImportSource, _SourceFetch]],
        *,
        source_ids: Sequence[int],
        dry_run: bool = False,
    ) -> _TeamLookup:
        # ``source_ids`` is every discovered source of this tournament, including
        # sources whose fetch failed: their mappings still feed the cross-source
        # (None, participant_id) fallback in _TeamLookup.resolve.
        existing_source_mappings = list(await self.participant_mapping_repo.list_by_source_ids(session, source_ids))

        name_index = await self._build_team_name_index(session, tournament.id)
        created_mappings = await self._auto_map_participants(
            session,
            tournament,
            fetches,
            existing_source_mappings,
            name_index,
            dry_run=dry_run,
        )

        all_mappings = existing_source_mappings + created_mappings

        # Per-source lookup key. Team resolve uses the (None, challonge_id) fallback.
        source_key_by_source_id: dict[int, int] = {}
        for source, _fetch in fetches:
            if source.source_id is not None:
                source_key_by_source_id[source.source_id] = _source_lookup_key(source)

        by_source_key: dict[tuple[int, int], int] = {}
        by_key: dict[tuple[int | None, int], int] = {}
        for mapping in all_mappings:
            source_key = source_key_by_source_id.get(mapping.source_id, mapping.source_id)
            by_source_key[(source_key, mapping.challonge_participant_id)] = mapping.team_id
            by_key.setdefault((None, mapping.challonge_participant_id), mapping.team_id)

        team_ids = sorted({mapping.team_id for mapping in all_mappings})
        teams_by_id = {team.id: team for team in await self.team_repo.bulk_get(session, team_ids)}

        logger.info(
            "Team lookup built",
            tournament_id=tournament.id,
            mapping_count=len(by_key),
            team_count=len(teams_by_id),
        )
        return _TeamLookup(
            by_source_key=by_source_key,
            by_key=by_key,
            teams_by_id=teams_by_id,
        )

    async def _build_match_lookup(
        self,
        session: AsyncSession,
        sources: list[_ImportSource],
        *,
        tournament_id: int,
    ) -> _MatchLookup:
        source_keys_by_source_id = {
            source.source_id: _source_lookup_key(source) for source in sources if source.source_id is not None
        }
        mapping_result = await session.execute(
            self.match_mapping_repo.select()
            .where(models.ChallongeMatchMapping.source_id.in_(tuple(source_keys_by_source_id.keys())))
            .options(selectinload(models.ChallongeMatchMapping.encounter))
        )
        mappings = list(mapping_result.scalars().all())
        by_source_key: dict[tuple[int, int], models.Encounter] = {}
        mapped_keys: set[tuple[int, int]] = set()
        mapped_encounter_ids: set[int] = set()
        for mapping in mappings:
            mapped_keys.add((mapping.source_id, mapping.challonge_match_id))
            if mapping.encounter is None:
                continue
            mapped_encounter_ids.add(mapping.encounter.id)
            source_key = source_keys_by_source_id.get(mapping.source_id, mapping.source_id)
            by_source_key[(source_key, mapping.challonge_match_id)] = mapping.encounter

        # Locally generated bracket rows (StageService.generate_encounters) with no
        # challonge_match_mapping yet, indexed by (stage, round, team pair) so the
        # create-path adopts them instead of laying a second Encounter over the
        # same slot every run.
        unlinked_by_slot: dict[tuple[int | None, int, frozenset[int]], models.Encounter] = {}
        encounters_result = await session.execute(
            sa.select(models.Encounter, models.BracketEncounter)
            .join(models.BracketEncounter, models.BracketEncounter.encounter_id == models.Encounter.id)
            .where(
                models.Encounter.tournament_id == tournament_id,
                # A Challonge match is a duel; a lobby sitting in the same
                # tournament must never be claimed as one of its slots.
                models.Encounter.slot_count == 2,
            )
        )
        rows = encounters_result.tuples().all()
        seats_by_encounter: dict[int, list[int]] = {}
        for seat in (
            await session.execute(
                sa.select(models.EncounterTeam).where(
                    models.EncounterTeam.encounter_id.in_([encounter.id for encounter, _ in rows] or [0]),
                    models.EncounterTeam.active.is_(True),
                    models.EncounterTeam.team_id.is_not(None),
                )
            )
        ).scalars():
            seats_by_encounter.setdefault(seat.encounter_id, []).append(seat.team_id)
        for encounter, position in rows:
            if encounter.id in mapped_encounter_ids:
                continue
            team_ids = seats_by_encounter.get(encounter.id, [])
            # TBD slots are left for the create-path: there is nothing to match yet.
            if len(team_ids) != 2:
                continue
            unlinked_by_slot.setdefault((position.stage_id, position.round, frozenset(team_ids)), encounter)

        # Existing encounters are located via challonge_match_mapping (by_source_key);
        # by_challonge_id is an in-run cache populated by _MatchLookup.set for
        # encounters created/mapped during this import.
        return _MatchLookup(
            by_source_key=by_source_key,
            by_challonge_id={},
            mapped_keys=mapped_keys,
            unlinked_by_slot=unlinked_by_slot,
        )

    async def _ensure_match_mapping(
        self,
        session: AsyncSession,
        source: _ImportSource,
        challonge_match_id: int,
        encounter: models.Encounter,
        match_lookup: _MatchLookup,
    ) -> None:
        if source.source_id is None:
            return
        key = (source.source_id, challonge_match_id)
        if key in match_lookup.mapped_keys:
            return
        mapping = models.ChallongeMatchMapping(
            source_id=source.source_id,
            challonge_match_id=challonge_match_id,
            encounter_id=encounter.id,
        )
        await self.match_mapping_repo.create(session, mapping)
        match_lookup.mapped_keys.add(key)
        match_lookup.set(source, challonge_match_id, encounter)

    async def _existing_participant_mappings(
        self, session: AsyncSession, source_ids: set[int]
    ) -> dict[tuple[int, int], models.ChallongeParticipantMapping]:
        mappings: dict[tuple[int, int], models.ChallongeParticipantMapping] = {}
        for mapping in await self.participant_mapping_repo.list_by_source_ids(session, sorted(source_ids)):
            mappings.setdefault((mapping.source_id, mapping.challonge_participant_id), mapping)
        return mappings

    async def _fetch_team_sync_context(
        self, session: AsyncSession, tournament_id: int
    ) -> tuple[models.Tournament, list[models.Team], list[tuple[_ImportSource, _SourceFetch]]]:
        """Shared setup for preview/apply: the tournament, its teams, and every
        Challonge source's current participant list (matches are irrelevant here,
        but ``_fetch_all_sources`` fetches both in one round-trip per source)."""
        tournament = await self.tournament_repo.get(session, tournament_id)
        if tournament is None:
            raise HTTPException(status_code=404, detail="Tournament not found")

        sources = await self.discover_sources(session, tournament)
        teams = list(await team_service.get_by_tournament(session, tournament, []))
        raw_fetches = await _fetch_all_sources(sources)
        fetches = [(source, fetch) for source, fetch in raw_fetches if not isinstance(fetch, Exception)]
        return tournament, teams, fetches

    async def preview_team_mapping(self, session: AsyncSession, tournament_id: int) -> schemas.ChallongeTeamSyncPreview:
        """Read-only: for every Challonge participant on this tournament's linked
        source(s), suggest a local team by normalized-name match and report any
        mapping already persisted. Counterpart to ``apply_team_mapping``, which
        accepts an admin's explicit overrides for whatever this can't resolve
        (no match, or an ambiguous name shared by two local teams)."""
        _tournament, teams, fetches = await self._fetch_team_sync_context(session, tournament_id)
        name_index = await self._build_team_name_index(session, tournament_id)
        source_ids = {source.source_id for source, _fetch in fetches if source.source_id is not None}
        existing_mappings = await self._existing_participant_mappings(session, source_ids)

        participants: list[schemas.ChallongeTeamPreviewParticipant] = []
        for source, fetch in fetches:
            for participant in fetch.participants:
                suggested_team_id = name_index.get(_normalize_team_name(participant.name))
                if suggested_team_id == _AMBIGUOUS:
                    suggested_team_id = None
                mapped_team_id = (
                    existing_mappings[(source.source_id, participant.id)].team_id
                    if source.source_id is not None and (source.source_id, participant.id) in existing_mappings
                    else None
                )
                participants.append(
                    schemas.ChallongeTeamPreviewParticipant(
                        participant_id=participant.id,
                        challonge_id=participant.id,
                        group_id=None,
                        group_name=None,
                        challonge_tournament_id=source.challonge_id,
                        name=participant.name,
                        active=participant.active,
                        suggested_team_id=suggested_team_id,
                        mapped_team_id=mapped_team_id,
                    )
                )

        return schemas.ChallongeTeamSyncPreview(
            teams=[
                schemas.ChallongeTeamPreviewTeam(id=team.id, name=team.name, balancer_name=team.balancer_name)
                for team in teams
            ],
            participants=participants,
        )

    async def apply_team_mapping(
        self, session: AsyncSession, tournament_id: int, mappings: list[schemas.ChallongeTeamMapping]
    ) -> schemas.ChallongeTeamSyncResult:
        """Persist an admin's explicit Challonge participant -> team mappings.

        Every ``(participant_id, group_id)`` in ``mappings`` must resolve against
        this tournament's currently fetched Challonge participants, and every
        ``team_id`` must belong to this tournament -- both checked up front so a bad
        entry fails the whole request rather than silently skipping it."""
        _tournament, teams, fetches = await self._fetch_team_sync_context(session, tournament_id)
        team_ids = {team.id for team in teams}

        rows_by_request_key: dict[tuple[int, int | None], tuple[_ImportSource, schemas.ChallongeParticipant]] = {}
        for source, fetch in fetches:
            group_id = None
            for participant in fetch.participants:
                rows_by_request_key[(participant.id, group_id)] = (source, participant)

        validation_errors: list[str] = []
        for mapping in mappings:
            if (mapping.participant_id, mapping.group_id) not in rows_by_request_key:
                validation_errors.append(f"Challonge participant {mapping.participant_id} not found on this tournament")
            elif mapping.team_id not in team_ids:
                validation_errors.append(f"Team {mapping.team_id} not found on this tournament")
        if validation_errors:
            raise HTTPException(status_code=400, detail=validation_errors)

        source_ids = {
            source.source_id for source, _participant in rows_by_request_key.values() if source.source_id is not None
        }
        existing_mappings = await self._existing_participant_mappings(session, source_ids)

        created = updated = unchanged = 0
        new_rows: list[models.ChallongeParticipantMapping] = []
        for mapping in mappings:
            source, participant = rows_by_request_key[(mapping.participant_id, mapping.group_id)]
            if source.source_id is None:
                continue
            # Challonge's group stages give each participant a separate
            # ``group_player_id`` per group, and group-stage matches reference
            # that id (not the top-level participant id) as player1_id/player2_id.
            # Map every alias here too (as `_auto_map_participants` does), or
            # matches never resolve a team the admin explicitly picked.
            primary_result = "unchanged"
            for challonge_participant_id in (participant.id, *participant.group_player_ids):
                source_key = (source.source_id, challonge_participant_id)
                existing = existing_mappings.get(source_key)
                if existing is None:
                    row = models.ChallongeParticipantMapping(
                        source_id=source.source_id,
                        challonge_participant_id=challonge_participant_id,
                        team_id=mapping.team_id,
                    )
                    new_rows.append(row)
                    existing_mappings[source_key] = row
                    result = "created"
                elif existing.team_id != mapping.team_id:
                    existing.team_id = mapping.team_id
                    result = "updated"
                else:
                    result = "unchanged"
                if challonge_participant_id == participant.id:
                    primary_result = result
            if primary_result == "created":
                created += 1
            elif primary_result == "updated":
                updated += 1
            else:
                unchanged += 1

        if new_rows:
            await self.participant_mapping_repo.create_many(session, new_rows)
        await session.commit()
        mapped_keys = {(mapping.participant_id, mapping.group_id) for mapping in mappings}
        skipped = max(len(rows_by_request_key) - len(mapped_keys), 0)
        return schemas.ChallongeTeamSyncResult(
            success=True,
            count=created + updated + unchanged,
            created=created,
            updated=updated,
            unchanged=unchanged,
            skipped=skipped,
        )


mapping_service = ChallongeMappingService()
