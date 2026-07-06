from __future__ import annotations

import traceback

import sqlalchemy as sa
from faststream.exceptions import RejectMessage
from loguru import logger

from src import models
from src.core import db
from src.services.admin import stage as stage_service
from src.services.admin.swiss_rounds import generate_next_swiss_round
from src.services.computation import jobs
from src.services.tournament.events import enqueue_tournament_changed


async def process_bracket_job(job_id: int) -> None:
    async with db.async_session_maker() as session:
        job = await jobs.claim_job(session, job_id, kind="bracket")
    if job is None:
        return

    try:
        async with db.async_session_maker() as session:
            current = await jobs.get_job(session, job_id, for_update=True)
            if current is None or current.status != "running" or current.stage_id is None:
                return

            await session.scalar(
                sa.select(models.Tournament.id).where(models.Tournament.id == current.tournament_id).with_for_update()
            )
            await session.scalar(
                sa.select(models.Stage.id).where(models.Stage.id == current.stage_id).with_for_update()
            )
            generated = await _execute_bracket_operation(session, current)
            await jobs.request_standings_recalculation(session, current.tournament_id)
            await enqueue_tournament_changed(session, current.tournament_id, "structure_changed")
            await jobs.mark_job_succeeded(
                session,
                current,
                {"generated": len(generated), "encounter_ids": [int(encounter.id) for encounter in generated]},
            )
            await session.commit()
    except Exception as exc:
        logger.exception("Bracket computation job failed", job_id=job_id)
        async with db.async_session_maker() as session:
            disposition = await jobs.mark_job_failed(session, job_id, f"{exc}\n{traceback.format_exc()}")
        if disposition == "failed":
            raise RejectMessage() from exc


async def _execute_bracket_operation(
    session,
    job: models.TournamentComputationJob,
) -> list[models.Encounter]:
    payload = dict(job.payload_json or {})
    if job.operation == "generate_stage":
        return await stage_service.generate_encounters(
            session,
            int(job.stage_id),
            notify=False,
            commit=False,
            schedule_standings=False,
        )
    if job.operation == "activate_and_generate":
        _, encounters = await stage_service.activate_and_generate(
            session,
            int(job.stage_id),
            force=bool(payload.get("force", False)),
            notify=False,
            commit=False,
            schedule_standings=False,
        )
        return encounters
    if job.operation == "generate_next_swiss_round":
        return await generate_next_swiss_round(
            session,
            tournament_id=job.tournament_id,
            stage_id=int(job.stage_id),
            stage_item_id=job.stage_item_id,
            expected_next_round=payload.get("next_round"),
        )
    raise ValueError(f"Unsupported bracket operation: {job.operation}")
