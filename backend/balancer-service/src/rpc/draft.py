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

Zero SQL lives in this module: every handler decodes, gates, and calls exactly
one draft-package service singleton. All DB access goes through
``shared.repository.draft``'s repositories (see the service modules for how).
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit import RabbitMessage
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import DraftStatus, HeroClass
from shared.core.errors import BaseAPIException as HTTPException
from shared.models.balancer.draft import DraftAuditEvent, DraftPick, DraftSession
from shared.repository.draft import (
    DraftAuditEventRepository,
    DraftPickRepository,
    DraftSessionRepository,
)
from shared.repository.identity import UserRepository
from shared.services.realtime import Scope, emit, enqueue_invalidation_outbox
from shared.services.roster_shape_access import get_effective_roster_shape
from src import schemas
from src.core import db
from src.core.auth import (
    _get_draft_session_workspace_id,
    _get_pick_workspace_id,
    _get_tournament_workspace_id,
)
from src.core.config import config
from src.domain.draft import rules
from src.domain.draft.entities import DraftResult
from src.rpc import _common as c
from src.services.balancer.realtime import EXPORT_RESOURCES
from src.services.draft import clock as clock_svc
from src.services.draft import realtime as draft_rt
from src.services.draft.board import board_service
from src.services.draft.export import export_service
from src.services.draft.feasibility import feasibility_service
from src.services.draft.lifecycle import lifecycle_service
from src.services.draft.role_edit import role_edit_service
from src.services.draft.selection import selection_service

_SF = db.async_session_maker

_sessions_repo = DraftSessionRepository()
_picks_repo = DraftPickRepository()
_audit_repo = DraftAuditEventRepository()
_users_repo = UserRepository()

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
    draft = await _sessions_repo.get(session, session_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft session not found")
    return draft


async def _load_pick(session: AsyncSession, pick_id: int) -> tuple[DraftSession, DraftPick]:
    pick = await _picks_repo.get(session, pick_id)
    if pick is None:
        raise HTTPException(status_code=404, detail="Draft pick not found")
    draft = await _load_session(session, pick.session_id)
    return draft, pick


async def _actor_player_ids(session: AsyncSession, auth_user_id: int) -> list[int]:
    """Domain player ids for an acting auth user.

    The single-link model (``players.user.auth_user_id`` is a unique FK) means
    this is always 0 or 1 ids; kept as a list because callers pass it straight
    into ``_is_on_clock_captain``'s ``actor_player_ids`` collection.
    """
    player_id = await _users_repo.get_id_by_auth_user_id(session, auth_user_id)
    return [player_id] if player_id is not None else []


def _to_role(slot_code: str | None) -> HeroClass | None:
    """Wire slot code -> the domain's ``HeroClass``.

    Requests carry ``tank``/``dps``/``support``; everything below this layer —
    ``rules.resolve_pick_slot``, ``role_edit_service``, ``fit`` — takes a
    ``HeroClass``. Handing the raw string down reached ``role.slot_code`` on a
    ``str`` and 500'd the pick instead of drafting anyone.
    """
    return HeroClass.from_slot_code(slot_code) if slot_code is not None else None


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
    role: HeroClass,
    player_version: int,
    is_feasible: bool,
) -> dict:
    return {
        "session_id": session_id,
        "player_id": player_id,
        "role": role.slot_code,
        "player_version": player_version,
        "is_feasible": is_feasible,
    }


