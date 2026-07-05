"""Captain match result submission: submit, confirm, dispute."""

from datetime import UTC, datetime

from shared.core import http_status as status
from shared.core.enums import EncounterResultStatus
from shared.core.errors import BaseAPIException as HTTPException
from shared.messaging.config import (
    TOURNAMENT_EVENTS_EXCHANGE,
)
from shared.messaging.outbox import enqueue_outbox_event
from shared.schemas.events import EncounterCompletedEvent
from shared.services.challonge_refs import resolve_encounter_challonge
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src import models
from src.services.challonge import sync as challonge_sync
from src.services.encounter.finalize import finalize_encounter_score
from src.services.tournament.events import enqueue_tournament_recalculation


async def _enqueue_tournament_recalculation(
    session: AsyncSession,
    tournament_id: int,
) -> None:
    await enqueue_tournament_recalculation(session, tournament_id)


async def _enqueue_encounter_completed(
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


async def _resolve_captain_identity(
    session: AsyncSession,
    auth_user: models.AuthUser,
    encounter: models.Encounter,
) -> tuple[str, int]:
    """Determine if the auth user is captain of home or away team.

    Returns side and linked players.user id.
    Raises 403 if user is not a captain of either team.
    """
    result = await session.execute(select(models.User).where(models.User.auth_user_id == auth_user.id))
    player = result.scalar_one_or_none()

    if player is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No player profile linked to your account",
        )

    if encounter.home_team and encounter.home_team.captain_id == player.id:
        return "home", encounter.home_team.captain_id
    if encounter.away_team and encounter.away_team.captain_id == player.id:
        return "away", encounter.away_team.captain_id

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You are not a captain of either team in this encounter",
    )


async def resolve_captain_side(
    session: AsyncSession,
    auth_user: models.AuthUser,
    encounter: models.Encounter,
) -> str:
    side, _captain_player_id = await _resolve_captain_identity(session, auth_user, encounter)
    return side


async def _load_encounter(session: AsyncSession, encounter_id: int) -> models.Encounter:
    result = await session.execute(
        select(models.Encounter)
        .where(models.Encounter.id == encounter_id)
        .options(
            selectinload(models.Encounter.home_team),
            selectinload(models.Encounter.away_team),
            selectinload(models.Encounter.stage),
        )
        .with_for_update(nowait=False)
    )
    encounter = result.scalar_one_or_none()
    if not encounter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Encounter not found",
        )
    return encounter


async def submit_result(
    session: AsyncSession,
    auth_user: models.AuthUser,
    encounter_id: int,
    home_score: int,
    away_score: int,
) -> models.Encounter:
    """Captain submits a match result. Sets status to pending_confirmation."""
    encounter = await _load_encounter(session, encounter_id)

    if encounter.result_status not in (
        EncounterResultStatus.NONE,
        EncounterResultStatus.DISPUTED,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot submit: result status is '{encounter.result_status}'",
        )

    _side, captain_player_id = await _resolve_captain_identity(session, auth_user, encounter)

    encounter.home_score = home_score
    encounter.away_score = away_score
    encounter.result_status = EncounterResultStatus.PENDING_CONFIRMATION
    encounter.submitted_by_id = captain_player_id
    encounter.submitted_at = datetime.now(UTC)
    encounter.confirmed_by_id = None
    encounter.confirmed_at = None

    tournament_id = encounter.tournament_id
    await _enqueue_tournament_recalculation(session, tournament_id)
    await session.commit()
    await session.refresh(encounter)
    return encounter


