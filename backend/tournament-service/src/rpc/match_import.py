"""Import one encounter game's match by its external id: a captain of either team, or an organizer.

This module only authorizes the caller and names the target game of a tournament encounter; the stats service owns
the request (``rpc.stats.ingest.fetch`` / ``fetch_list``, internal subjects): which source the encounter's discipline
fetches from (none: 422 ``unsupported_ingestor``), the retries, the ingest job and the organizer warnings. Its reply
is relayed verbatim, refusals included.
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit.annotations import RabbitMessage

from shared.core import http_status as status
from shared.core.enums import EncounterGameState
from shared.core.errors import ApiExc
from shared.core.errors import BaseAPIException as HTTPException
from shared.messaging.rpc import request_dict
from shared.rpc.identity import ensure_workspace_permission
from shared.schemas.rpc import rpc_error
from shared.services.scrim_scope import is_scrim_container
from src.core import auth
from src.rpc._helpers import _identity, _path_int, _payload, _require_id, _run
from src.schemas.captain import MatchImportInput
from src.services.encounter.captain import captain_service
from src.services.encounter.games import encounter_game_service

__all__ = ("register",)

_STATS_TIMEOUT = 10.0


async def _target(session: Any, data: dict[str, Any]) -> tuple[Any, Any]:
    """The tournament encounter and its live game the path names."""
    encounter = await captain_service._load_encounter(session, _require_id(data), for_update=False)
    if encounter.tournament_id is None or await is_scrim_container(session, encounter.tournament_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=[ApiExc(code="match_import_tournament_only", msg="Matches are imported for tournament games only")],
        )
    game = await encounter_game_service.get_game(session, _path_int(data, "game_id"))
    if game is None or game.encounter_id != encounter.id or game.state == EncounterGameState.CANCELLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Game not found")
    return encounter, game


def _submission(encounter: Any, game: Any, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "workspace_id": encounter.workspace_id,
        "discipline": encounter.discipline,
        "tournament_id": encounter.tournament_id,
        "encounter_id": encounter.id,
        "encounter_game_id": game.id,
        "external_id": MatchImportInput.model_validate(_payload(data)).external_id,
    }


async def _forward(broker: Any, logger: Any, data: dict[str, Any], queue: str, checked: dict[str, Any]) -> dict:
    """Hand an authorized request to stats and return its envelope as it is."""
    if not checked.get("ok"):
        return checked
    try:
        reply = await request_dict(
            broker, {"identity": data.get("identity"), "payload": checked["data"]}, queue, timeout=_STATS_TIMEOUT
        )
    except Exception:
        logger.exception("stats {} is unreachable", queue)
        reply = None
    return reply if reply is not None and "ok" in reply else rpc_error("unavailable", "Match import is unavailable")


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.tournament.captain_match_import")
    async def _captain_match_import(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            encounter, game = await _target(session, data)
            await captain_service.captain_seat(session, user, encounter)
            return _submission(encounter, game, data)

        return await _forward(broker, logger, data, "rpc.stats.ingest.fetch", await _run(logger, op))

    @broker.subscriber("rpc.tournament.captain_match_imports")
    async def _captain_match_imports(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            encounter, game = await _target(session, data)
            await captain_service.captain_seat(session, user, encounter)
            return {"encounter_game_id": game.id, "warnings": False}

        return await _forward(broker, logger, data, "rpc.stats.ingest.fetch_list", await _run(logger, op))

    @broker.subscriber("rpc.tournament.admin_match_import")
    async def _admin_match_import(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            ws_id = await auth.get_encounter_workspace_id(session, _require_id(data))
            ensure_workspace_permission(user, ws_id, "match", "result")
            encounter, game = await _target(session, data)
            return _submission(encounter, game, data)

        return await _forward(broker, logger, data, "rpc.stats.ingest.fetch", await _run(logger, op))

    @broker.subscriber("rpc.tournament.admin_match_imports")
    async def _admin_match_imports(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            ws_id = await auth.get_encounter_workspace_id(session, _require_id(data))
            # ``read`` like the room history: the list writes nothing.
            ensure_workspace_permission(user, ws_id, "match", "read")
            _encounter, game = await _target(session, data)
            return {"encounter_game_id": game.id, "warnings": True}

        return await _forward(broker, logger, data, "rpc.stats.ingest.fetch_list", await _run(logger, op))