def _seed_diff(
    *,
    before: tuple[int, int, int],
    after: tuple[int, int, int],
    version_before: int,
    version_after: int,
) -> schemas.DraftSeedDiff:
    return schemas.DraftSeedDiff(
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
    draft: DraftSession,
    result: DraftResult,
    *,
    made_event: str,
    actor_user_id: int | None,
) -> None:
    if result.blocked_reason and result.next_pick is None:
        # Nothing was picked (role shortage) — the block is the whole story.
        await draft_rt.publish_draft_event(
            session,
            draft_session=draft,
            event_type="draft.blocked",
            payload={
                "session_id": draft.id,
                "pick_id": result.pick.id,
                "draft_team_id": result.pick.draft_team_id,
                # `blocked_reason`, never `reason`: the vocabulary has exactly
                # one meaning per field, and this one is the business cause.
                "blocked_reason": result.blocked_reason,
            },
            actor_user_id=actor_user_id,
        )
        return
    await draft_rt.publish_draft_event(
        session,
        draft_session=draft,
        event_type=made_event,
        payload=_pick_event_payload(draft, result.pick),
        actor_user_id=actor_user_id,
    )
    if result.completed:
        await draft_rt.publish_draft_event(
            session,
            draft_session=draft,
            event_type="draft.completed",
            payload={"session_id": draft.id, "status": draft.status},
        )
    elif result.blocked_reason and result.next_pick is not None:
        # The pick landed, but the next round re-seated the teams and the draft
        # is paused: no pick_started, it would flip clients back to live.
        await draft_rt.publish_draft_event(
            session,
            draft_session=draft,
            event_type="draft.blocked",
            payload={
                "session_id": draft.id,
                "pick_id": result.next_pick.id,
                "draft_team_id": result.next_pick.draft_team_id,
                "blocked_reason": result.blocked_reason,
            },
            actor_user_id=actor_user_id,
        )
    elif result.next_pick is not None:
        await draft_rt.publish_draft_event(
            session,
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


async def _lifecycle_action(
    session, redis, session_id, action, event_type, user, **action_kwargs
) -> schemas.DraftSessionRead:
    draft = await _load_session(session, session_id)
    await action(session, draft, **action_kwargs)
    extra: dict = {"session_id": draft.id, "status": draft.status}
    if event_type == "draft.pick_started" and draft.current_pick_id:
        current = await _picks_repo.get(session, draft.current_pick_id)
        extra["pick_id"] = current.id
        extra["clock_expires_at"] = current.clock_expires_at.isoformat() if current.clock_expires_at else None
    await draft_rt.publish_draft_event(
        session, draft_session=draft, event_type=event_type, payload=extra, actor_user_id=user.id
    )
    await session.commit()
    if draft.status == DraftStatus.LIVE.value:
        # Wake the supervisor so a freshly started/resumed draft gets its
        # autopick clock loop immediately (the idle discovery poll is relaxed).
        await clock_svc.notify_supervisor(redis)
    return await board_service.session_read(session, draft)


def register(broker: Any, logger: Any) -> None:
    # --- public reads -------------------------------------------------------
    @broker.subscriber("rpc.balancer.draft.tournament_board")
    async def _tournament_board(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            tournament_id = c.require_id(data)
            draft = await board_service.get_active_session(session, tournament_id)
            if draft is None:
                return None
            return await board_service.build_board(session, draft)

        return await c.envelope(logger, "draft.tournament_board", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.session_get")
    async def _session_get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            draft = await _load_session(session, c.require_id(data))
            return await board_service.session_read(session, draft)

        return await c.envelope(logger, "draft.session_get", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.session_board")
    async def _session_board(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            draft = await _load_session(session, c.require_id(data))
            return await board_service.build_board(session, draft)

        return await c.envelope(logger, "draft.session_board", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.feasibility")
    async def _feasibility(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            session_id = c.require_id(data)
            ws_id = await _get_draft_session_workspace_id(session, session_id)
            c.require_workspace_permission(data, user, ws_id, "team", "create")
            draft = await _load_session(session, session_id)
            report = await feasibility_service.analyze_session(session, draft)
            return schemas.DraftFeasibilityResponse.model_validate(report)

        return await c.envelope(logger, "draft.feasibility", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.pick_options")
    async def _pick_options(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            draft, pick = await _load_pick(session, c.require_id(data))
            public_user_ids = await _actor_player_ids(session, user.id)
            options = await feasibility_service.options_for_current_pick(
                session,
                draft,
                pick,
                actor_auth_user_id=user.id,
                actor_player_ids=public_user_ids,
                is_workspace_admin=user.is_workspace_admin(draft.workspace_id),
            )
            return schemas.DraftPickOptionsResponse(
                pick_id=pick.id,
                pick_version=pick.version,
                draft_team_id=pick.draft_team_id,
                options=[schemas.DraftPickOptionRead.model_validate(option) for option in options],
            )

        return await c.envelope(logger, "draft.pick_options", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.player_role_edit")
    async def _player_role_edit(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            player_id = c.require_id(data)
            session_id = c.path_int(data, "session_id")
            ws_id = await _get_draft_session_workspace_id(session, session_id)
            c.require_workspace_permission(data, user, ws_id, "team", "create")
            payload = schemas.DraftRoleEditRequest.model_validate(c.payload(data))
            draft = await _load_session(session, session_id)
            result = await role_edit_service.edit_player_role(
                session,
                draft,
                player_id=player_id,
                role=HeroClass.from_slot_code(payload.role),
                rank_value=payload.rank_value,
                reason=payload.reason,
                expected_version=payload.expected_version,
                actor_auth_user_id=user.id,
                preview_only=payload.preview_only,
            )
            response = schemas.DraftRoleEditResponse(
                player_id=result.player_id,
                role=result.role,
                player_version=result.player_version,
                committed=result.committed,
                before=schemas.DraftFeasibilityResponse.model_validate(result.preview.before),
                after=schemas.DraftFeasibilityResponse.model_validate(result.preview.after),
            )
            if result.committed:
                await draft_rt.publish_draft_event(
                    session,
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
            current, ranked = await feasibility_service.rank_current_suggestions(session, draft)
            return schemas.DraftSuggestionsResponse(
                pick_id=current.id,
                draft_team_id=current.draft_team_id,
                suggestions=[
                    schemas.DraftSuggestion(
                        player_id=r.player_id, role=r.role, fit_score=r.fit_score, breakdown=r.breakdown
                    )
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
            c.require_workspace_permission(data, user, workspace_id, "team", "create")
            payload = schemas.DraftSessionCreateRequest.model_validate(c.payload(data))
            # The roster shape is the tournament's, not the request's: a draft
            # cannot be created at a size the tournament does not run.
            shape = await get_effective_roster_shape(session, tournament_id=tournament_id, workspace_id=workspace_id)
            draft = await lifecycle_service.create_session(
                session,
                tournament_id=tournament_id,
                workspace_id=workspace_id,
                shape=shape,
                pool_source=payload.pool_source.value,
                source_balance_id=payload.source_balance_id,
                fmt=payload.format,
                pick_time_seconds=payload.pick_time_seconds,
                autopick_strategy=payload.autopick_strategy.value,
                allow_admin_override=payload.allow_admin_override,
                settings=payload.settings,
            )
            await draft_rt.publish_draft_event(
                session,
                draft_session=draft,
                event_type="draft.session_updated",
                payload={"session_id": draft.id, "status": draft.status},
                actor_user_id=user.id,
            )
            await session.commit()
            return await board_service.session_read(session, draft)

        return await c.envelope(logger, "draft.session_create", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.seed")
    async def _seed(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            session_id = c.require_id(data)
            tournament_id = c.path_int(data, "tournament_id")
            ws_id = await _get_tournament_workspace_id(session, tournament_id)
            c.require_workspace_permission(data, user, ws_id, "team", "create")
            payload = schemas.DraftSeedRequest.model_validate(c.payload(data))
            draft = await _sessions_repo.get_for_update(session, session_id)
            if draft is None:
                raise HTTPException(status_code=404, detail="Draft session not found")
            rules.validate_seed_version(draft, expected_version=payload.expected_version)
            before = await lifecycle_service.seed_row_counts(session, draft.id)
            version_before = draft.version
            savepoint = await session.begin_nested() if payload.preview_only else None
            try:
                if not payload.pool_captains:
                    raise HTTPException(
                        status_code=422,
                        detail="Provide pool_captains: a draft seat is a balancer registration",
                    )
                await lifecycle_service.seed_from_pool(
                    session,
                    draft,
                    captain_registration_ids=[c_.registration_id for c_ in payload.pool_captains],
                    team_names={c_.registration_id: c_.name for c_ in payload.pool_captains if c_.name},
                    captain_order=payload.captain_order,
                    rng_seed=payload.seed,
                )

                after = await lifecycle_service.seed_row_counts(session, draft.id)
                report = await feasibility_service.analyze_session(session, draft)
                response = schemas.DraftSeedResponse(
                    session=await board_service.session_read(session, draft),
                    preview_only=payload.preview_only,
                    diff=_seed_diff(
                        before=before,
                        after=after,
                        version_before=version_before,
                        version_after=draft.version,
                    ),
                    feasibility=schemas.DraftFeasibilityResponse.model_validate(report),
                )
                if savepoint is not None:
                    await savepoint.rollback()
                    return response

                await draft_rt.publish_draft_event(
                    session,
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
            c.require_workspace_permission(data, user, ws_id, "team", "create")
            payload = schemas.DraftSessionPatchRequest.model_validate(c.payload(data))
            draft = await _load_session(session, session_id)
            if payload.pick_time_seconds is not None:
                draft.pick_time_seconds = payload.pick_time_seconds
            if payload.autopick_strategy is not None:
                draft.autopick_strategy = payload.autopick_strategy.value
            if payload.allow_admin_override is not None:
                draft.allow_admin_override = payload.allow_admin_override
            if payload.rounds is not None:
                # Kept only so a stale client cannot silently desync the board:
                # the sole accepted value is the one the shape already implies.
                rules.validate_draft_rounds(
                    rounds=payload.rounds, shape=await feasibility_service.resolve_shape(session, draft)
                )
                draft.rounds = payload.rounds
            if payload.settings is not None:
                draft.settings_json = payload.settings
            # The pick rows carry the seat order, and `round_rules` decides it, so
            # a rules change that stopped at `settings_json` left the board picking
            # in the order it was seeded with while the wizard previewed the new
            # one. Rounds already in progress keep their order (see
            # lifecycle_service.resync_pick_order).
            moved = await lifecycle_service.resync_pick_order(session, draft)
            if moved:
                await draft_rt.publish_draft_event(
                    session,
                    draft_session=draft,
                    event_type="draft.session_updated",
                    payload={"session_id": draft.id, "status": draft.status, "picks_reordered": moved},
                    actor_user_id=user.id,
                )
            await session.commit()
            await session.refresh(draft)
            return await board_service.session_read(session, draft)

        return await c.envelope(logger, "draft.session_patch", op, session_factory=_SF)

    def _make_lifecycle(subject: str, action, event_type: str, *, superuser_forces: bool = False) -> None:
        @broker.subscriber(subject)
        async def _handler(data: dict, msg: RabbitMessage) -> dict:
            async def op(session: Any) -> Any:
                user = c.active_actor(data)
                session_id = c.require_id(data)
                tournament_id = c.path_int(data, "tournament_id")
                ws_id = await _get_tournament_workspace_id(session, tournament_id)
                c.require_workspace_permission(data, user, ws_id, "team", "create")
                # Only ``start`` has a phase gate, and only a superuser may skip it.
                extra = {"force": bool(user.is_superuser)} if superuser_forces else {}
                return await _lifecycle_action(session, _redis(logger), session_id, action, event_type, user, **extra)

            return await c.envelope(logger, subject, op, session_factory=_SF)

    _make_lifecycle("rpc.balancer.draft.start", lifecycle_service.start, "draft.pick_started", superuser_forces=True)
    _make_lifecycle("rpc.balancer.draft.pause", lifecycle_service.pause, "draft.paused")
    _make_lifecycle("rpc.balancer.draft.resume", lifecycle_service.resume, "draft.resumed")
    _make_lifecycle("rpc.balancer.draft.cancel", lifecycle_service.cancel, "draft.cancelled")
    _make_lifecycle("rpc.balancer.draft.rollback", lifecycle_service.rollback, "draft.rollback")

    @broker.subscriber("rpc.balancer.draft.session_list")
    async def _session_list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            tournament_id = c.require_id(data)
            ws_id = await _get_tournament_workspace_id(session, tournament_id)
            c.require_workspace_permission(data, user, ws_id, "team", "read")
            rows = await _sessions_repo.list_by_tournament(session, tournament_id)
            # The shape lookup behind session_read is cache-backed at both
            # levels, so one call per row costs a dict hit, not a query.
            return [await board_service.session_read(session, row) for row in rows]

        return await c.envelope(logger, "draft.session_list", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.session_delete")
    async def _session_delete(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            session_id = c.require_id(data)
            tournament_id = c.path_int(data, "tournament_id")
            ws_id = await _get_tournament_workspace_id(session, tournament_id)
            c.require_workspace_permission(data, user, ws_id, "team", "create")
            draft = await _load_session(session, session_id)
            if draft.tournament_id != tournament_id:
                raise HTTPException(status_code=404, detail="Draft session not found")
            # Published before the row goes away: spectators keep a board keyed
            # by this session and would otherwise never learn it is gone.
            await draft_rt.publish_draft_event(
                session,
                draft_session=draft,
                event_type="draft.session_updated",
                payload={"session_id": draft.id, "status": draft.status, "deleted": True},
                actor_user_id=user.id,
            )
            await lifecycle_service.delete_session(session, draft)
            await session.commit()
            return None

        return await c.envelope(logger, "draft.session_delete", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.export")
    async def _export(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            session_id = c.require_id(data)
            tournament_id = c.path_int(data, "tournament_id")
            ws_id = await _get_tournament_workspace_id(session, tournament_id)
            c.require_workspace_permission(data, user, ws_id, "team", "create")
            draft = await _load_session(session, session_id)
            updated, _removed, _imported = await export_service.export(session, draft)
            await draft_rt.publish_draft_event(
                session,
                draft_session=updated,
                event_type="draft.completed",
                payload={"session_id": updated.id, "status": updated.status, "export_status": updated.export_status},
                actor_user_id=user.id,
            )
            # Materializing the drafted rosters rewrote tournament.team /
            # player / standing, so the PUBLIC reads are stale. Named here for
            # this service's own clients, and mirrored to app-service (which
            # caches the same three) through the transactional outbox.
            await emit(session, scope=Scope.tournament(updated.tournament_id), invalidates=EXPORT_RESOURCES)
            await enqueue_invalidation_outbox(
                session, scope=Scope.tournament(updated.tournament_id), resources=EXPORT_RESOURCES
            )
            await session.commit()
            return await board_service.session_read(session, updated)

        return await c.envelope(logger, "draft.export", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.export_ranks")
    async def _export_ranks(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            session_id = c.require_id(data)
            tournament_id = c.path_int(data, "tournament_id")
            ws_id = await _get_tournament_workspace_id(session, tournament_id)
            c.require_workspace_permission(data, user, ws_id, "team", "create")
            draft = await _load_session(session, session_id)
            # Ranks only: no team is removed or created, so no draft lifecycle
            # event — nothing about the session itself changed.
            updated = await export_service.export_ranks(session, draft)
            await emit(session, scope=Scope.tournament(draft.tournament_id), invalidates=EXPORT_RESOURCES)
            await enqueue_invalidation_outbox(
                session, scope=Scope.tournament(draft.tournament_id), resources=EXPORT_RESOURCES
            )
            await session.commit()
            return schemas.RanksExportResponse(success=True, updated_players=updated)

        return await c.envelope(logger, "draft.export_ranks", op, session_factory=_SF)

    # --- pick actions (keyed by pick_id) ------------------------------------
    @broker.subscriber("rpc.balancer.draft.pick_select")
    async def _pick_select(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            pick_id = c.require_id(data)
            payload = schemas.DraftPickSelectRequest.model_validate(c.payload(data))
            draft, pick = await _load_pick(session, pick_id)
            public_user_ids = await _actor_player_ids(session, user.id)
            public_user_id = public_user_ids[0] if public_user_ids else None
            is_admin = user.is_workspace_admin(draft.workspace_id)
            result = await selection_service.select(
                session,
                draft,
                pick,
                player_id=payload.player_id,
                expected_version=payload.expected_version,
                target_role=_to_role(payload.target_role),
                actor_user_id=public_user_id,
                actor_auth_user_id=user.id,
                actor_player_ids=public_user_ids,
                is_admin=is_admin,
            )
            await _publish_result(session, draft, result, made_event="draft.pick_made", actor_user_id=public_user_id)
            await session.commit()
            return await board_service.session_read(session, draft)

        return await c.envelope(logger, "draft.pick_select", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.pick_autopick")
    async def _pick_autopick(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            pick_id = c.require_id(data)
            ws_id = await _get_pick_workspace_id(session, pick_id)
            c.require_workspace_permission(data, user, ws_id, "team", "create")
            payload = schemas.DraftPickAutopickRequest.model_validate(c.payload(data))
            draft, pick = await _load_pick(session, pick_id)
            result = await selection_service.autopick(session, draft, pick, expected_version=payload.expected_version)
            await _publish_result(session, draft, result, made_event="draft.autopicked", actor_user_id=None)
            await session.commit()
            return await board_service.session_read(session, draft)

        return await c.envelope(logger, "draft.pick_autopick", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.pick_override")
    async def _pick_override(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            pick_id = c.require_id(data)
            ws_id = await _get_pick_workspace_id(session, pick_id)
            c.require_workspace_permission(data, user, ws_id, "team", "create")
            payload = schemas.DraftPickOverrideRequest.model_validate(c.payload(data))
            draft, pick = await _load_pick(session, pick_id)
            before = {
                "player_id": pick.picked_player_id,
                "team_id": pick.draft_team_id,
                "role": pick.target_role,
                "rank_value": pick.target_rank_value,
                "version": pick.version,
            }
            public_user_id = await _users_repo.get_id_by_auth_user_id(session, user.id)
            result = await selection_service.override(
                session,
                draft,
                pick,
                player_id=payload.player_id,
                expected_version=payload.expected_version,
                actor_user_id=public_user_id,
                target_role=_to_role(payload.target_role),
            )
            await _audit_repo.create(
                session,
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
                ),
            )
            await _publish_result(session, draft, result, made_event="draft.pick_made", actor_user_id=public_user_id)
            await session.commit()
            return await board_service.session_read(session, draft)

        return await c.envelope(logger, "draft.pick_override", op, session_factory=_SF)