async def confirm_result(
    session: AsyncSession,
    auth_user: models.AuthUser,
    encounter_id: int,
) -> models.Encounter:
    """Opposing captain confirms the submitted result."""
    encounter = await _load_encounter(session, encounter_id)

    if encounter.result_status != EncounterResultStatus.PENDING_CONFIRMATION:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No pending result to confirm",
        )

    _side, captain_player_id = await _resolve_captain_identity(session, auth_user, encounter)

    # Must be the OTHER captain (not the one who submitted)
    if encounter.submitted_by_id == captain_player_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot confirm your own submission - the other captain must confirm",
        )

    tournament_id = encounter.tournament_id
    await finalize_encounter_score(
        session,
        encounter.id,
        encounter=encounter,
        home_score=encounter.home_score,
        away_score=encounter.away_score,
        source="captain",
        result_status=EncounterResultStatus.CONFIRMED,
        confirmed_by_id=captain_player_id,
        confirmed_at=datetime.now(UTC),
    )
    await _enqueue_tournament_recalculation(session, tournament_id)
    await _enqueue_encounter_completed(session, encounter)
    await session.commit()

    # Auto-push to Challonge if linked (derived from challonge_match_mapping).
    challonge_links = await resolve_encounter_challonge(session, [encounter.id])
    if challonge_links.get(encounter.id) is not None:
        await challonge_sync.auto_push_on_confirm(session, encounter.id)

    await session.refresh(encounter)
    return encounter


async def submit_match_report(
    session: AsyncSession,
    auth_user: models.AuthUser,
    encounter_id: int,
    home_score: int,
    away_score: int,
    closeness_score: int,
) -> models.Encounter:
    """Captain submits the encounter-level result.

    Match rows are created by log ingestion only, so manual reports update the
    Encounter record and do not touch ``matches.match`` or map-veto state.
    - closeness_score in 1..10 is stored as encounter.closeness = score / 10.
    - Sets result_status = PENDING_CONFIRMATION so the other captain confirms.
    """
    if not 1 <= closeness_score <= 10:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="closeness must be between 1 and 10",
        )
    encounter = await _load_encounter(session, encounter_id)

    if encounter.result_status not in (
        EncounterResultStatus.NONE,
        EncounterResultStatus.DISPUTED,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(f"Cannot submit: result status is '{encounter.result_status}'"),
        )

    _side, captain_player_id = await _resolve_captain_identity(session, auth_user, encounter)

    now = datetime.now(UTC)
    encounter.home_score = home_score
    encounter.away_score = away_score
    encounter.closeness = closeness_score / 10.0
    encounter.result_status = EncounterResultStatus.PENDING_CONFIRMATION
    encounter.submitted_by_id = captain_player_id
    encounter.submitted_at = now
    encounter.confirmed_by_id = None
    encounter.confirmed_at = None

    tournament_id = encounter.tournament_id
    await _enqueue_tournament_recalculation(session, tournament_id)
    await session.commit()
    await session.refresh(encounter)
    return encounter


async def admin_confirm_result(
    session: AsyncSession,
    encounter_id: int,
) -> models.Encounter:
    """Admin force-confirms a pending result without captain check."""
    encounter = await _load_encounter(session, encounter_id)

    if encounter.result_status != EncounterResultStatus.PENDING_CONFIRMATION:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No pending result to confirm",
        )

    tournament_id = encounter.tournament_id
    await finalize_encounter_score(
        session,
        encounter.id,
        encounter=encounter,
        home_score=encounter.home_score,
        away_score=encounter.away_score,
        source="admin",
        result_status=EncounterResultStatus.CONFIRMED,
        confirmed_at=datetime.now(UTC),
    )
    await _enqueue_tournament_recalculation(session, tournament_id)
    await _enqueue_encounter_completed(session, encounter)
    await session.commit()

    challonge_links = await resolve_encounter_challonge(session, [encounter.id])
    if challonge_links.get(encounter.id) is not None:
        await challonge_sync.auto_push_on_confirm(session, encounter.id)

    await session.refresh(encounter)
    return encounter


async def dispute_result(
    session: AsyncSession,
    auth_user: models.AuthUser,
    encounter_id: int,
    reason: str | None = None,
) -> models.Encounter:
    """Either captain disputes the submitted result."""
    encounter = await _load_encounter(session, encounter_id)

    if encounter.result_status != EncounterResultStatus.PENDING_CONFIRMATION:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No pending result to dispute",
        )

    await resolve_captain_side(session, auth_user, encounter)

    encounter.result_status = EncounterResultStatus.DISPUTED

    tournament_id = encounter.tournament_id
    await _enqueue_tournament_recalculation(session, tournament_id)
    await session.commit()
    await session.refresh(encounter)
    return encounter
