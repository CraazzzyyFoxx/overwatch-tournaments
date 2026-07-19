"""Time-driven tournament status transitions (the tournament-worker tick).

Advances ``Tournament.status`` forward along its ``tournament_phase_schedule``
rows (see ``shared.core.tournament_state``). Automation only moves forward and
only up to LIVE; PLAYOFFS/COMPLETED stay manual/event-driven. Tournaments in
manual mode (``auto_transitions_enabled = False``) are never touched.

Candidates are picked with a coarse SQL filter (enabled + source status + any
due schedule row), then each is re-locked ``FOR UPDATE SKIP LOCKED`` in its own
session and re-checked with the precise pure helper ``next_due_status`` before
transitioning — one transaction per tournament, so a failure in one never
aborts the loop (pattern of ``sync_due_google_sheet_feeds``).
"""

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from shared.core import tournament_state
from src import models
from src.services.admin import tournament as admin_tournament_service

__all__ = ("run_due_transitions",)


async def run_due_transitions(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[dict[str, Any]]:
    """Apply every due phase transition; returns one result dict per attempt."""
    async with session_factory() as session:
        result = await session.execute(
            sa.select(models.Tournament.id)
            .where(
                models.Tournament.auto_transitions_enabled.is_(True),
                models.Tournament.status.in_(tournament_state.AUTO_TRANSITION_SOURCE_STATUSES),
                sa.exists().where(
                    models.TournamentPhaseSchedule.tournament_id == models.Tournament.id,
                    models.TournamentPhaseSchedule.starts_at <= sa.func.now(),
                ),
            )
            .order_by(models.Tournament.id.asc())
        )
        candidate_ids = list(result.scalars().all())

    results: list[dict[str, Any]] = []
    for tournament_id in candidate_ids:
        # ``transition_status`` commits internally (releasing the row lock), so
        # each candidate gets its own session: re-lock, re-check due-ness under
        # the lock, then transition in the same session/transaction chain.
        async with session_factory() as session:
            try:
                result = await session.execute(
                    sa.select(models.Tournament)
                    .where(
                        models.Tournament.id == tournament_id,
                        models.Tournament.auto_transitions_enabled.is_(True),
                        models.Tournament.status.in_(tournament_state.AUTO_TRANSITION_SOURCE_STATUSES),
                    )
                    .with_for_update(of=models.Tournament, skip_locked=True)
                )
                tournament = result.scalar_one_or_none()
                if tournament is None:
                    continue

                now = datetime.now(UTC)
                schedule = list(tournament.phase_schedule)
                target = tournament_state.next_due_status(tournament.status, schedule, now)
                if target is None:
                    continue

                old_status = tournament.status
                scheduled_at = next(
                    (entry.starts_at for entry in schedule if entry.status == target),
                    None,
                )
                if scheduled_at is not None and scheduled_at.tzinfo is None:
                    scheduled_at = scheduled_at.replace(tzinfo=UTC)
                await admin_tournament_service.transition_status(
                    session,
                    tournament_id,
                    target,
                    automated=True,
                )
                lag_seconds = (now - scheduled_at).total_seconds() if scheduled_at is not None else None
                logger.info(
                    "Auto-transitioned tournament",
                    tournament_id=tournament_id,
                    old_status=old_status.value,
                    new_status=target.value,
                    scheduled_at=scheduled_at.isoformat() if scheduled_at is not None else None,
                    lag_seconds=lag_seconds,
                )
                results.append(
                    {
                        "tournament_id": tournament_id,
                        "status": "success",
                        "old_status": old_status.value,
                        "new_status": target.value,
                        "lag_seconds": lag_seconds,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Failed to auto-transition tournament", tournament_id=tournament_id)
                results.append(
                    {
                        "tournament_id": tournament_id,
                        "status": "failed",
                        "error": str(exc),
                    }
                )
    return results
