"""Per-captain encounter result reporting.

Each captain submits their own report (series score + closeness rating + optional
per-map codes) independently — there is no blocking submit/confirm handshake. The
encounter result is DERIVED from the reports:

- < 2 reports        -> ``pending_confirmation`` (waiting on the other captain).
- 2 reports, scores match -> ``confirmed`` (via ``finalize_encounter_score``,
  which advances the bracket); ``Encounter.closeness`` = average of the two
  ratings / 10.
- 2 reports, scores differ -> ``disputed`` (admin resolves).

A captain may re-submit (upsert) their report until the encounter is confirmed;
afterwards only an admin can change the result (``admin_confirm_result`` /
admin encounter edit).
"""

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.core import http_status as status
from shared.core.enums import EncounterResultStatus, MapPoolEntryStatus
from shared.core.errors import BaseAPIException as HTTPException
from shared.messaging.config import (
    TOURNAMENT_EVENTS_EXCHANGE,
)
from shared.messaging.outbox import enqueue_outbox_event
from shared.schemas.events import EncounterCompletedEvent
from shared.services.challonge_refs import resolve_encounter_challonge
from src import models
from src.services.challonge import sync as challonge_sync
from src.services.encounter.finalize import finalize_encounter_score
from src.services.tournament.events import enqueue_tournament_recalculation

# One per-map code: (map_index 1-based, replay/match code string).
MapCodeInput = tuple[int, str]


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
) -> tuple[str, int, int]:
    """Determine if the auth user is captain of the home or away team.

    Returns ``(side, captain_user_id, team_id)`` where ``captain_user_id`` is the
    linked ``players.user`` id and ``team_id`` the captain's team.
    Raises 403 if the user is not a captain of either team.
    """
    result = await session.execute(select(models.User).where(models.User.auth_user_id == auth_user.id))
    player = result.scalar_one_or_none()

    if player is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No player profile linked to your account",
        )

    if encounter.home_team and encounter.home_team.captain_id == player.id:
        return "home", encounter.home_team.captain_id, encounter.home_team.id
    if encounter.away_team and encounter.away_team.captain_id == player.id:
        return "away", encounter.away_team.captain_id, encounter.away_team.id

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You are not a captain of either team in this encounter",
    )


async def resolve_captain_side(
    session: AsyncSession,
    auth_user: models.AuthUser,
    encounter: models.Encounter,
) -> str:
    side, _captain_user_id, _team_id = await _resolve_captain_identity(session, auth_user, encounter)
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


