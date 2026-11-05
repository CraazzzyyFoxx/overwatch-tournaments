"""Time-driven node transitions (the tournament-worker tick), spec §9.

Each due ``flow_node_schedule`` row moves its node forward from the exact status its phase starts from
(``SCHEDULE_TRANSITIONS``: registration ``open`` draft→open and ``check_in`` open→check_in, formation ``start``
draft→forming, stage ``start`` ready→live), so the tick can never undo an admin's move (plan Decision 4). A tournament
with ``auto_transitions_enabled = False`` is never touched.

Candidates are picked with a coarse SQL filter, then each is handled in its own session: the tournament is locked
first and the node second (the order ``FlowNodeService.transition`` takes), the due-ness is re-checked under the
locks and the node is moved with ``flow_node_service.transition(automated=True)``. One transaction per node, so a
failure in one never aborts the loop.
"""

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from shared import models
from shared.core.enums import FlowNodeKind
from shared.core.errors import ApiHTTPException
from shared.core.flow_state import SCHEDULE_TRANSITIONS
from shared.core.tournament_state import as_utc
from src.services.flow.lifecycle import flow_node_service

__all__ = ("run_due_transitions",)


async def run_due_transitions(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[dict[str, Any]]:
    """Apply every due node transition; returns one result dict per attempt."""
    node, schedule = models.FlowNode, models.FlowNodeSchedule
    at_source = sa.or_(
        *(
            sa.and_(node.kind == kind, schedule.phase == phase, node.status == source)
            for (kind, phase), (source, _target) in SCHEDULE_TRANSITIONS.items()
        )
    )
    async with session_factory() as session:
        rows = (
            await session.execute(
                sa.select(schedule.node_id, schedule.phase, node.tournament_id)
                .join(node, node.id == schedule.node_id)
                .join(models.Tournament, models.Tournament.id == node.tournament_id)
                .where(
                    models.Tournament.auto_transitions_enabled.is_(True),
                    schedule.starts_at <= sa.func.now(),
                    at_source,
                )
                .order_by(schedule.starts_at, schedule.node_id)
            )
        ).all()

    results: list[dict[str, Any]] = []
    for node_id, phase, tournament_id in rows:
        base = {"node_id": node_id, "tournament_id": tournament_id}
        async with session_factory() as session:
            try:
                tournament = await flow_node_service.lock_tournament(session, tournament_id)
                locked = await session.scalar(
                    sa.select(node)
                    .where(node.id == node_id)
                    .with_for_update(key_share=True)
                    .execution_options(populate_existing=True)
                )
                row = await session.scalar(
                    sa.select(schedule).where(schedule.node_id == node_id, schedule.phase == phase)
                )
                if locked is None or row is None or not tournament.auto_transitions_enabled:
                    continue
                source, target = SCHEDULE_TRANSITIONS[(FlowNodeKind(locked.kind), phase)]
                now = datetime.now(UTC)
                if locked.status != source.value or as_utc(row.starts_at) > now:
                    continue

                await flow_node_service.transition(session, node_id, target, automated=True, actor=None)
                await session.commit()
                lag_seconds = (now - as_utc(row.starts_at)).total_seconds()
                logger.info(
                    "Auto-transitioned flow node",
                    node_id=node_id,
                    tournament_id=tournament_id,
                    old_status=source.value,
                    new_status=target.value,
                    scheduled_at=row.starts_at.isoformat(),
                    lag_seconds=lag_seconds,
                )
                results.append(
                    {
                        **base,
                        "status": "success",
                        "old_status": source.value,
                        "new_status": target.value,
                        "lag_seconds": lag_seconds,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                if isinstance(exc, ApiHTTPException) and exc.status_code == 409:
                    # A refused move (no registration form yet, an input not final) is "not ready", not broken: the
                    # row stays due every 30 s until someone fixes it, and a stack trace per pass would be a log flood.
                    results.append({**base, "status": "skipped", "reason": exc.detail[0]["code"]})
                    continue
                logger.exception("Failed to auto-transition flow node", **base)
                results.append({**base, "status": "failed", "error": str(exc)})
    return results
