from __future__ import annotations

import sqlalchemy as sa
from shared.messaging.config import (
    TOURNAMENT_CHANGED_EXCHANGE,
    TOURNAMENT_EVENTS_EXCHANGE,
)
from shared.messaging.outbox import enqueue_outbox_event
from shared.schemas.events import (
    EncounterCompletedEvent,
    RegistrationApprovedEvent,
    RegistrationRejectedEvent,
    TournamentChangedEvent,
    TournamentChangedReason,
    TournamentStateChangedEvent,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.services.computation.jobs import request_standings_recalculation
from src.services.tournament.realtime_commit import register_tournament_realtime_update


async def enqueue_tournament_recalculation(
    session: AsyncSession,
    tournament_id: int,
) -> None:
    await request_standings_recalculation(session, tournament_id)
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
        exchange=TOURNAMENT_CHANGED_EXCHANGE,
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


async def get_registration_workspace_id(session: AsyncSession, tournament_id: int) -> int:
    # BalancerRegistration has no denormalized workspace_id column — derive it via
    # the owning tournament (registrations are always tournament-scoped).
    workspace_id = await session.scalar(
        sa.select(models.Tournament.workspace_id).where(models.Tournament.id == tournament_id)
    )
    assert workspace_id is not None, f"Tournament {tournament_id} has no workspace_id"
    return int(workspace_id)


async def get_registration_player_id(
    session: AsyncSession,
    registration: models.BalancerRegistration,
) -> int | None:
    """The registration's domain player id (players.user.id), via its member.

    workspace_member_id is the row's only identity anchor (dbarch02 dropped
    user_id); an explicit scalar query avoids lazy-loading the relationship in
    async code. Registrations without a member have no player identity.
    """
    if registration.workspace_member_id is None:
        return None
    return await session.scalar(
        sa.select(models.WorkspaceMember.player_id).where(
            models.WorkspaceMember.id == registration.workspace_member_id
        )
    )


async def enqueue_registration_approved(
    session: AsyncSession,
    registration: models.BalancerRegistration,
) -> None:
    workspace_id = await get_registration_workspace_id(session, registration.tournament_id)
    await enqueue_outbox_event(
        session,
        RegistrationApprovedEvent(
            tournament_id=registration.tournament_id,
            workspace_id=workspace_id,
            registration_id=registration.id,
            user_id=await get_registration_player_id(session, registration),
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
    workspace_id = await get_registration_workspace_id(session, registration.tournament_id)
    await enqueue_outbox_event(
        session,
        RegistrationRejectedEvent(
            tournament_id=registration.tournament_id,
            workspace_id=workspace_id,
            registration_id=registration.id,
            user_id=await get_registration_player_id(session, registration),
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