async def _load_encounter_with_reports(session: AsyncSession, encounter_id: int) -> models.Encounter:
    """Like ``_load_encounter`` but also eager-loads captain reports + map codes."""
    result = await session.execute(
        select(models.Encounter)
        .where(models.Encounter.id == encounter_id)
        .options(
            selectinload(models.Encounter.home_team),
            selectinload(models.Encounter.away_team),
            selectinload(models.Encounter.stage),
            selectinload(models.Encounter.captain_reports).selectinload(
                models.EncounterCaptainReport.map_codes
            ),
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


async def _picked_map_ids(session: AsyncSession, encounter_id: int) -> dict[int, int]:
    """Map ``map_index`` (== 1-based pick order) -> ``map_id`` for a completed pool.

    Returns an empty dict when there is no veto pool (map codes then keep
    ``map_id = NULL``). Soft binding: callers never fail on an index beyond the
    picked count — it simply is not in the dict.
    """
    rows = await session.execute(
        select(models.EncounterMapPool.order, models.EncounterMapPool.map_id)
        .where(
            models.EncounterMapPool.encounter_id == encounter_id,
            models.EncounterMapPool.status == MapPoolEntryStatus.PICKED,
        )
        .order_by(models.EncounterMapPool.order)
    )
    return {int(order): int(map_id) for order, map_id in rows.all() if order is not None}


def serialize_map_code(code: models.EncounterMapCode) -> dict:
    return {
        "id": code.id,
        "map_index": code.map_index,
        "map_id": code.map_id,
        "code": code.code,
    }


def serialize_captain_report(report: models.EncounterCaptainReport, encounter: models.Encounter) -> dict:
    side: str | None = None
    if report.team_id == encounter.home_team_id:
        side = "home"
    elif report.team_id == encounter.away_team_id:
        side = "away"
    return {
        "id": report.id,
        "encounter_id": report.encounter_id,
        "team_id": report.team_id,
        "side": side,
        "reporter_user_id": report.reporter_user_id,
        "home_score": report.home_score,
        "away_score": report.away_score,
        "closeness": report.closeness,
        "map_codes": [serialize_map_code(mc) for mc in sorted(report.map_codes, key=lambda c: c.map_index)],
        "created_at": report.created_at.isoformat() if report.created_at else None,
        "updated_at": report.updated_at.isoformat() if report.updated_at else None,
    }


async def get_encounter_reports(session: AsyncSession, encounter_id: int) -> list[dict]:
    """Read both captains' reports for an encounter (public/read-only)."""
    result = await session.execute(
        select(models.Encounter)
        .where(models.Encounter.id == encounter_id)
        .options(
            selectinload(models.Encounter.captain_reports).selectinload(
                models.EncounterCaptainReport.map_codes
            ),
        )
    )
    encounter = result.scalar_one_or_none()
    if not encounter:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encounter not found")
    return [serialize_captain_report(r, encounter) for r in encounter.captain_reports]


async def _recompute_encounter_result(
    session: AsyncSession,
    encounter: models.Encounter,
    *,
    actor_user_id: int,
) -> bool:
    """Recompute the derived encounter result from its captain reports.

    Returns ``True`` when the encounter was auto-confirmed (so the caller can run
    post-commit side effects like Challonge push).
    """
    reports = list(encounter.captain_reports)
    now = datetime.now(UTC)

    if len(reports) < 2:
        encounter.result_status = EncounterResultStatus.PENDING_CONFIRMATION
        encounter.submitted_by_id = actor_user_id
        encounter.submitted_at = now
        encounter.confirmed_by_id = None
        encounter.confirmed_at = None
        encounter.closeness = None
        await _enqueue_tournament_recalculation(session, encounter.tournament_id)
        return False

    by_team = {r.team_id: r for r in reports}
    home_report = by_team.get(encounter.home_team_id)
    away_report = by_team.get(encounter.away_team_id)

    # Defensive: both team reports must be present for a two-report encounter.
    if home_report is None or away_report is None:
        encounter.result_status = EncounterResultStatus.PENDING_CONFIRMATION
        encounter.submitted_by_id = actor_user_id
        encounter.submitted_at = now
        encounter.closeness = None
        await _enqueue_tournament_recalculation(session, encounter.tournament_id)
        return False

    scores_match = (
        home_report.home_score == away_report.home_score
        and home_report.away_score == away_report.away_score
    )
    avg_closeness = (home_report.closeness + away_report.closeness) / 2.0

    if not scores_match:
        encounter.result_status = EncounterResultStatus.DISPUTED
        encounter.closeness = None
        await _enqueue_tournament_recalculation(session, encounter.tournament_id)
        return False

    encounter.closeness = avg_closeness / 10.0
    await finalize_encounter_score(
        session,
        encounter.id,
        encounter=encounter,
        home_score=home_report.home_score,
        away_score=home_report.away_score,
        source="captain",
        result_status=EncounterResultStatus.CONFIRMED,
        confirmed_by_id=actor_user_id,
        confirmed_at=now,
    )
    await _enqueue_tournament_recalculation(session, encounter.tournament_id)
    await _enqueue_encounter_completed(session, encounter)
    return True


async def submit_captain_report(
    session: AsyncSession,
    auth_user: models.AuthUser,
    encounter_id: int,
    *,
    home_score: int,
    away_score: int,
    closeness: int,
    map_codes: Sequence[MapCodeInput] = (),
) -> models.Encounter:
    """Upsert the calling captain's report and recompute the derived result.

    ``home_score``/``away_score`` are in the encounter's home/away orientation.
    ``map_codes`` are ``(map_index, code)`` pairs; blank codes are ignored and
    ``map_id`` is softly resolved from the veto pool when one is complete.
    """
    if not 1 <= closeness <= 10:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="closeness must be between 1 and 10",
        )
    if home_score < 0 or away_score < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="scores must be non-negative",
        )

    seen_indices: set[int] = set()
    for map_index, _code in map_codes:
        if map_index < 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="map_index must be >= 1",
            )
        if map_index in seen_indices:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"duplicate map_index {map_index}",
            )
        seen_indices.add(map_index)

    encounter = await _load_encounter_with_reports(session, encounter_id)

    if encounter.result_status == EncounterResultStatus.CONFIRMED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Encounter result is confirmed; only an admin can change it",
        )

    _side, captain_user_id, team_id = await _resolve_captain_identity(session, auth_user, encounter)

    report = next((r for r in encounter.captain_reports if r.team_id == team_id), None)
    if report is None:
        report = models.EncounterCaptainReport(encounter_id=encounter.id, team_id=team_id)
        session.add(report)
        encounter.captain_reports.append(report)
    else:
        # Drop existing codes up front so re-inserting the same (report_id,
        # map_index) never collides with rows pending deletion in one flush.
        await session.execute(
            delete(models.EncounterMapCode).where(models.EncounterMapCode.report_id == report.id)
        )
        report.map_codes.clear()

    report.reporter_user_id = captain_user_id
    report.home_score = home_score
    report.away_score = away_score
    report.closeness = closeness

    # Ensure the (possibly new) report has an id before attaching codes.
    await session.flush()

    map_id_by_index = await _picked_map_ids(session, encounter_id)
    for map_index, code in map_codes:
        clean = (code or "").strip()
        if not clean:
            continue
        report.map_codes.append(
            models.EncounterMapCode(
                map_index=map_index,
                code=clean,
                map_id=map_id_by_index.get(map_index),
            )
        )

    confirmed = await _recompute_encounter_result(session, encounter, actor_user_id=captain_user_id)
    await session.commit()

    if confirmed:
        challonge_links = await resolve_encounter_challonge(session, [encounter.id])
        if challonge_links.get(encounter.id) is not None:
            await challonge_sync.auto_push_on_confirm(session, encounter.id)

    await session.refresh(encounter)
    return encounter


async def admin_confirm_result(
    session: AsyncSession,
    encounter_id: int,
) -> models.Encounter:
    """Admin force-confirms a pending/disputed result without captain checks.

    Uses the encounter's current score (an admin may have edited it while
    resolving a dispute). When captain reports exist, the final closeness is set
    to their average; otherwise the admin-set value is left untouched.
    """
    encounter = await _load_encounter_with_reports(session, encounter_id)

    if encounter.result_status not in (
        EncounterResultStatus.PENDING_CONFIRMATION,
        EncounterResultStatus.DISPUTED,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No pending or disputed result to confirm",
        )

    closeness_values = [r.closeness for r in encounter.captain_reports]
    if closeness_values:
        encounter.closeness = (sum(closeness_values) / len(closeness_values)) / 10.0

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
