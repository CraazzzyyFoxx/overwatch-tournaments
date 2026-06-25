"""Read/validation helpers for the match-log admin surface.

Extracted verbatim from the former ``src/routes/admin/logs.py`` HTTP route so the
typed-RPC handlers (``src/rpc/logs.py``) can reuse them after the FastAPI face was
removed.

``HTTPException`` here is ``fastapi.HTTPException`` on purpose: the parser RPC
envelope (``src/rpc/_common.py``) maps ``fastapi.HTTPException`` onto the
``{ok,data,error}`` envelope, and a Starlette base-class instance would not be
caught by that ``except`` clause (it is a strict subclass). The rest of the
``src/services/match_logs`` layer (``uploads.py``) raises the same type.
"""

from __future__ import annotations

import httpx
from shared.core.errors import BaseAPIException as HTTPException
from shared.core import http_status as status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.core import config
from src.schemas.admin.logs import QueueDepth

MONITORED_QUEUES = [
    "process_match_log",
    "process_tournament_logs",
    "discord_commands",
    "balancer_jobs",
]


async def _fetch_queue_depths() -> list[QueueDepth]:
    """Query RabbitMQ Management API for queue depths."""
    cfg = config.settings
    base = cfg.rabbitmq_management_url.rstrip("/")
    auth_tuple = (cfg.rabbitmq_management_user, cfg.rabbitmq_management_password)
    depths: list[QueueDepth] = []
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            for queue_name in MONITORED_QUEUES:
                url = f"{base}/api/queues/%2F/{queue_name}"
                resp = await client.get(url, auth=auth_tuple)
                if resp.status_code == 200:
                    data = resp.json()
                    depths.append(
                        QueueDepth(
                            name=queue_name,
                            messages_ready=data.get("messages_ready", 0),
                            messages_unacknowledged=data.get("messages_unacknowledged", 0),
                            consumers=data.get("consumers", 0),
                        )
                    )
                elif resp.status_code == 404:
                    depths.append(QueueDepth(name=queue_name, messages_ready=-1, messages_unacknowledged=-1, consumers=0, status="not_found"))
                else:
                    depths.append(QueueDepth(name=queue_name, messages_ready=-1, messages_unacknowledged=-1, consumers=0, status="error"))
    except Exception as exc:
        logger.warning(f"Failed to fetch queue depths from RabbitMQ management API: {exc}")
        for queue_name in MONITORED_QUEUES:
            depths.append(QueueDepth(name=queue_name, messages_ready=-1, messages_unacknowledged=-1, consumers=0, status="error"))
    return depths


def _record_to_dict(record: models.LogProcessingRecord) -> dict:
    return {
        "id": record.id,
        "tournament_id": record.tournament_id,
        "tournament_name": record.tournament.name if record.tournament else None,
        "attached_encounter_id": record.attached_encounter_id,
        "attached_encounter_name": record.attached_encounter.name if record.attached_encounter else None,
        "filename": record.filename,
        "status": record.status.value if hasattr(record.status, "value") else record.status,
        "source": record.source.value if hasattr(record.source, "value") else record.source,
        "uploader_name": record.uploader.name if record.uploader else None,
        "error_message": record.error_message,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "started_at": record.started_at.isoformat() if record.started_at else None,
        "finished_at": record.finished_at.isoformat() if record.finished_at else None,
    }


async def _validate_attached_encounter(
    session: AsyncSession,
    *,
    tournament_id: int,
    encounter_id: int | None,
) -> models.Encounter | None:
    if encounter_id is None:
        return None

    result = await session.execute(select(models.Encounter).where(models.Encounter.id == encounter_id).limit(1))
    encounter = result.scalar_one_or_none()
    if encounter is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encounter not found")
    if encounter.tournament_id != tournament_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Encounter does not belong to this tournament",
        )
    return encounter
