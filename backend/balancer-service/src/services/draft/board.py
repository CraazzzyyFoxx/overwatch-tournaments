"""Read-side helpers: active-session lookup and the board snapshot."""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from cashews import cache
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import DraftStatus
from shared.models.balancer.draft import DraftPick, DraftPlayer, DraftSession, DraftTeam
from shared.models.platform.realtime import WorkspaceEvent
from shared.services import realtime_topics
from src.schemas.draft import (
    DraftBoardSnapshot,
    DraftPickRead,
    DraftPlayerRead,
    DraftSessionRead,
    DraftTeamRead,
)
from src.services.draft import loaders

# Registration `notes` stay public: captains read them in the Player Inspector
# while drafting. Only organizer-side metadata is stripped from the snapshot.
_PRIVATE_ADDITIONAL_INFO_KEYS = frozenset({"admin_notes", "audit_reason"})
_ACTIVE = (
    DraftStatus.SETUP.value,
    DraftStatus.READY.value,
    DraftStatus.LIVE.value,
    DraftStatus.PAUSED.value,
)

# Safety-net TTL for the public board cache: the event-id in the key already
# invalidates on every persisted draft event, so the TTL only bounds staleness
# for hypothetical writes that bypass the event log and expires dead keys.
_BOARD_CACHE_TTL = "5s"


def _board_cache_key(session_id: int, last_event_id: int | None) -> str:
    # The "backend:" prefix routes the key to the backend configured by
    # cache.setup() (cashews routes strictly by key prefix).
    return f"backend:balancer:draft_board:{session_id}:{last_event_id or 0}"


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


def public_additional_info(additional_info: dict | None) -> dict:
    """Remove organizer-only metadata from the public draft snapshot."""

    return {
        key: value
        for key, value in (additional_info or {}).items()
        if key not in _PRIVATE_ADDITIONAL_INFO_KEYS
    }


async def build_board(session: AsyncSession, draft_session: DraftSession) -> DraftBoardSnapshot:
    # The cheap max-event-id read runs on every request and doubles as the
    # cache key: every draft mutation persists a WorkspaceEvent in the same
    # transaction (services.draft.realtime), so new event -> new key -> fresh
    # board, and an unchanged id can safely serve the cached snapshot.
    topic = realtime_topics.draft(draft_session.tournament_id)
    last_event_id = await session.scalar(
        sa.select(sa.func.max(WorkspaceEvent.id)).where(WorkspaceEvent.topic == topic)
    )
    cache_key = _board_cache_key(draft_session.id, last_event_id)
    if cache.is_setup():
        try:
            cached = await cache.get(cache_key)
        except Exception:  # noqa: BLE001 — cache is best-effort
            cached = None
        if cached is not None:
            # server_time drives client clock sync; never serve a stale one.
            return cached.model_copy(update={"server_time": datetime.now(UTC)})

    # DraftTeamRead reads captain_user_id, DraftPickRead reads picked_by_user_id,
    # DraftPlayerRead reads user_id/secondary_roles_json/role_ranks/role_top_heroes
    # — eager-load the relationships those compat properties resolve through.
    teams = (
        await session.scalars(
            sa.select(DraftTeam)
            .where(DraftTeam.session_id == draft_session.id)
            .order_by(DraftTeam.draft_position.asc())
            .options(*loaders.team_options())
        )
    ).all()
    picks = (
        await session.scalars(
            sa.select(DraftPick)
            .where(DraftPick.session_id == draft_session.id)
            .order_by(DraftPick.overall_no.asc())
            .options(*loaders.pick_options())
        )
    ).all()
    players = (
        await session.scalars(
            sa.select(DraftPlayer)
            .where(DraftPlayer.session_id == draft_session.id)
            .order_by(DraftPlayer.id.asc())
            .options(*loaders.player_options())
        )
    ).all()

    # The current pick always belongs to this session, so it is among `picks`
    # (loaded with pick_options above) — no extra fetch needed.
    current = (
        next((p for p in picks if p.id == draft_session.current_pick_id), None)
        if draft_session.current_pick_id
        else None
    )
    snapshot = DraftBoardSnapshot(
        session=DraftSessionRead.model_validate(draft_session),
        teams=[DraftTeamRead.model_validate(t) for t in teams],
        picks=[DraftPickRead.model_validate(p) for p in picks],
        players=[
            DraftPlayerRead.model_validate(p).model_copy(
                update={"additional_info": public_additional_info(p.additional_info)}
            )
            for p in players
        ],
        current_pick=DraftPickRead.model_validate(current) if current else None,
        server_time=datetime.now(UTC),
        last_event_id=last_event_id,
    )
    if cache.is_setup():
        try:
            await cache.set(cache_key, snapshot, expire=_BOARD_CACHE_TTL)
        except Exception:  # noqa: BLE001 — cache is best-effort
            pass
    return snapshot
