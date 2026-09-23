"""Typed RPC surface for ad-hoc scrim rooms.

Design: ``docs/plans/2026-08-12-scrim-rooms.md``.

Five subjects, all thin: every rule (workspace membership, the per-creator open
room cap, one-captain-per-person, hidden-container visibility) lives in
``services/scrim/service.py``, because ``claim_side`` and ``create_room`` enforce
the same invariants and a handler-level check would only be enforced on one path.

The rooms these subjects hand out are played through the EXISTING pre-game
subjects (``captain_pick_ban_*``, ``captain_ready``, ``captain_report_game``) —
nothing here duplicates them. Once a room's two ``Team.captain_id`` values are
set, the engine's own resolver does the rest.
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit.annotations import RabbitMessage

from shared.core.errors import BaseAPIException as HTTPException
from shared.rpc.identity import rehydrate_user_optional
from src import models, schemas
from src.rpc._helpers import _dump, _identity, _payload, _read, _require_q1, _run
from src.services.scrim.service import scrim_service


def _token(data: dict[str, Any]) -> str:
    """The room's share token, from the route's ``{token}`` path segment.

    A string, not an id: the token IS the room's address, and making it
    guessable-by-increment would hand every room to anyone who can count.
    """
    raw = data.get("token")
    if not isinstance(raw, str) or not raw.strip():
        raise HTTPException(status_code=422, detail="token is required")
    return raw.strip()


def _room(payload: dict) -> Any:
    return _dump(schemas.ScrimRoomRead.model_validate(payload))


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.tournament.scrim_create")
    async def _scrim_create(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            body = schemas.ScrimCreateRequest.model_validate(_payload(data))
            room = await scrim_service.create_room(
                session,
                user,
                workspace_id=body.workspace_id,
                label=body.label,
                best_of=body.best_of,
                home_team_name=body.home_team_name,
                away_team_name=body.away_team_name,
                pool=body.pool.model_dump(mode="json"),
            )
            return _room(room)

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.scrim_list_mine")
    async def _scrim_list_mine(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            workspace_id = _require_q1(data, "workspace_id", int)
            rooms = await scrim_service.list_rooms_for_viewer(session, user, workspace_id)
            return schemas.ScrimRoomListRead(rooms=[schemas.ScrimRoomRead.model_validate(r) for r in rooms])

        return await _read(logger, op)

    @broker.subscriber("rpc.tournament.scrim_get")
    async def _scrim_get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            # AuthOptional: a room is still 404 for a viewer who may not see its
            # hidden container, so the anonymous case is answered by the same
            # visibility gate as every other tournament read, not by a shortcut
            # here.
            user: models.AuthUser | None = rehydrate_user_optional(data.get("identity"))
            room = await scrim_service.get_room_by_token(session, user, _token(data))
            return schemas.ScrimRoomRead.model_validate(room)

        return await _read(logger, op)

    @broker.subscriber("rpc.tournament.scrim_claim")
    async def _scrim_claim(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            return _room(await scrim_service.claim_side(session, user, _token(data)))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.scrim_close")
    async def _scrim_close(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            return _room(await scrim_service.close_room(session, user, _token(data)))

        return await _run(logger, op)
