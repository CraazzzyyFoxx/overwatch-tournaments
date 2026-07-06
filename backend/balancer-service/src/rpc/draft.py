"""Live Draft endpoints over typed RPC (rpc.balancer.draft.*).

Ports ``src/routes/admin/draft.py``: public reads (no auth) for spectating, admin
lifecycle keyed by tournament_id, pick actions keyed by pick_id. Every mutation
commits then publishes a realtime event on ``tournament:{id}:draft`` (persisted
within the transaction so the WorkspaceEvent id orders with the pick). The draft
router has no admin-panel gate, so handlers enforce only the per-endpoint
permission (or just the active user, for /select).

The orchestration mirrors the HTTP routes; the underlying draft services are
reused unchanged. A single worker-lifetime Redis client backs the realtime
publish (publish failures are swallowed by publish_event).
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from faststream.rabbit import RabbitMessage
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import DraftAutopickStrategy, DraftRole
from shared.core.errors import BaseAPIException as HTTPException
from shared.models.balancer.draft import DraftPick, DraftSession
from src import models
from src.core import db
from src.core.auth import (
    _get_draft_session_workspace_id,
    _get_pick_workspace_id,
    _get_tournament_workspace_id,
)
from src.core.config import config
from src.rpc import _common as c
from src.schemas.draft import (
    DraftPickAutopickRequest,
    DraftPickOverrideRequest,
    DraftPickSelectRequest,
    DraftSeedRequest,
    DraftSessionCreateRequest,
    DraftSessionPatchRequest,
    DraftSessionRead,
    DraftSuggestion,
    DraftSuggestionsResponse,
)
from src.services.draft import board as board_svc
from src.services.draft import export as export_svc
from src.services.draft import lifecycle, loaders, selection
from src.services.draft import realtime as draft_rt
from src.services.draft import suggestions as sug

_SF = db.async_session_maker

# A single worker-lifetime client (asyncio redis is safe for concurrent use via
# its pool). publish_event swallows publish failures, so realtime is best-effort.
_redis_client: Redis | None = None


def _redis(logger: Any) -> Redis | None:
    global _redis_client
    if _redis_client is None:
        try:
            _redis_client = Redis.from_url(config.redis_url, decode_responses=True)
        except Exception:  # noqa: BLE001 — realtime is best-effort; events persist regardless
            logger.warning("Draft realtime Redis unavailable; events persist but are not broadcast")
            return None
    return _redis_client


async def close() -> None:
    """Close the worker-lifetime realtime Redis client (called on worker shutdown)."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None


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


async def _lifecycle_action(session, redis, session_id, action, event_type, user) -> DraftSessionRead:
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


