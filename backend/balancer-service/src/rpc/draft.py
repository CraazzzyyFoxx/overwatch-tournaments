"""Live Draft endpoints over typed RPC (rpc.balancer.draft.*).

Public reads (no auth) for spectating; lifecycle keyed by session_id for both owners and authorized on the
session's own owner (``services.draft.access``); tournament-only admin (create, seed, patch, delete, export) keyed
by tournament_id; pick actions keyed by pick_id. Every mutation's service stages its realtime event on
``draft:{session_id}:board`` inside the transaction the handler commits, so the WorkspaceEvent id orders with the
pick. The draft router has no admin-panel gate, so handlers enforce only the per-endpoint permission (or just the
active user, for /select).

A single worker-lifetime Redis client carries the clock nudges (publish failures
are swallowed by ``clock_svc.notify_*``).
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from faststream.rabbit import RabbitMessage
from redis.asyncio import Redis

from shared.core.enums import DraftStatus
from shared.rpc.common import optional_actor
from shared.rpc.identity import ensure_workspace_permission
from shared.schemas.role import RoleRef
from shared.services.chat import (
    HISTORY_DEFAULT,
    ChatMuteInput,
    ChatPostInput,
    ChatRoom,
    ChatSettingsInput,
)
from src import schemas
from src.core import db
from src.core.auth import (
    _get_tournament_draft_session_workspace_id,
    _get_tournament_workspace_id,
)
from src.core.config import config
from src.rpc import _common as c
from src.services.draft import clock as clock_svc
from src.services.draft import loaders
from src.services.draft.access import acts_for_any_team, ensure_organizer, ensure_team_actor, hold_owner
from src.services.draft.board import board_service
from src.services.draft.chat_access import draft_chat_service
from src.services.draft.export import export_service
from src.services.draft.feasibility import feasibility_service
from src.services.draft.journal import JOURNAL_LIMIT_DEFAULT, journal_service
from src.services.draft.lifecycle import lifecycle_service
from src.services.draft.queue import queue_service
from src.services.draft.role_edit import role_edit_service
from src.services.formation_node import require_formation_node

_SF = db.async_session_maker

# A single worker-lifetime client (asyncio redis is safe for concurrent use via
# its pool). The clock nudges swallow publish failures, so they are best-effort.
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
    """Close the worker-lifetime Redis client (called on worker shutdown)."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None


