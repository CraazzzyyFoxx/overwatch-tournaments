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
from shared.models.balancer.draft import DraftAuditEvent, DraftPick, DraftSession, DraftTeam
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
    DraftFeasibilityResponse,
    DraftPickAutopickRequest,
    DraftPickOptionRead,
    DraftPickOptionsResponse,
    DraftPickOverrideRequest,
    DraftPickSelectRequest,
    DraftRoleEditRequest,
    DraftRoleEditResponse,
    DraftSeedDiff,
    DraftSeedRequest,
    DraftSeedResponse,
    DraftSessionCreateRequest,
    DraftSessionPatchRequest,
    DraftSessionRead,
    DraftSuggestion,
    DraftSuggestionsResponse,
)
from src.services.draft import board as board_svc
from src.services.draft import export as export_svc
from src.services.draft import feasibility, lifecycle, loaders, selection
from src.services.draft import realtime as draft_rt
from src.services.draft import role_edit as role_edit_svc
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


async def _seed_counts(session: AsyncSession, session_id: int) -> tuple[int, int, int]:
    counts = []
    for model in (models.DraftTeam, models.DraftPlayer, models.DraftPick):
        counts.append(
            int(
                await session.scalar(
                    sa.select(sa.func.count()).select_from(model).where(model.session_id == session_id)
                )
                or 0
            )
        )
    return counts[0], counts[1], counts[2]


def _pick_event_payload(draft: DraftSession, pick: DraftPick) -> dict:
    return {
        "session_id": draft.id,
        "pick_id": pick.id,
        "overall_pick_no": pick.overall_no,
        "draft_team_id": pick.draft_team_id,
        "picked_player_id": pick.picked_player_id,
        "target_role": pick.target_role,
        "target_rank_value": pick.target_rank_value,
        "pick_version": pick.version,
        "status": pick.status,
        "current_pick_index": draft.current_pick_id,
    }


def _override_audit_event(
    *,
    session_id: int,
    pick_id: int,
    actor_auth_user_id: int,
    reason: str | None,
    before: dict[str, Any],
    after: dict[str, Any],
) -> DraftAuditEvent:
    return DraftAuditEvent(
        session_id=session_id,
        actor_auth_user_id=actor_auth_user_id,
        action="pick_overridden",
        entity_type="draft_pick",
        entity_id=pick_id,
        reason=(reason or "").strip() or "Admin override",
        before_json=before,
        after_json=after,
    )


def _player_updated_payload(
    *,
    session_id: int,
    player_id: int,
    role: DraftRole,
    player_version: int,
    is_feasible: bool,
) -> dict:
    return {
        "session_id": session_id,
        "player_id": player_id,
        "role": role.value,
        "player_version": player_version,
        "is_feasible": is_feasible,
    }


def _seed_diff(
    *,
    before: tuple[int, int, int],
    after: tuple[int, int, int],
    version_before: int,
    version_after: int,
) -> DraftSeedDiff:
    return DraftSeedDiff(
        teams_before=before[0],
        teams_after=after[0],
        players_before=before[1],
        players_after=after[1],
        picks_before=before[2],
        picks_after=after[2],
        session_version_before=version_before,
        session_version_after=version_after,
    )


