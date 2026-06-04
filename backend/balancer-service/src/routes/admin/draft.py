"""Live Draft REST routes (balancer-service, mounted under /api/balancer/draft).

Public reads (no auth) for spectating; admin lifecycle keyed by tournament_id;
pick actions keyed by pick_id. Every mutation commits then publishes a realtime
event on tournament:{id}:draft. Captain identity for /select is enforced in the
service; the permission dep only checks workspace membership.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import DraftAutopickStrategy, DraftRole
from shared.core.errors import ApiHTTPException
from shared.models.draft import DraftPick, DraftSession

from src import models
from src.core import auth, db
from src.core.config import config
from src.schemas.draft import (
    DraftBoardSnapshot,
    DraftPickAutopickRequest,
    DraftPickOverrideRequest,
    DraftPickSelectRequest,
    DraftSessionCreateRequest,
    DraftSessionPatchRequest,
    DraftSessionRead,
    DraftSuggestion,
    DraftSuggestionsResponse,
    DraftSeedRequest,
)
from src.services.draft import board as board_svc
from src.services.draft import lifecycle, selection
from src.services.draft import export as export_svc
from src.services.draft import realtime as draft_rt
from src.services.draft import suggestions as sug

router = APIRouter(prefix="/draft", tags=["draft"])


async def get_redis() -> AsyncGenerator[Redis | None, None]:
    # A yield-dependency must yield EXACTLY once. Never yield inside an except:
    # FastAPI throws the endpoint's exception into the generator at the yield,
    # and a second yield raises "generator didn't stop after athrow()", masking
    # the real error. Redis.from_url builds the client without I/O, so guard it
    # before the try and yield None on its (rare) failure without re-yielding.
    try:
        client: Redis | None = Redis.from_url(config.redis_url, decode_responses=True)
    except Exception:  # noqa: BLE001 — realtime is best-effort; events persist regardless
        logger.warning("Draft realtime Redis unavailable; events persist but are not broadcast")
        yield None
        return
    try:
        yield client
    finally:
        await client.aclose()


async def _load_session(session: AsyncSession, session_id: int) -> DraftSession:
    draft = await session.get(DraftSession, session_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft session not found")
    return draft


async def _load_pick(session: AsyncSession, pick_id: int) -> tuple[DraftSession, DraftPick]:
    pick = await session.get(DraftPick, pick_id)
    if pick is None:
        raise HTTPException(status_code=404, detail="Draft pick not found")
    draft = await _load_session(session, pick.session_id)
    return draft, pick


def _pick_event_payload(draft: DraftSession, pick: DraftPick) -> dict:
    return {
        "session_id": draft.id,
        "pick_id": pick.id,
        "overall_pick_no": pick.overall_no,
        "draft_team_id": pick.draft_team_id,
        "picked_player_id": pick.picked_player_id,
        "status": pick.status,
        "current_pick_index": draft.current_pick_id,
    }


async def _publish_result(
    session: AsyncSession,
    redis: Redis | None,
    draft: DraftSession,
    result: selection.DraftResult,
    *,
    made_event: str,
    actor_user_id: int | None,
) -> None:
    await draft_rt.publish_draft_event(
        session,
        redis,
        draft_session=draft,
        event_type=made_event,
        payload=_pick_event_payload(draft, result.pick),
        actor_user_id=actor_user_id,
    )
    if result.completed:
        await draft_rt.publish_draft_event(
            session,
            redis,
            draft_session=draft,
            event_type="draft.completed",
            payload={"session_id": draft.id, "status": draft.status},
        )
    elif result.next_pick is not None:
        await draft_rt.publish_draft_event(
            session,
            redis,
            draft_session=draft,
            event_type="draft.pick_started",
            payload={
                "session_id": draft.id,
                "pick_id": result.next_pick.id,
                "overall_pick_no": result.next_pick.overall_no,
                "draft_team_id": result.next_pick.draft_team_id,
                "clock_expires_at": result.next_pick.clock_expires_at.isoformat()
                if result.next_pick.clock_expires_at
                else None,
            },
        )


# --------------------------------------------------------------------------- #
# Public reads
# --------------------------------------------------------------------------- #
@router.get("/tournaments/{tournament_id}/draft", response_model=DraftBoardSnapshot | None)
async def get_tournament_draft(
    tournament_id: int,
    session: AsyncSession = Depends(db.get_async_session),
) -> DraftBoardSnapshot | None:
    draft = await board_svc.get_active_session(session, tournament_id)
    if draft is None:
        return None
    return await board_svc.build_board(session, draft)


@router.get("/sessions/{session_id}", response_model=DraftSessionRead)
async def get_session(
    session_id: int,
    session: AsyncSession = Depends(db.get_async_session),
) -> DraftSessionRead:
    draft = await _load_session(session, session_id)
    return DraftSessionRead.model_validate(draft)


@router.get("/sessions/{session_id}/board", response_model=DraftBoardSnapshot)
async def get_session_board(
    session_id: int,
    session: AsyncSession = Depends(db.get_async_session),
) -> DraftBoardSnapshot:
    draft = await _load_session(session, session_id)
    return await board_svc.build_board(session, draft)


@router.get("/sessions/{session_id}/suggestions", response_model=DraftSuggestionsResponse)
async def get_suggestions(
    session_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    _: models.AuthUser = Depends(auth.require_draft_session_permission("team", "read")),
) -> DraftSuggestionsResponse:
    draft = await _load_session(session, session_id)
    if draft.current_pick_id is None:
        raise HTTPException(status_code=409, detail="Draft has no current pick")
    current = await session.get(DraftPick, draft.current_pick_id)
    available = (
        await session.scalars(
            sa.select(models.DraftPlayer).where(
                models.DraftPlayer.session_id == draft.id,
                models.DraftPlayer.status == "available",
            )
        )
    ).all()
    picked_count = await selection._team_picked_count(session, current.draft_team_id)
    capacity = selection._role_capacity(draft.team_size, picked_count)
    fit_players = [
        sug.FitPlayer(
            player_id=p.id,
            rank_value=p.rank_value or 0,
            playable_roles=frozenset(DraftRole(r) for r in {p.primary_role, *(p.secondary_roles_json or [])}),
            preference_order=(DraftRole(p.primary_role),),
            is_flex=p.is_flex,
            user_id=p.user_id,
        )
        for p in available
    ]
    ranked = sug.rank_suggestions(
        fit_players,
        capacity,
        sug.FitConfig(),
        strategy=DraftAutopickStrategy(draft.autopick_strategy),
        limit=5,
    )
    return DraftSuggestionsResponse(
        pick_id=current.id,
        draft_team_id=current.draft_team_id,
        suggestions=[
            DraftSuggestion(player_id=r.player_id, role=r.role, fit_score=r.fit_score, breakdown=r.breakdown)
            for r in ranked
        ],
    )


# --------------------------------------------------------------------------- #
# Admin lifecycle (keyed by tournament_id)
# --------------------------------------------------------------------------- #
@router.post("/tournaments/{tournament_id}/sessions", response_model=DraftSessionRead)
async def create_session_route(
    tournament_id: int,
    payload: DraftSessionCreateRequest,
    session: AsyncSession = Depends(db.get_async_session),
    redis: Redis | None = Depends(get_redis),
    user: models.AuthUser = Depends(auth.require_tournament_permission("team", "import")),
) -> DraftSessionRead:
    workspace_id = await auth._get_tournament_workspace_id(session, tournament_id)
    draft = await lifecycle.create_session(
        session,
        tournament_id=tournament_id,
        workspace_id=workspace_id,
        pool_source=payload.pool_source.value,
        source_balance_id=payload.source_balance_id,
        fmt=payload.format,
        rounds=payload.rounds,
        pick_time_seconds=payload.pick_time_seconds,
        team_size=payload.team_size,
        autopick_strategy=payload.autopick_strategy.value,
        allow_admin_override=payload.allow_admin_override,
        settings=payload.settings,
    )
    await draft_rt.publish_draft_event(
        session,
        redis,
        draft_session=draft,
        event_type="draft.session_updated",
        payload={"session_id": draft.id, "status": draft.status},
        actor_user_id=user.id,
    )
    await session.commit()
    return DraftSessionRead.model_validate(draft)


@router.post("/tournaments/{tournament_id}/sessions/{session_id}/seed", response_model=DraftSessionRead)
async def seed_route(
    tournament_id: int,
    session_id: int,
    payload: DraftSeedRequest,
    session: AsyncSession = Depends(db.get_async_session),
    redis: Redis | None = Depends(get_redis),
    user: models.AuthUser = Depends(auth.require_tournament_permission("team", "import")),
) -> DraftSessionRead:
    draft = await _load_session(session, session_id)
    if payload.pool_captains:
        # Pool-derived seeding: captains chosen from the existing balancer pool,
        # everyone else becomes available. No manual entry.
        await lifecycle.seed_from_pool(
            session,
            draft,
            captain_player_ids=[c.pool_player_id for c in payload.pool_captains],
            team_names={c.pool_player_id: c.name for c in payload.pool_captains if c.name},
        )
    elif payload.captains:
        captains = [
            lifecycle.CaptainSeed(
                name=c.name, draft_position=c.draft_position, user_id=c.user_id, battle_tag=c.battle_tag
            )
            for c in payload.captains
        ]
        players = [
            lifecycle.PlayerSeed(
                primary_role=p.primary_role,
                user_id=p.user_id,
                battle_tag=p.battle_tag,
                secondary_roles=p.secondary_roles,
                sub_role=p.sub_role,
                is_flex=p.is_flex,
                division_number=p.division_number,
                rank_value=p.rank_value,
            )
            for p in payload.players
        ]
        await lifecycle.seed(session, draft, captains=captains, players=players)
    else:
        raise HTTPException(
            status_code=422,
            detail="Provide pool_captains (from the balancer pool) or manual captains",
        )
    await draft_rt.publish_draft_event(
        session,
        redis,
        draft_session=draft,
        event_type="draft.session_updated",
        payload={"session_id": draft.id, "status": draft.status},
        actor_user_id=user.id,
    )
    await session.commit()
    return DraftSessionRead.model_validate(draft)


@router.patch("/tournaments/{tournament_id}/sessions/{session_id}", response_model=DraftSessionRead)
async def patch_session_route(
    tournament_id: int,
    session_id: int,
    payload: DraftSessionPatchRequest,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("team", "import")),
) -> DraftSessionRead:
    draft = await _load_session(session, session_id)
    if payload.pick_time_seconds is not None:
        draft.pick_time_seconds = payload.pick_time_seconds
    if payload.autopick_strategy is not None:
        draft.autopick_strategy = payload.autopick_strategy.value
    if payload.allow_admin_override is not None:
        draft.allow_admin_override = payload.allow_admin_override
    if payload.rounds is not None:
        draft.rounds = payload.rounds
    if payload.settings is not None:
        draft.settings_json = payload.settings
    await session.commit()
    await session.refresh(draft)
    return DraftSessionRead.model_validate(draft)


async def _lifecycle_action(session, redis, session_id, action, event_type, user):
    draft = await _load_session(session, session_id)
    await action(session, draft)
    extra: dict = {"session_id": draft.id, "status": draft.status}
    if event_type == "draft.pick_started" and draft.current_pick_id:
        current = await session.get(DraftPick, draft.current_pick_id)
        extra["pick_id"] = current.id
        extra["clock_expires_at"] = current.clock_expires_at.isoformat() if current.clock_expires_at else None
    await draft_rt.publish_draft_event(
        session, redis, draft_session=draft, event_type=event_type, payload=extra, actor_user_id=user.id
    )
    await session.commit()
    return DraftSessionRead.model_validate(draft)


@router.post("/tournaments/{tournament_id}/sessions/{session_id}/start", response_model=DraftSessionRead)
async def start_route(
    tournament_id: int,
    session_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    redis: Redis | None = Depends(get_redis),
    user: models.AuthUser = Depends(auth.require_tournament_permission("team", "import")),
) -> DraftSessionRead:
    return await _lifecycle_action(session, redis, session_id, lifecycle.start, "draft.pick_started", user)


@router.post("/tournaments/{tournament_id}/sessions/{session_id}/pause", response_model=DraftSessionRead)
async def pause_route(
    tournament_id: int,
    session_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    redis: Redis | None = Depends(get_redis),
    user: models.AuthUser = Depends(auth.require_tournament_permission("team", "import")),
) -> DraftSessionRead:
    return await _lifecycle_action(session, redis, session_id, lifecycle.pause, "draft.paused", user)


@router.post("/tournaments/{tournament_id}/sessions/{session_id}/resume", response_model=DraftSessionRead)
async def resume_route(
    tournament_id: int,
    session_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    redis: Redis | None = Depends(get_redis),
    user: models.AuthUser = Depends(auth.require_tournament_permission("team", "import")),
) -> DraftSessionRead:
    return await _lifecycle_action(session, redis, session_id, lifecycle.resume, "draft.resumed", user)


@router.post("/tournaments/{tournament_id}/sessions/{session_id}/cancel", response_model=DraftSessionRead)
async def cancel_route(
    tournament_id: int,
    session_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    redis: Redis | None = Depends(get_redis),
    user: models.AuthUser = Depends(auth.require_tournament_permission("team", "import")),
) -> DraftSessionRead:
    return await _lifecycle_action(session, redis, session_id, lifecycle.cancel, "draft.cancelled", user)


@router.post("/tournaments/{tournament_id}/sessions/{session_id}/export", response_model=DraftSessionRead)
async def export_route(
    tournament_id: int,
    session_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    redis: Redis | None = Depends(get_redis),
    user: models.AuthUser = Depends(auth.require_tournament_permission("team", "import")),
) -> DraftSessionRead:
    draft = await _load_session(session, session_id)
    updated, _removed, _imported = await export_svc.export(session, draft)
    await draft_rt.publish_draft_event(
        session,
        redis,
        draft_session=updated,
        event_type="draft.completed",
        payload={"session_id": updated.id, "status": updated.status, "export_status": updated.export_status},
        actor_user_id=user.id,
    )
    await session.commit()
    return DraftSessionRead.model_validate(updated)


# --------------------------------------------------------------------------- #
# Pick actions (keyed by pick_id)
# --------------------------------------------------------------------------- #
@router.post("/picks/{pick_id}/select", response_model=DraftSessionRead)
async def select_route(
    pick_id: int,
    payload: DraftPickSelectRequest,
    session: AsyncSession = Depends(db.get_async_session),
    redis: Redis | None = Depends(get_redis),
    user: models.AuthUser = Depends(auth.require_pick_permission("team", "import")),
) -> DraftSessionRead:
    draft, pick = await _load_pick(session, pick_id)
    public_user_id = await session.scalar(
        sa.select(models.AuthUserPlayer.player_id).where(models.AuthUserPlayer.auth_user_id == user.id)
    )
    is_admin = user.is_workspace_admin(draft.workspace_id)
    try:
        result = await selection.select(
            session,
            draft,
            pick,
            player_id=payload.player_id,
            expected_version=payload.expected_version,
            target_role=payload.target_role,
            actor_user_id=public_user_id,
            is_admin=is_admin,
        )
    except ApiHTTPException:
        raise
    await _publish_result(session, redis, draft, result, made_event="draft.pick_made", actor_user_id=public_user_id)
    await session.commit()
    return DraftSessionRead.model_validate(draft)


@router.post("/picks/{pick_id}/autopick", response_model=DraftSessionRead)
async def autopick_route(
    pick_id: int,
    payload: DraftPickAutopickRequest,
    session: AsyncSession = Depends(db.get_async_session),
    redis: Redis | None = Depends(get_redis),
    user: models.AuthUser = Depends(auth.require_pick_permission("team", "import")),
) -> DraftSessionRead:
    draft, pick = await _load_pick(session, pick_id)
    result = await selection.autopick(session, draft, pick, expected_version=payload.expected_version)
    await _publish_result(session, redis, draft, result, made_event="draft.autopicked", actor_user_id=None)
    await session.commit()
    return DraftSessionRead.model_validate(draft)


@router.post("/picks/{pick_id}/override", response_model=DraftSessionRead)
async def override_route(
    pick_id: int,
    payload: DraftPickOverrideRequest,
    session: AsyncSession = Depends(db.get_async_session),
    redis: Redis | None = Depends(get_redis),
    user: models.AuthUser = Depends(auth.require_pick_permission("team", "import")),
) -> DraftSessionRead:
    draft, pick = await _load_pick(session, pick_id)
    public_user_id = await session.scalar(
        sa.select(models.AuthUserPlayer.player_id).where(models.AuthUserPlayer.auth_user_id == user.id)
    )
    result = await selection.override(
        session,
        draft,
        pick,
        player_id=payload.player_id,
        expected_version=payload.expected_version,
        actor_user_id=public_user_id,
    )
    await _publish_result(session, redis, draft, result, made_event="draft.pick_made", actor_user_id=public_user_id)
    await session.commit()
    return DraftSessionRead.model_validate(draft)
