"""Bidirectional Challonge sync engine.

Import: Challonge -> Local (upsert encounters from Challonge matches)
Export: Local -> Challonge (push encounter results to Challonge)
Auto-push: triggered when encounter result_status becomes 'confirmed'

Four classes, split by responsibility: ``ChallongeSyncLogService`` owns the
``challonge_sync_log`` audit trail, ``ChallongeStructureService`` creates the
local stage/group/stage-item/stage-input rows a Challonge bracket implies,
``ChallongeMappingService`` owns source discovery and the Challonge-id <-> local-id
mapping tables, and ``ChallongeSyncService`` — the exported ``sync_service`` — is
the public orchestration (import, export, push, auto-sync), assembled here from
one mixin per concern. Everything pure (the value dataclasses, score parsing,
name normalization, the loaded-collection probes) stays module-level.

Layout: ``_types`` (value dataclasses), ``helpers`` (pure mapping helpers and the
Challonge fetch), ``locking`` (the per-tournament Redis sync lock), ``sync_log``,
``structure``, ``mapping``, and the ``ChallongeSyncService`` mixins: ``upsert``
(per-match upsert, conflicts, advancement links), ``importer``
(``import_tournament``), ``export`` (export, push, auto-push) and ``auto_sync``
(the periodic pull).
"""

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.errors import BaseAPIException as HTTPException
from shared.repository import (
    BracketEncounterRepository,
    ChallongeMatchMappingRepository,
    ChallongeParticipantMappingRepository,
    ChallongeSourceRepository,
    EncounterLinkRepository,
    EncounterRepository,
    ScoringRuleRepository,
    TournamentRepository,
)
from src import schemas
from src.clients.challonge import challonge_client
from src.core import config
from src.services.challonge.sync._types import _ImportSource, _MatchLookup, _TeamLookup
from src.services.challonge.sync.auto_sync import ACTIVE_TOURNAMENT_STATUSES, AutoSyncMixin
from src.services.challonge.sync.export import ExportMixin
from src.services.challonge.sync.helpers import _import_invalidated_resources, _stage_for_challonge_group
from src.services.challonge.sync.importer import ImportMixin
from src.services.challonge.sync.locking import ADMIN_LOCK_WAIT_SECONDS, SYNC_LOCK_TTL_SECONDS, close_redis
from src.services.challonge.sync.mapping import _AMBIGUOUS, ChallongeMappingService, mapping_service
from src.services.challonge.sync.structure import ChallongeStructureService, structure_service
from src.services.challonge.sync.sync_log import ChallongeSyncLogService, purge_sync_log, sync_log_service
from src.services.challonge.sync.upsert import EncounterUpsertMixin, _places, _reseat
from src.services.tournament.events import RESULT_RESOURCES, STRUCTURE_RESOURCES


class ChallongeSyncService(EncounterUpsertMixin, ImportMixin, ExportMixin, AutoSyncMixin):
    """The public Challonge sync surface: import, export, single-result push,
    auto-push on confirmation, and the periodic worker pull."""

    def __init__(
        self,
        *,
        tournament_repo: TournamentRepository = TournamentRepository(),
        encounter_repo: EncounterRepository = EncounterRepository(),
        encounter_link_repo: EncounterLinkRepository = EncounterLinkRepository(),
        bracket_encounter_repo: BracketEncounterRepository = BracketEncounterRepository(),
        scoring_rule_repo: ScoringRuleRepository = ScoringRuleRepository(),
        source_repo: ChallongeSourceRepository = ChallongeSourceRepository(),
        match_mapping_repo: ChallongeMatchMappingRepository = ChallongeMatchMappingRepository(),
        participant_mapping_repo: ChallongeParticipantMappingRepository = ChallongeParticipantMappingRepository(),
        structure: ChallongeStructureService = structure_service,
        mapping: ChallongeMappingService = mapping_service,
        sync_log: ChallongeSyncLogService = sync_log_service,
    ) -> None:
        self.tournament_repo = tournament_repo
        self.encounter_repo = encounter_repo
        self.encounter_link_repo = encounter_link_repo
        self.bracket_encounter_repo = bracket_encounter_repo
        self.scoring_rule_repo = scoring_rule_repo
        self.source_repo = source_repo
        self.match_mapping_repo = match_mapping_repo
        self.participant_mapping_repo = participant_mapping_repo
        self.structure = structure
        self.mapping = mapping
        self.sync_log = sync_log

    async def get_sync_log(
        self, session: AsyncSession, tournament_id: int, limit: int = 50
    ) -> list[models.ChallongeSyncLog]:
        return await self.sync_log.get_sync_log(session, tournament_id, limit)

    async def preview_team_mapping(self, session: AsyncSession, tournament_id: int) -> schemas.ChallongeTeamSyncPreview:
        return await self.mapping.preview_team_mapping(session, tournament_id)

    async def apply_team_mapping(
        self, session: AsyncSession, tournament_id: int, mappings: list[schemas.ChallongeTeamMapping]
    ) -> schemas.ChallongeTeamSyncResult:
        return await self.mapping.apply_team_mapping(session, tournament_id, mappings)


sync_service = ChallongeSyncService()


__all__ = (
    "ACTIVE_TOURNAMENT_STATUSES",
    "ADMIN_LOCK_WAIT_SECONDS",
    "SYNC_LOCK_TTL_SECONDS",
    "ChallongeMappingService",
    "ChallongeStructureService",
    "ChallongeSyncLogService",
    "ChallongeSyncService",
    "close_redis",
    "mapping_service",
    "purge_sync_log",
    "structure_service",
    "sync_log_service",
    "sync_service",
)
