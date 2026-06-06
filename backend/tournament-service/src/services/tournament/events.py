from __future__ import annotations

from shared.messaging.config import (
    TOURNAMENT_EVENTS_EXCHANGE,
    TOURNAMENT_RECALC_EXCHANGE,
)
from shared.messaging.outbox import enqueue_outbox_event
from shared.schemas.events import (
    EncounterCompletedEvent,
    RegistrationApprovedEvent,
    RegistrationRejectedEvent,
    TournamentChangedEvent,
    TournamentChangedReason,
    TournamentRecalcEvent,
    TournamentStateChangedEvent,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.services.tournament.realtime_commit import register_tournament_realtime_update


async def enqueue_tournament_recalculation(
    session: AsyncSession,
    tournament_id: int,
) -> None:
    await enqueue_outbox_event(
        session,
        TournamentRecalcEvent(
            tournament_id=tournament_id,
            source_service="tournament-service",
        ),
        exchange=TOURNAMENT_RECALC_EXCHANGE,
        routing_key=f"tournament.recalc.{tournament_id}",
    )
    register_tournament_realtime_update(session, tournament_id, "bracket_changed")


async def enqueue_tournament_changed(
    session: AsyncSession,
    tournament_id: int,
    reason: TournamentChangedReason,
) -> None:
    await enqueue_outbox_event(
        session,
        TournamentChangedEvent(
            tournament_id=tournament_id,
            reason=reason,
            source_service="tournament-service",
        ),
        exchange=TOURNAMENT_RECALC_EXCHANGE,
        routing_key=f"tournament.changed.{tournament_id}",
    )
    register_tournament_realtime_update(session, tournament_id, reason)


async def enqueue_encounter_completed(
    session: AsyncSession,
    encounter: models.Encounter,
) -> None:
    winner_team_id: int | None = None
    if encounter.home_score > encounter.away_score:
        winner_team_id = encounter.home_team_id
    elif encounter.away_score > encounter.home_score:
        winner_team_id = encounter.away_team_id

    await enqueue_outbox_event(
        session,
        EncounterCompletedEvent(
            tournament_id=encounter.tournament_id,
            encounter_id=encounter.id,
            home_team_id=encounter.home_team_id,
            away_team_id=encounter.away_team_id,
            winner_team_id=winner_team_id,
            source_service="tournament-service",
        ),
        exchange=TOURNAMENT_EVENTS_EXCHANGE,
        routing_key="tournament.encounter.completed",
    )


async def enqueue_registration_approved(
    session: AsyncSession,
    registration: models.BalancerRegistration,
) -> None:
    await enqueue_outbox_event(
        session,
        RegistrationApprovedEvent(
            tournament_id=registration.tournament_id,
            workspace_id=registration.workspace_id,
            registration_id=registration.id,
            auth_user_id=registration.auth_user_id,
            user_id=registration.user_id,
            battle_tag=registration.battle_tag,
            source_service="tournament-service",
        ),
        exchange=TOURNAMENT_EVENTS_EXCHANGE,
        routing_key="tournament.registration.approved",
    )
    register_tournament_realtime_update(session, registration.tournament_id, "structure_changed")


async def enqueue_registration_rejected(
    session: AsyncSession,
    registration: models.BalancerRegistration,
) -> None:
    await enqueue_outbox_event(
        session,
        RegistrationRejectedEvent(
            tournament_id=registration.tournament_id,
            workspace_id=registration.workspace_id,
            registration_id=registration.id,
            auth_user_id=registration.auth_user_id,
            user_id=registration.user_id,
            battle_tag=registration.battle_tag,
            source_service="tournament-service",
        ),
        exchange=TOURNAMENT_EVENTS_EXCHANGE,
        routing_key="tournament.registration.rejected",
    )
    register_tournament_realtime_update(session, registration.tournament_id, "structure_changed")


async def enqueue_tournament_state_changed(
    session: AsyncSession,
    tournament: models.Tournament,
    *,
    old_status: str | None,
    new_status: str,
) -> None:
    await enqueue_outbox_event(
        session,
        TournamentStateChangedEvent(
            tournament_id=tournament.id,
            workspace_id=tournament.workspace_id,
            old_status=old_status,
            new_status=new_status,
            source_service="tournament-service",
        ),
        exchange=TOURNAMENT_EVENTS_EXCHANGE,
        routing_key="tournament.state.changed",
    )