def register(broker: Any, logger: Any) -> None:
    # --- public reads -------------------------------------------------------
    @broker.subscriber("rpc.balancer.draft.tournament_board")
    async def _tournament_board(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            tournament_id = c.require_id(data)
            node_id = c.formation_node_id(data)
            await require_formation_node(session, tournament_id, node_id)
            draft = await board_service.get_active_session(session, node_id)
            if draft is None:
                return None
            return await board_service.build_board(session, draft)

        return await c.envelope(logger, "draft.tournament_board", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.session_get")
    async def _session_get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            draft = await lifecycle_service.get_session(session, c.require_id(data))
            return await board_service.session_read(session, draft)

        return await c.envelope(logger, "draft.session_get", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.session_board")
    async def _session_board(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            draft = await lifecycle_service.get_session(session, c.require_id(data))
            return await board_service.build_board(session, draft)

        return await c.envelope(logger, "draft.session_board", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.feasibility")
    async def _feasibility(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            session_id = c.require_id(data)
            draft = await lifecycle_service.get_session(session, session_id)
            await ensure_organizer(session, user, draft, "read")

            async def compute() -> schemas.DraftFeasibilityResponse:
                snapshot = await feasibility_service.load_read_snapshot(session, draft)
                state = await feasibility_service.state_from_snapshot(session, draft, snapshot)
                report = await feasibility_service.analyze_session(session, draft, state=state)
                return schemas.DraftFeasibilityResponse.model_validate(report)

            # Refetched by every organizer in the room after every pick: one
            # analysis per board state, on the snapshot fit and queue share.
            return await board_service.shared_read(session, draft, ("feasibility",), compute)

        return await c.envelope(logger, "draft.feasibility", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.pick_options")
    async def _pick_options(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            draft, pick = await lifecycle_service.get_pick(session, c.require_id(data))
            player_id = await lifecycle_service.actor_player_id(session, user.id)
            options = await feasibility_service.options_for_current_pick(
                session,
                draft,
                pick,
                actor_auth_user_id=user.id,
                actor_player_ids=[player_id] if player_id is not None else [],
                is_workspace_admin=await acts_for_any_team(session, user, draft),
            )
            dimension = await loaders.rated_dimension(session, draft)
            return schemas.DraftPickOptionsResponse(
                pick_id=pick.id,
                pick_version=pick.version,
                draft_team_id=pick.draft_team_id,
                options=[
                    schemas.DraftPickOptionRead(**{**asdict(option), "role": RoleRef.of(dimension, option.role)})
                    for option in options
                ],
            )

        return await c.envelope(logger, "draft.pick_options", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.player_role_edit")
    async def _player_role_edit(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            player_id = c.require_id(data)
            session_id = c.path_int(data, "session_id")
            draft = await lifecycle_service.get_session(session, session_id)
            await ensure_organizer(session, user, draft)
            payload = schemas.DraftRoleEditRequest.model_validate(c.payload(data))
            response = await role_edit_service.edit_player_role(
                session,
                draft,
                player_id=player_id,
                role=await lifecycle_service.resolve_role(session, draft, payload.role),
                rank_value=payload.rank_value,
                reason=payload.reason,
                expected_version=payload.expected_version,
                actor_auth_user_id=user.id,
                preview_only=payload.preview_only,
            )
            if response.committed:
                await session.commit()
            return response

        return await c.envelope(logger, "draft.player_role_edit", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.suggestions")
    async def _suggestions(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            session_id = c.require_id(data)
            draft = await lifecycle_service.get_session(session, session_id)
            await ensure_organizer(session, user, draft, "read")
            current, ranked = await feasibility_service.rank_current_suggestions(session, draft)
            dimension = await loaders.rated_dimension(session, draft)
            return schemas.DraftSuggestionsResponse(
                pick_id=current.id,
                draft_team_id=current.draft_team_id,
                suggestions=[
                    schemas.DraftSuggestion(
                        player_id=r.player_id,
                        role=RoleRef.of(dimension, r.role),
                        fit_score=r.fit_score,
                        breakdown=r.breakdown,
                    )
                    for r in ranked
                ],
            )

        return await c.envelope(logger, "draft.suggestions", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.team_fit")
    async def _team_fit(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            draft = await lifecycle_service.get_session(session, c.require_id(data))
            team = await lifecycle_service.get_team(session, draft, c.path_int(data, "team_id"))
            await ensure_team_actor(session, user, draft, team, "read")

            async def compute() -> schemas.DraftTeamFitResponse:
                scores = await feasibility_service.team_fit_scores(session, draft, team_id=team.id)
                dimension = await loaders.rated_dimension(session, draft)
                return schemas.DraftTeamFitResponse(
                    session_id=draft.id,
                    team_id=team.id,
                    scores=[
                        schemas.DraftTeamFitScore(
                            player_id=score.player_id, role=RoleRef.of(dimension, score.role), score=score.score
                        )
                        for score in scores
                    ],
                )

            # Refetched by every viewer on every draft event: one run per board state.
            return await board_service.shared_read(session, draft, ("fit", team.id, draft.autopick_strategy), compute)

        return await c.envelope(logger, "draft.team_fit", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.queue_get")
    async def _queue_get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            draft = await lifecycle_service.get_session(session, c.require_id(data))
            team = await lifecycle_service.get_team(session, draft, c.path_int(data, "team_id"))
            await ensure_team_actor(session, user, draft, team, "create")
            # The private queue is in the key: queue_set emits no event.
            queue = ",".join(str(player_id) for player_id in team.pick_queue or [])
            return await board_service.shared_read(
                session, draft, ("queue", team.id, queue), lambda: queue_service.read(session, draft, team)
            )

        return await c.envelope(logger, "draft.queue_get", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.queue_set")
    async def _queue_set(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            draft = await lifecycle_service.get_session(session, c.require_id(data))
            team = await lifecycle_service.get_team(session, draft, c.path_int(data, "team_id"))
            await ensure_team_actor(session, user, draft, team, "create")
            payload = schemas.DraftTeamQueueRequest.model_validate(c.payload(data))
            response = await queue_service.write(session, draft, team, payload.player_ids)
            # No realtime event: a queue is viewer-scoped, and the broadcast
            # topic is read by the whole room including the other captains.
            await session.commit()
            return response

        return await c.envelope(logger, "draft.queue_set", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.journal")
    async def _journal(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            session_id = c.require_id(data)
            draft = await lifecycle_service.get_session(session, session_id)
            await ensure_organizer(session, user, draft)
            return await journal_service.list_entries(
                session, draft, limit=c.q1(data, "limit", int, JOURNAL_LIMIT_DEFAULT)
            )

        return await c.envelope(logger, "draft.journal", op, session_factory=_SF)

    # --- admin lifecycle (keyed by tournament_id) ---------------------------
    @broker.subscriber("rpc.balancer.draft.session_create")
    async def _session_create(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            tournament_id = c.require_id(data)
            workspace_id = await _get_tournament_workspace_id(session, tournament_id)
            ensure_workspace_permission(user, workspace_id, "team", "create")
            payload = schemas.DraftSessionCreateRequest.model_validate(c.payload(data))
            draft = await lifecycle_service.create_for_tournament(
                session, payload, tournament_id=tournament_id, workspace_id=workspace_id, actor_user_id=user.id
            )
            await session.commit()
            return await board_service.session_read(session, draft)

        return await c.envelope(logger, "draft.session_create", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.seed")
    async def _seed(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            session_id = c.require_id(data)
            ws_id = await _get_tournament_draft_session_workspace_id(
                session, c.path_int(data, "tournament_id"), session_id
            )
            ensure_workspace_permission(user, ws_id, "team", "create")
            payload = schemas.DraftSeedRequest.model_validate(c.payload(data))
            response = await lifecycle_service.seed_or_preview(session, session_id, payload, actor_user_id=user.id)
            # A preview's writes died with its savepoint: this commit only releases the row lock.
            await session.commit()
            return response

        return await c.envelope(logger, "draft.seed", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.session_patch")
    async def _session_patch(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            session_id = c.require_id(data)
            ws_id = await _get_tournament_draft_session_workspace_id(
                session, c.path_int(data, "tournament_id"), session_id
            )
            ensure_workspace_permission(user, ws_id, "team", "create")
            payload = schemas.DraftSessionPatchRequest.model_validate(c.payload(data))
            draft = await lifecycle_service.patch_session(session, session_id, payload, actor_user_id=user.id)
            await session.commit()
            await session.refresh(draft)
            return await board_service.session_read(session, draft)

        return await c.envelope(logger, "draft.session_patch", op, session_factory=_SF)

    # --- lifecycle (keyed by session_id; both owners) -----------------------
    def _make_lifecycle(
        subject: str, action, event_type: str, audit_action: str, *, superuser_forces: bool = False
    ) -> None:
        @broker.subscriber(subject)
        async def _handler(data: dict, msg: RabbitMessage) -> dict:
            async def op(session: Any) -> Any:
                user = c.active_actor(data)
                session_id = c.require_id(data)
                draft = await lifecycle_service.get_session(session, session_id)
                await hold_owner(session, draft)
                await ensure_organizer(session, user, draft)
                # Only a tournament's ``start`` has a phase gate, and only a superuser may skip it.
                extra = {"force": bool(user.is_superuser)} if superuser_forces else {}
                draft = await lifecycle_service.transition(
                    session,
                    session_id,
                    action,
                    event_type=event_type,
                    audit_action=audit_action,
                    actor_auth_user_id=user.id,
                    **extra,
                )
                await session.commit()
                if draft.status == DraftStatus.LIVE.value:
                    # Wake the supervisor so a freshly started/resumed draft gets its
                    # autopick clock loop immediately (the idle discovery poll is relaxed).
                    await clock_svc.notify_supervisor(_redis(logger))
                return await board_service.session_read(session, draft)

            return await c.envelope(logger, subject, op, session_factory=_SF)

    _make_lifecycle(
        "rpc.balancer.draft.start",
        lifecycle_service.start,
        "draft.pick_started",
        "started",
        superuser_forces=True,
    )
    _make_lifecycle("rpc.balancer.draft.pause", lifecycle_service.pause, "draft.paused", "paused")
    _make_lifecycle("rpc.balancer.draft.resume", lifecycle_service.resume, "draft.resumed", "resumed")
    _make_lifecycle("rpc.balancer.draft.cancel", lifecycle_service.cancel, "draft.cancelled", "cancelled")
    _make_lifecycle("rpc.balancer.draft.rollback", lifecycle_service.rollback, "draft.rollback", "rollback")

    @broker.subscriber("rpc.balancer.draft.session_list")
    async def _session_list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            tournament_id = c.require_id(data)
            ws_id = await _get_tournament_workspace_id(session, tournament_id)
            ensure_workspace_permission(user, ws_id, "team", "read")
            node_id = c.formation_node_id(data)
            await require_formation_node(session, tournament_id, node_id)
            return await board_service.list_sessions(session, node_id)

        return await c.envelope(logger, "draft.session_list", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.session_delete")
    async def _session_delete(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            session_id = c.require_id(data)
            tournament_id = c.path_int(data, "tournament_id")
            ws_id = await _get_tournament_draft_session_workspace_id(session, tournament_id, session_id)
            ensure_workspace_permission(user, ws_id, "team", "create")
            await lifecycle_service.delete_for_tournament(
                session, session_id, tournament_id=tournament_id, actor_user_id=user.id
            )
            await session.commit()
            return None

        return await c.envelope(logger, "draft.session_delete", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.export")
    async def _export(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            session_id = c.require_id(data)
            ws_id = await _get_tournament_draft_session_workspace_id(
                session, c.path_int(data, "tournament_id"), session_id
            )
            ensure_workspace_permission(user, ws_id, "team", "create")
            draft = await lifecycle_service.get_session(session, session_id)
            updated, _removed, _imported, advisories = await export_service.export(
                session, draft, actor_user_id=user.id
            )
            await session.commit()
            read = await board_service.session_read(session, updated)
            return schemas.DraftExportResponse(**read.model_dump(), advisories=advisories)

        return await c.envelope(logger, "draft.export", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.export_ranks")
    async def _export_ranks(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            session_id = c.require_id(data)
            ws_id = await _get_tournament_draft_session_workspace_id(
                session, c.path_int(data, "tournament_id"), session_id
            )
            ensure_workspace_permission(user, ws_id, "team", "create")
            draft = await lifecycle_service.get_session(session, session_id)
            updated = await export_service.export_ranks(session, draft)
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
            draft, pick = await lifecycle_service.get_pick(session, pick_id)
            await hold_owner(session, draft)
            await lifecycle_service.select_pick(
                session,
                draft,
                pick,
                payload,
                actor_auth_user_id=user.id,
                is_admin=await acts_for_any_team(session, user, draft),
            )
            await session.commit()
            return await board_service.session_read(session, draft)

        return await c.envelope(logger, "draft.pick_select", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.pick_autopick")
    async def _pick_autopick(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            pick_id = c.require_id(data)
            draft, pick = await lifecycle_service.get_pick(session, pick_id)
            await hold_owner(session, draft)
            await ensure_organizer(session, user, draft)
            payload = schemas.DraftPickAutopickRequest.model_validate(c.payload(data))
            await lifecycle_service.autopick_pick(
                session, draft, pick, expected_version=payload.expected_version, actor_auth_user_id=user.id
            )
            await session.commit()
            return await board_service.session_read(session, draft)

        return await c.envelope(logger, "draft.pick_autopick", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.pick_extend")
    async def _pick_extend(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            pick_id = c.require_id(data)
            draft, pick = await lifecycle_service.get_pick(session, pick_id)
            await ensure_organizer(session, user, draft)
            payload = schemas.DraftPickExtendRequest.model_validate(c.payload(data))
            await lifecycle_service.extend_pick(
                session,
                draft,
                pick,
                seconds=payload.seconds,
                expected_version=payload.expected_version,
                actor_auth_user_id=user.id,
            )
            await session.commit()
            # The owning clock loop is asleep until the OLD deadline; without this
            # nudge it would wake there and autopick the time we just granted away.
            await clock_svc.notify_clock(_redis(logger), draft.id)
            return await board_service.session_read(session, draft)

        return await c.envelope(logger, "draft.pick_extend", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.pick_override")
    async def _pick_override(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            pick_id = c.require_id(data)
            draft, pick = await lifecycle_service.get_pick(session, pick_id)
            await hold_owner(session, draft)
            await ensure_organizer(session, user, draft)
            payload = schemas.DraftPickOverrideRequest.model_validate(c.payload(data))
            await lifecycle_service.override_pick(session, draft, pick, payload, actor_auth_user_id=user.id)
            await session.commit()
            return await board_service.session_read(session, draft)

        return await c.envelope(logger, "draft.pick_override", op, session_factory=_SF)

    # --- room chat (keyed by session_id; the room IS the draft session) -----
    @broker.subscriber("rpc.balancer.draft.chat_history")
    async def _chat_history(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            return await draft_chat_service.envelope(
                session,
                optional_actor(data),
                ChatRoom.draft(c.require_id(data)),
                after_id=c.q1(data, "after_id", int),
                limit=c.q1(data, "limit", int, HISTORY_DEFAULT),
            )

        return await c.envelope(logger, "draft.chat_history", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.chat_post")
    async def _chat_post(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            room = ChatRoom.draft(c.require_id(data))
            payload = ChatPostInput.model_validate(c.payload(data))
            return await draft_chat_service.post(session, user, room, payload.body)

        return await c.envelope(logger, "draft.chat_post", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.chat_delete")
    async def _chat_delete(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            room = ChatRoom.draft(c.require_id(data))
            await draft_chat_service.delete(session, user, room, c.path_int(data, "message_id"))
            return {"deleted": True}

        return await c.envelope(logger, "draft.chat_delete", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.chat_settings")
    async def _chat_settings(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            room = ChatRoom.draft(c.require_id(data))
            payload = ChatSettingsInput.model_validate(c.payload(data))
            return await draft_chat_service.set_settings(
                session, user, room, spectators_can_read=payload.spectators_can_read
            )

        return await c.envelope(logger, "draft.chat_settings", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.chat_mute_set")
    async def _chat_mute_set(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            room = ChatRoom.draft(c.require_id(data))
            payload = ChatMuteInput.model_validate(c.payload(data))
            return await draft_chat_service.set_mute(
                session,
                user,
                room,
                c.path_int(data, "target_user_id"),
                minutes=payload.minutes,
                reason=payload.reason,
            )

        return await c.envelope(logger, "draft.chat_mute_set", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.draft.chat_mute_clear")
    async def _chat_mute_clear(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            room = ChatRoom.draft(c.require_id(data))
            await draft_chat_service.clear_mute(session, user, room, c.path_int(data, "target_user_id"))
            return {"deleted": True}

        return await c.envelope(logger, "draft.chat_mute_clear", op, session_factory=_SF)
