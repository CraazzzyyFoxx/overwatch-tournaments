"""FFA lobby methods over typed RPC: two public reads and three admin writes.

The reads answer the lobby table the frontend draws (``schemas/ffa.py``) and are
gated exactly like every other public tournament read -- a hidden tournament
404s for an ineligible viewer before anything else is loaded.

The writes are the organizer's three levers on a lobby: record (or correct) one
game, void one game, change how many games the lobby plays. Each carries the
same workspace ``match.update`` permission, files an admin-audit row before the
service runs, and refuses a correction whose downstream qualification is
already live -- the duel result endpoints' contract, unchanged
(``src/rpc/admin_misc.py``).

Every write answers the lobby's own table, so the admin UI re-renders the whole
group from the response instead of refetching it.

The gateway passes path params as ``data["<name>"]`` (and the primary id as
``data["id"]`` when the RouteSpec sets IDParam), query params as
``data["query"][key] = [values]``, and the JSON body as ``data["payload"]``.
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit.annotations import RabbitMessage

from shared.domain.ffa_scoring import FfaGameLine
from shared.repository import UserRepository
from shared.rpc.identity import ensure_workspace_permission, rehydrate_user_optional
from shared.services.audit import record_admin_audit
from shared.services.tournament.visibility import assert_tournament_viewable
from src import models
from src.core import auth
from src.rpc._helpers import _dump, _identity, _path_int, _payload, _read, _require_id, _run
from src.schemas.ffa import FfaGameCancelInput, FfaGameResultsInput, FfaGamesCountInput
from src.services import visibility_resolvers
from src.services.admin.stage import stage_service as admin_stage_service
from src.services.encounter.ffa import ffa_encounter_service

_user_repo = UserRepository()


async def _actor_player_id(session: Any, user: models.AuthUser) -> int | None:
    """The caller's ``players.user`` id -- what the audit trail stores.

    Same translation as ``admin_misc._actor_player_id``: the token carries an
    auth id, while ``EncounterResultAudit.actor_user_id`` references a player.
    """
    return await _user_repo.get_id_by_auth_user_id(session, user.id)


async def _assert_source_correction_allowed(session: Any, encounter_id: int) -> None:
    """Refuse a change whose qualification fallout can no longer be applied.

    All three writes can move a group's final table -- a corrected game, a
    voided one, a games count that reopens a completed lobby -- so all three
    answer to the rule the stage service owns. A missing lobby is left to the
    service below to 404 on.
    """
    lobby = await ffa_encounter_service.encounter_repo.get(session, encounter_id)
    if lobby is not None:
        await admin_stage_service.assert_source_correction_allowed(session, lobby)


async def _admin_lobby(session: Any, data: dict) -> tuple[models.AuthUser, int, int]:
    """The shared prologue of the three writes: caller, lobby, workspace."""
    user = _identity(data)
    encounter_id = _require_id(data)
    ws_id = await auth.get_encounter_workspace_id(session, encounter_id)
    ensure_workspace_permission(user, ws_id, "match", "update")
    return user, encounter_id, ws_id


def register(broker: Any, logger: Any) -> None:
    # ── public reads ──────────────────────────────────────────────────────

    @broker.subscriber("rpc.tournament.ffa_stage")
    async def _ffa_stage(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            # Public route — no identity required, but hidden tournaments 404.
            tournament_id = _require_id(data)
            await assert_tournament_viewable(session, rehydrate_user_optional(data.get("identity")), tournament_id)
            return await ffa_encounter_service.load_stage_lobbies(
                session, _path_int(data, "stage_id"), tournament_id=tournament_id
            )

        return await _read(logger, op)

    @broker.subscriber("rpc.tournament.ffa_lobby")
    async def _ffa_lobby(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            encounter_id = _require_id(data)
            tournament_id = await visibility_resolvers.visibility_resolvers_service.tournament_id_for_encounter(
                session, encounter_id
            )
            await assert_tournament_viewable(session, rehydrate_user_optional(data.get("identity")), tournament_id)
            return await ffa_encounter_service.load_lobby(session, encounter_id)

        return await _read(logger, op)

    # ── admin writes ──────────────────────────────────────────────────────

    @broker.subscriber("rpc.tournament.ffa_game_results_set")
    async def _ffa_game_results_set(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user, encounter_id, ws_id = await _admin_lobby(session, data)
            position = _path_int(data, "position")
            body = FfaGameResultsInput.model_validate(_payload(data))
            await record_admin_audit(
                session,
                action="encounter.ffa_game_results_set",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="encounter",
                entity_id=encounter_id,
                after={"position": position, **body.model_dump(mode="json")},
            )
            await _assert_source_correction_allowed(session, encounter_id)
            # set_game_results commits internally; the settled table comes back.
            await ffa_encounter_service.set_game_results(
                session,
                encounter_id,
                position,
                [
                    FfaGameLine(team_id=line.team_id, placement=line.placement, score=line.score)
                    for line in body.results
                ],
                actor_user_id=await _actor_player_id(session, user),
                reason=body.reason,
            )
            return _dump(await ffa_encounter_service.load_lobby(session, encounter_id))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.ffa_game_cancel")
    async def _ffa_game_cancel(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user, encounter_id, ws_id = await _admin_lobby(session, data)
            position = _path_int(data, "position")
            body = FfaGameCancelInput.model_validate(_payload(data))
            await record_admin_audit(
                session,
                action="encounter.ffa_game_cancel",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="encounter",
                entity_id=encounter_id,
                after={"position": position, "reason": body.reason},
            )
            await _assert_source_correction_allowed(session, encounter_id)
            # cancel_game commits internally.
            await ffa_encounter_service.cancel_game(
                session,
                encounter_id,
                position,
                actor_user_id=await _actor_player_id(session, user),
                reason=body.reason,
            )
            return _dump(await ffa_encounter_service.load_lobby(session, encounter_id))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.ffa_games_count_set")
    async def _ffa_games_count_set(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user, encounter_id, ws_id = await _admin_lobby(session, data)
            body = FfaGamesCountInput.model_validate(_payload(data))
            await record_admin_audit(
                session,
                action="encounter.ffa_games_count_set",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="encounter",
                entity_id=encounter_id,
                after=body.model_dump(mode="json"),
            )
            await _assert_source_correction_allowed(session, encounter_id)
            # set_games_count commits internally.
            await ffa_encounter_service.set_games_count(
                session,
                encounter_id,
                body.games,
                actor_user_id=await _actor_player_id(session, user),
            )
            return _dump(await ffa_encounter_service.load_lobby(session, encounter_id))

        return await _run(logger, op)
