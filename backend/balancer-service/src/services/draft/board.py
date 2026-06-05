"""Read-side helpers: active-session lookup and the board snapshot."""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import DraftStatus
from shared.models.draft import DraftPick, DraftPlayer, DraftSession, DraftTeam
from shared.models.realtime import WorkspaceEvent
from shared.services import realtime_topics

from src.schemas.draft import (
    DraftBoardSnapshot,
    DraftPickRead,
    DraftPlayerRead,
    DraftSessionRead,
    DraftTeamRead,
)

_ACTIVE = (
    DraftStatus.SETUP.value,
    DraftStatus.READY.value,
    DraftStatus.LIVE.value,
    DraftStatus.PAUSED.value,
)


async def get_active_session(session: AsyncSession, tournament_id: int) -> DraftSession | None:
    active = await session.scalar(
        sa.select(DraftSession)
        .where(DraftSession.tournament_id == tournament_id, DraftSession.status.in_(_ACTIVE))
        .order_by(DraftSession.id.desc())
        .limit(1)
    )
    if active is not None:
        return active
    # Fall back to the most recent (e.g. COMPLETED) session for read-only views.
    return await session.scalar(
        sa.select(DraftSession)
        .where(DraftSession.tournament_id == tournament_id)
        .order_by(DraftSession.id.desc())
        .limit(1)
    )


async def build_board(session: AsyncSession, draft_session: DraftSession) -> DraftBoardSnapshot:
    teams = (
        await session.scalars(
            sa.select(DraftTeam)
            .where(DraftTeam.session_id == draft_session.id)
            .order_by(DraftTeam.draft_position.asc())
        )
    ).all()
    picks = (
        await session.scalars(
            sa.select(DraftPick).where(DraftPick.session_id == draft_session.id).order_by(DraftPick.overall_no.asc())
        )
    ).all()
    players = (
        await session.scalars(
            sa.select(DraftPlayer)
            .where(DraftPlayer.session_id == draft_session.id)
            .order_by(DraftPlayer.id.asc())
        )
    ).all()
    current = await session.get(DraftPick, draft_session.current_pick_id) if draft_session.current_pick_id else None
    topic = realtime_topics.draft(draft_session.tournament_id)
    last_event_id = await session.scalar(sa.select(sa.func.max(WorkspaceEvent.id)).where(WorkspaceEvent.topic == topic))
    return DraftBoardSnapshot(
        session=DraftSessionRead.model_validate(draft_session),
        teams=[DraftTeamRead.model_validate(t) for t in teams],
        picks=[DraftPickRead.model_validate(p) for p in picks],
        players=[DraftPlayerRead.model_validate(p) for p in players],
        current_pick=DraftPickRead.model_validate(current) if current else None,
        server_time=datetime.now(UTC),
        last_event_id=last_event_id,
    )
