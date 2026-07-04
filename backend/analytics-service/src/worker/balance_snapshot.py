"""Consume balancer ``balance_exported`` events into analytics snapshots.

analytics-service owns the write side of ``analytics.balance_snapshot`` +
``analytics.balance_player_snapshot``. balancer-service emits a fully
denormalized :class:`BalanceExportedEvent` via its transactional outbox; this
consumer materializes both tables.

Idempotency: outbox delivery is at-least-once and a balance can be re-exported,
so the writer upserts on the ``(tournament_id, balance_id)`` unique constraint by
deleting any existing snapshot (player rows cascade) before inserting. Both a
duplicate of the same event and a fresh re-export converge to one snapshot row.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from faststream.rabbit.annotations import RabbitMessage
from shared.messaging.config import (
    ANALYTICS_BALANCE_SNAPSHOT_QUEUE,
    BALANCER_EVENTS_EXCHANGE,
)
from shared.observability import observe_message_processing
from shared.schemas.events import BalanceExportedEvent
from sqlalchemy.ext.asyncio import AsyncSession

from src import models


async def write_balance_snapshot(
    session: AsyncSession, event: BalanceExportedEvent
) -> models.AnalyticsBalanceSnapshot:
    """Write (upsert) the balance snapshot + per-player rows for one event.

    Deletes any existing snapshot for ``(tournament_id, balance_id)`` first; the
    player rows cascade via the FK, so re-delivery/re-export stays idempotent.
    Does not commit — the caller owns the transaction boundary.
    """
    await session.execute(
        sa.delete(models.AnalyticsBalanceSnapshot).where(
            models.AnalyticsBalanceSnapshot.tournament_id == event.tournament_id,
            models.AnalyticsBalanceSnapshot.balance_id == event.balance_id,
        )
    )
    # Flush the delete before inserting so the unique constraint sees a clean slate.
    await session.flush()

    snapshot = models.AnalyticsBalanceSnapshot(
        tournament_id=event.tournament_id,
        balance_id=event.balance_id,
        variant_id=event.variant_id,
        workspace_id=event.workspace_id,
        algorithm=event.algorithm,
        division_scope=event.division_scope,
        division_grid_json=event.division_grid_json,
        team_count=event.team_count,
        player_count=event.player_count,
        avg_sr_overall=event.avg_sr_overall,
        sr_std_dev=event.sr_std_dev,
        sr_range=event.sr_range,
        total_discomfort=event.total_discomfort,
        off_role_count=event.off_role_count,
        objective_score=event.objective_score,
    )
    session.add(snapshot)
    await session.flush()

    for player in event.players:
        session.add(
            models.AnalyticsBalancePlayerSnapshot(
                balance_snapshot_id=snapshot.id,
                tournament_id=event.tournament_id,
                user_id=player.user_id,
                team_id=player.team_id,
                assigned_role=player.assigned_role,
                preferred_role=player.preferred_role,
                assigned_rank=player.assigned_rank,
                discomfort=player.discomfort,
                division_number=player.division_number,
                is_captain=player.is_captain,
                was_off_role=player.was_off_role,
            )
        )

    return snapshot


def register(broker: Any, logger: Any) -> None:
    """Register the ``balance_exported`` consumer on the worker broker."""

    from src.core import db

    @broker.subscriber(ANALYTICS_BALANCE_SNAPSHOT_QUEUE, exchange=BALANCER_EVENTS_EXCHANGE)
    async def consume_balance_exported(data: dict, msg: RabbitMessage) -> None:
        async with observe_message_processing(
            queue=ANALYTICS_BALANCE_SNAPSHOT_QUEUE,
            handler="consume_balance_exported",
            message=msg,
            logger=logger,
        ):
            event = BalanceExportedEvent.model_validate(data)
            logger.bind(
                tournament_id=event.tournament_id,
                balance_id=event.balance_id,
            ).info("Writing balance snapshot from balance_exported event")
            async with db.async_session_maker() as session:
                await write_balance_snapshot(session, event)
                await session.commit()