def register(broker: Any, logger: Any) -> None:
    # --- public reads -------------------------------------------------------
    @broker.subscriber("rpc.balancer.draft.tournament_board")
    async def _tournament_board(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            tournament_id = c.require_id(data)
            draft = await board_svc.get_active_session(session, tournament_id)
            if draft is None:
                return None
            return await board_svc.build_board(session, draft)

        return await c.envelope(logger, "draft.tournament_board", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.session_get")
    async def _session_get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            draft = await _load_session(session, c.require_id(data))
            return DraftSessionRead.model_validate(draft)

        return await c.envelope(logger, "draft.session_get", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.session_board")
    async def _session_board(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            draft = await _load_session(session, c.require_id(data))
            return await board_svc.build_board(session, draft)

        return await c.envelope(logger, "draft.session_board", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.suggestions")
    async def _suggestions(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            session_id = c.require_id(data)
            ws_id = await _get_draft_session_workspace_id(session, session_id)
            c.require_workspace_permission(data, user, ws_id, "team", "read")
            draft = await _load_session(session, session_id)
            if draft.current_pick_id is None:
                raise HTTPException(status_code=409, detail="Draft has no current pick")
            current = await session.get(DraftPick, draft.current_pick_id)
            available = (
                await session.scalars(
                    sa.select(models.DraftPlayer)
                    .where(
                        models.DraftPlayer.session_id == draft.id,
                        models.DraftPlayer.status == "available",
                    )
                    # Fit construction reads secondary_roles_json/user_id/role_ranks.
                    .options(*loaders.player_options())
                )
            ).all()
            counts = await selection._team_role_counts(session, current.draft_team_id)
            capacity = selection._role_capacity(draft.team_size, counts)
            fit_players = [
                sug.FitPlayer(
                    player_id=p.id,
                    rank_value=p.rank_value or 0,
                    playable_roles=frozenset(DraftRole(r) for r in {p.primary_role, *(p.secondary_roles_json or [])}),
                    preference_order=(DraftRole(p.primary_role),),
                    is_flex=p.is_flex,
                    user_id=p.user_id,
                    rank_by_role={DraftRole(k): v for k, v in (p.role_ranks or {}).items()},
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

        return await c.envelope(logger, "draft.suggestions", op, session_factory=_SF)

    # --- admin lifecycle (keyed by tournament_id) ---------------------------
    @broker.subscriber("rpc.balancer.draft.session_create")
    async def _session_create(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            tournament_id = c.require_id(data)
            workspace_id = await _get_tournament_workspace_id(session, tournament_id)
            c.require_workspace_permission(data, user, workspace_id, "team", "import")
            payload = DraftSessionCreateRequest.model_validate(c.payload(data))
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
                _redis(logger),
                draft_session=draft,
                event_type="draft.session_updated",
                payload={"session_id": draft.id, "status": draft.status},
                actor_user_id=user.id,
            )
            await session.commit()
            return DraftSessionRead.model_validate(draft)

        return await c.envelope(logger, "draft.session_create", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.seed")
    async def _seed(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            session_id = c.require_id(data)
            tournament_id = c.path_int(data, "tournament_id")
            ws_id = await _get_tournament_workspace_id(session, tournament_id)
            c.require_workspace_permission(data, user, ws_id, "team", "import")
            payload = DraftSeedRequest.model_validate(c.payload(data))
            draft = await _load_session(session, session_id)
            if payload.pool_captains:
                await lifecycle.seed_from_pool(
                    session,
                    draft,
                    captain_registration_ids=[c_.registration_id for c_ in payload.pool_captains],
                    team_names={c_.registration_id: c_.name for c_ in payload.pool_captains if c_.name},
                    captain_order=payload.captain_order,
                    rng_seed=payload.seed,
                )
            elif payload.captains:
                captains = [
                    lifecycle.CaptainSeed(
                        name=cap.name, draft_position=cap.draft_position, user_id=cap.user_id, battle_tag=cap.battle_tag
                    )
                    for cap in payload.captains
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
                        role_ranks=({p.primary_role.value: p.rank_value} if p.rank_value is not None else {}),
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
                _redis(logger),
                draft_session=draft,
                event_type="draft.session_updated",
                payload={"session_id": draft.id, "status": draft.status},
                actor_user_id=user.id,
            )
            await session.commit()
            return DraftSessionRead.model_validate(draft)

        return await c.envelope(logger, "draft.seed", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.session_patch")
    async def _session_patch(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            session_id = c.require_id(data)
            tournament_id = c.path_int(data, "tournament_id")
            ws_id = await _get_tournament_workspace_id(session, tournament_id)
            c.require_workspace_permission(data, user, ws_id, "team", "import")
            payload = DraftSessionPatchRequest.model_validate(c.payload(data))
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

        return await c.envelope(logger, "draft.session_patch", op, session_factory=_SF)

    def _make_lifecycle(subject: str, action, event_type: str) -> None:
        @broker.subscriber(subject)
        async def _handler(data: dict, msg: RabbitMessage) -> dict:
            async def op(session: Any) -> Any:
                user = c.active_actor(data)
                session_id = c.require_id(data)
                tournament_id = c.path_int(data, "tournament_id")
                ws_id = await _get_tournament_workspace_id(session, tournament_id)
                c.require_workspace_permission(data, user, ws_id, "team", "import")
                return await _lifecycle_action(session, _redis(logger), session_id, action, event_type, user)

            return await c.envelope(logger, subject, op, session_factory=_SF)

    _make_lifecycle("rpc.balancer.draft.start", lifecycle.start, "draft.pick_started")
    _make_lifecycle("rpc.balancer.draft.pause", lifecycle.pause, "draft.paused")
    _make_lifecycle("rpc.balancer.draft.resume", lifecycle.resume, "draft.resumed")
    _make_lifecycle("rpc.balancer.draft.cancel", lifecycle.cancel, "draft.cancelled")
    _make_lifecycle("rpc.balancer.draft.rollback", lifecycle.rollback, "draft.rollback")

    @broker.subscriber("rpc.balancer.draft.export")
    async def _export(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            session_id = c.require_id(data)
            tournament_id = c.path_int(data, "tournament_id")
            ws_id = await _get_tournament_workspace_id(session, tournament_id)
            c.require_workspace_permission(data, user, ws_id, "team", "import")
            draft = await _load_session(session, session_id)
            updated, _removed, _imported = await export_svc.export(session, draft)
            await draft_rt.publish_draft_event(
                session,
                _redis(logger),
                draft_session=updated,
                event_type="draft.completed",
                payload={"session_id": updated.id, "status": updated.status, "export_status": updated.export_status},
                actor_user_id=user.id,
            )
            await session.commit()
            return DraftSessionRead.model_validate(updated)

        return await c.envelope(logger, "draft.export", op, session_factory=_SF)

    # --- pick actions (keyed by pick_id) ------------------------------------
    @broker.subscriber("rpc.balancer.draft.pick_select")
    async def _pick_select(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            pick_id = c.require_id(data)
            payload = DraftPickSelectRequest.model_validate(c.payload(data))
            draft, pick = await _load_pick(session, pick_id)
            public_user_ids = list(
                await session.scalars(sa.select(models.User.id).where(models.User.auth_user_id == user.id))
            )
            public_user_id = public_user_ids[0] if public_user_ids else None
            is_admin = user.is_workspace_admin(draft.workspace_id)
            result = await selection.select(
                session,
                draft,
                pick,
                player_id=payload.player_id,
                expected_version=payload.expected_version,
                target_role=payload.target_role,
                actor_user_id=public_user_id,
                actor_auth_user_id=user.id,
                actor_player_ids=public_user_ids,
                is_admin=is_admin,
            )
            await _publish_result(
                session, _redis(logger), draft, result, made_event="draft.pick_made", actor_user_id=public_user_id
            )
            await session.commit()
            return DraftSessionRead.model_validate(draft)

        return await c.envelope(logger, "draft.pick_select", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.pick_autopick")
    async def _pick_autopick(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            pick_id = c.require_id(data)
            ws_id = await _get_pick_workspace_id(session, pick_id)
            c.require_workspace_permission(data, user, ws_id, "team", "import")
            payload = DraftPickAutopickRequest.model_validate(c.payload(data))
            draft, pick = await _load_pick(session, pick_id)
            result = await selection.autopick(session, draft, pick, expected_version=payload.expected_version)
            await _publish_result(
                session, _redis(logger), draft, result, made_event="draft.autopicked", actor_user_id=None
            )
            await session.commit()
            return DraftSessionRead.model_validate(draft)

        return await c.envelope(logger, "draft.pick_autopick", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.pick_override")
    async def _pick_override(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            pick_id = c.require_id(data)
            ws_id = await _get_pick_workspace_id(session, pick_id)
            c.require_workspace_permission(data, user, ws_id, "team", "import")
            payload = DraftPickOverrideRequest.model_validate(c.payload(data))
            draft, pick = await _load_pick(session, pick_id)
            public_user_id = await session.scalar(sa.select(models.User.id).where(models.User.auth_user_id == user.id))
            result = await selection.override(
                session,
                draft,
                pick,
                player_id=payload.player_id,
                expected_version=payload.expected_version,
                actor_user_id=public_user_id,
                target_role=payload.target_role,
            )
            await _publish_result(
                session, _redis(logger), draft, result, made_event="draft.pick_made", actor_user_id=public_user_id
            )
            await session.commit()
            return DraftSessionRead.model_validate(draft)

        return await c.envelope(logger, "draft.pick_override", op, session_factory=_SF)