async def _publish_result(
    session: AsyncSession,
    redis: Redis | None,
    draft: DraftSession,
    result: selection.DraftResult,
    *,
    made_event: str,
    actor_user_id: int | None,
) -> None:
    if result.blocked_reason:
        await draft_rt.publish_draft_event(
            session,
            redis,
            draft_session=draft,
            event_type="draft.blocked",
            payload={
                "session_id": draft.id,
                "pick_id": result.pick.id,
                "draft_team_id": result.pick.draft_team_id,
                "reason": result.blocked_reason,
            },
            actor_user_id=actor_user_id,
        )
        return
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

    @broker.subscriber("rpc.balancer.draft.feasibility")
    async def _feasibility(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            session_id = c.require_id(data)
            ws_id = await _get_draft_session_workspace_id(session, session_id)
            c.require_workspace_permission(data, user, ws_id, "team", "import")
            draft = await _load_session(session, session_id)
            report = await feasibility.analyze_session(session, draft)
            return DraftFeasibilityResponse.model_validate(report)

        return await c.envelope(logger, "draft.feasibility", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.pick_options")
    async def _pick_options(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            draft, pick = await _load_pick(session, c.require_id(data))
            if draft.current_pick_id != pick.id:
                raise HTTPException(status_code=409, detail="Options are available only for the current pick")
            public_user_ids = list(
                await session.scalars(sa.select(models.User.id).where(models.User.auth_user_id == user.id))
            )
            team = await session.get(
                DraftTeam,
                pick.draft_team_id,
                options=loaders.team_options(),
                populate_existing=True,
            )
            if not user.is_workspace_admin(draft.workspace_id) and not selection._is_on_clock_captain(
                team,
                actor_auth_user_id=user.id,
                actor_player_ids=public_user_ids,
            ):
                raise HTTPException(status_code=403, detail="Only the on-clock captain or an admin may read options")
            options = await feasibility.evaluate_session_pick_options(
                session,
                draft,
                team_id=pick.draft_team_id,
            )
            return DraftPickOptionsResponse(
                pick_id=pick.id,
                pick_version=pick.version,
                draft_team_id=pick.draft_team_id,
                options=[DraftPickOptionRead.model_validate(option) for option in options],
            )

        return await c.envelope(logger, "draft.pick_options", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.player_role_edit")
    async def _player_role_edit(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            player_id = c.require_id(data)
            session_id = c.path_int(data, "session_id")
            ws_id = await _get_draft_session_workspace_id(session, session_id)
            c.require_workspace_permission(data, user, ws_id, "team", "import")
            payload = DraftRoleEditRequest.model_validate(c.payload(data))
            draft = await _load_session(session, session_id)
            result = await role_edit_svc.edit_player_role(
                session,
                draft,
                player_id=player_id,
                role=payload.role,
                rank_value=payload.rank_value,
                rank_absence_confirmed=payload.rank_absence_confirmed,
                reason=payload.reason,
                expected_version=payload.expected_version,
                actor_auth_user_id=user.id,
                preview_only=payload.preview_only,
            )
            response = DraftRoleEditResponse(
                player_id=result.player_id,
                role=result.role,
                player_version=result.player_version,
                committed=result.committed,
                before=DraftFeasibilityResponse.model_validate(result.preview.before),
                after=DraftFeasibilityResponse.model_validate(result.preview.after),
            )
            if result.committed:
                await draft_rt.publish_draft_event(
                    session,
                    _redis(logger),
                    draft_session=draft,
                    event_type="draft.player_updated",
                    payload=_player_updated_payload(
                        session_id=draft.id,
                        player_id=result.player_id,
                        role=result.role,
                        player_version=result.player_version,
                        is_feasible=result.preview.after.is_feasible,
                    ),
                )
                await session.commit()
            return response

        return await c.envelope(logger, "draft.player_role_edit", op, session_factory=_SF)

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
                    playable_roles=(
                        frozenset(DraftRole)
                        if p.is_flex
                        else frozenset(DraftRole(r) for r in {p.primary_role, *(p.secondary_roles_json or [])})
                    ),
                    preference_order=(DraftRole(p.primary_role),),
                    is_flex=p.is_flex,
                    user_id=p.user_id,
                    rank_by_role={DraftRole(k): v for k, v in (p.role_ranks or {}).items()},
                )
                for p in available
            ]
            options = await feasibility.evaluate_session_pick_options(
                session,
                draft,
                team_id=current.draft_team_id,
            )
            safe_options = {(option.player_id, option.role) for option in options if option.is_safe}
            ranked = sug.rank_suggestions(
                fit_players,
                capacity,
                sug.FitConfig(),
                strategy=DraftAutopickStrategy(draft.autopick_strategy),
                limit=5,
                allowed_options=safe_options,
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
            draft = await session.scalar(
                sa.select(DraftSession).where(DraftSession.id == session_id).with_for_update()
            )
            if draft is None:
                raise HTTPException(status_code=404, detail="Draft session not found")
            lifecycle.validate_seed_version(draft, expected_version=payload.expected_version)
            before = await _seed_counts(session, draft.id)
            version_before = draft.version
            savepoint = await session.begin_nested() if payload.preview_only else None
            try:
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
                            name=cap.name,
                            draft_position=cap.draft_position,
                            user_id=cap.user_id,
                            battle_tag=cap.battle_tag,
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

                after = await _seed_counts(session, draft.id)
                report = await feasibility.analyze_session(session, draft)
                response = DraftSeedResponse(
                    session=DraftSessionRead.model_validate(draft),
                    preview_only=payload.preview_only,
                    diff=_seed_diff(
                        before=before,
                        after=after,
                        version_before=version_before,
                        version_after=draft.version,
                    ),
                    feasibility=DraftFeasibilityResponse.model_validate(report),
                )
                if savepoint is not None:
                    await savepoint.rollback()
                    return response

                await draft_rt.publish_draft_event(
                    session,
                    _redis(logger),
                    draft_session=draft,
                    event_type="draft.session_updated",
                    payload={"session_id": draft.id, "status": draft.status},
                    actor_user_id=user.id,
                )
                await session.commit()
                return response
            except Exception:
                if savepoint is not None and savepoint.is_active:
                    await savepoint.rollback()
                raise

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
                lifecycle.validate_roster_shape(rounds=payload.rounds, team_size=draft.team_size)
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
            before = {
                "player_id": pick.picked_player_id,
                "team_id": pick.draft_team_id,
                "role": pick.target_role,
                "rank_value": pick.target_rank_value,
                "version": pick.version,
            }
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
            session.add(
                _override_audit_event(
                    session_id=draft.id,
                    pick_id=pick.id,
                    actor_auth_user_id=user.id,
                    reason=payload.note,
                    before=before,
                    after={
                        "player_id": pick.picked_player_id,
                        "team_id": pick.draft_team_id,
                        "role": pick.target_role,
                        "rank_value": pick.target_rank_value,
                        "version": pick.version,
                    },
                )
            )
            await _publish_result(
                session, _redis(logger), draft, result, made_event="draft.pick_made", actor_user_id=public_user_id
            )
            await session.commit()
            return DraftSessionRead.model_validate(draft)

        return await c.envelope(logger, "draft.pick_override", op, session_factory=_SF)
