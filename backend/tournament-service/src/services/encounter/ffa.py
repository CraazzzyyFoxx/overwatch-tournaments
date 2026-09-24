"""FFA lobbies: the one service that writes a lobby and its participants.

A lobby is an ``Encounter`` with ``format = 'ffa'`` and no sides: the teams sit
in ``tournament.encounter_participant`` instead of home/away
(docs/plans/2026-09-24-ffa-encounters.md §3, decisions 1 and 3).
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import http_status as status
from shared.core.enums import EncounterFormat, EncounterStatus
from shared.core.errors import ApiExc
from shared.core.errors import BaseAPIException as HTTPException
from shared.domain.ffa_scoring import FFA_MAX_LOBBY_SIZE
from shared.models.tournament.encounter_participant import EncounterParticipant
from shared.repository import (
    EncounterGameRepository,
    EncounterGameResultRepository,
    EncounterParticipantRepository,
    EncounterRepository,
    EncounterResultAuditRepository,
)
from src import models

__all__ = ("FfaEncounterService", "ffa_encounter_service")


class FfaEncounterService:
    """FFA lobbies end to end: seating, per-game results, completion, reads.

    The ONLY writer of ``encounter_participant`` and ``encounter_game_result``:
    that is what keeps "participants exist only on ffa encounters" true without
    a cross-table CHECK (plan §3, decision 4).
    """

    def __init__(
        self,
        *,
        encounter_repo: EncounterRepository = EncounterRepository(),
        participant_repo: EncounterParticipantRepository = EncounterParticipantRepository(),
        game_repo: EncounterGameRepository = EncounterGameRepository(),
        result_repo: EncounterGameResultRepository = EncounterGameResultRepository(),
        audit_repo: EncounterResultAuditRepository = EncounterResultAuditRepository(),
    ) -> None:
        self.encounter_repo = encounter_repo
        self.participant_repo = participant_repo
        self.game_repo = game_repo
        self.result_repo = result_repo
        self.audit_repo = audit_repo

    async def create_lobby(
        self,
        session: AsyncSession,
        stage: models.Stage,
        item: models.StageItem,
        team_ids: Sequence[int],
        *,
        games: int,
    ) -> models.Encounter:
        """Seat ``team_ids`` (already in seed order) in a new lobby for ``item``."""
        if not 2 <= len(team_ids) <= FFA_MAX_LOBBY_SIZE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=[
                    ApiExc(
                        code="ffa_lobby_size",
                        msg=f"A lobby seats 2..{FFA_MAX_LOBBY_SIZE} participants; {item.name!r} has {len(team_ids)}",
                    )
                ],
            )
        lobby = models.Encounter(
            name=item.name,
            format=EncounterFormat.FFA,
            home_team_id=None,
            away_team_id=None,
            home_score=0,
            away_score=0,
            round=1,
            best_of=games,
            tournament_id=stage.tournament_id,
            stage_id=stage.id,
            stage_item_id=item.id,
            status=EncounterStatus.OPEN,
        )
        lobby.participants = [
            EncounterParticipant(team_id=team_id, slot=slot) for slot, team_id in enumerate(team_ids, 1)
        ]
        session.add(lobby)
        await session.flush()
        return lobby


ffa_encounter_service = FfaEncounterService()
