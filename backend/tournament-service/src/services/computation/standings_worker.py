from __future__ import annotations

import traceback

import sqlalchemy as sa
from faststream.exceptions import RejectMessage
from loguru import logger

from src import models
from src.core import db
from src.services.computation import jobs
from src.services.standings import service as standings_service
from src.services.standings import swiss_auto_round
from src.services.tournament.events import enqueue_tournament_changed


async def process_standings_job(job_id: int) -> None:
    async with db.async_session_maker() as session:
        job = await jobs.claim_job(session, job_id, kind="standings")
    if job is None:
        return

    try:
        async with db.async_session_maker() as session:
            current = await jobs.get_job(session, job_id, for_update=True)
            if current is None or current.status != "running":
                return
            await session.scalar(
                sa.select(models.Tournament.id).where(models.Tournament.id == current.tournament_id).with_for_update()
            )
            generation = int((current.payload_json or {}).get("generation", 0))
            standings = await standings_service.recalculate_for_tournament(
                session,
                current.tournament_id,
                commit=False,
            )
            state = await jobs.complete_standings_generation(session, current.tournament_id, generation)
            await swiss_auto_round.enqueue_swiss_next_rounds(session, current.tournament_id)
            await enqueue_tournament_changed(session, current.tournament_id, "results_changed")
            await jobs.mark_job_succeeded(
                session,
                current,
                {
                    "generation": generation,
                    "standing_count": len(standings),
                },
            )
            await session.flush()
            if state.requested_generation > state.completed_generation:
                await jobs.request_followup_standings_job(session, current.tournament_id)
            await session.commit()
    except Exception as exc:
        logger.exception("Standings computation job failed", job_id=job_id)
        async with db.async_session_maker() as session:
            disposition = await jobs.mark_job_failed(session, job_id, f"{exc}\n{traceback.format_exc()}")
        if disposition == "failed":
            raise RejectMessage() from exc
