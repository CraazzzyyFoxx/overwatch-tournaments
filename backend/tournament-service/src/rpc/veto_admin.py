"""Map-veto admin methods over typed RPC.

Mirrors the ``admin_misc`` conventions: rehydrate the gateway-injected
identity, run the workspace "match"/"update" permission check (via the
tournament — directly for config routes, through the encounter for session
routes), validate the body, call the service and return plain dicts. The
gateway passes the primary path id as ``data["id"]`` (RouteSpec IDParam:
tournament_id for config list/upsert, config_id for delete, encounter_id for
session reset/act) and the JSON body as ``data["payload"]``.

Commit semantics: config upsert/delete commit here (plain ORM writes);
``reset_veto_session`` and ``perform_veto_action`` commit internally.
"""

from __future__ import annotations

from typing import Any, Literal

from faststream.rabbit.annotations import RabbitMessage
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.rpc.identity import ensure_workspace_permission
from src import models
from src.core import auth
from src.rpc._helpers import _identity, _payload, _require_id, _run
from src.services.encounter import map_veto as map_veto_service
from src.services.encounter import veto_session as veto_session_service


class VetoConfigUpsert(BaseModel):
    """Body for the veto-config upsert route (PUT .../veto-configs)."""

    stage_id: int | None = None
    round: int | None = None
    preset: str | None = Field(default=None, max_length=32)
    turn_timer_seconds: int | None = Field(default=None, ge=1)
    sequence: list[str]
    map_ids: list[int]


class AdminVetoAct(BaseModel):
    """Body for the admin act-for-a-side route (POST .../veto-act)."""

    side: Literal["home", "away"]
    map_id: int
    action: Literal["pick", "ban"]


def _serialize_config(config: models.MapVetoConfig) -> dict[str, Any]:
    """Config DTO — ``map_pool`` must be loaded (relationship orders by sort_order)."""
    return {
        "id": config.id,
        "tournament_id": config.tournament_id,
        "stage_id": config.stage_id,
        "round": config.round,
        "preset": config.preset,
        "first_pick_rule": config.first_pick_rule,
        "turn_timer_seconds": config.turn_timer_seconds,
        "sequence": list(config.veto_sequence_json or []),
        "map_ids": [entry.map_id for entry in config.map_pool],
    }


async def _load_encounter(session: Any, encounter_id: int) -> models.Encounter:
    encounter = await session.scalar(select(models.Encounter).where(models.Encounter.id == encounter_id))
    if encounter is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encounter not found")
    return encounter


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.tournament.admin_veto_config_list")
    async def _admin_veto_config_list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            ws_id = await auth.get_tournament_workspace_id(session, tournament_id)
            ensure_workspace_permission(user, ws_id, "match", "update")
            result = await session.execute(
                select(models.MapVetoConfig)
                .where(models.MapVetoConfig.tournament_id == tournament_id)
                .options(selectinload(models.MapVetoConfig.map_pool))
                .order_by(
                    models.MapVetoConfig.stage_id.asc().nulls_first(),
                    models.MapVetoConfig.round.asc().nulls_first(),
                    models.MapVetoConfig.id.asc(),
                )
            )
            return {"configs": [_serialize_config(config) for config in result.scalars().all()]}

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.admin_veto_config_upsert")
    async def _admin_veto_config_upsert(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            ws_id = await auth.get_tournament_workspace_id(session, tournament_id)
            ensure_workspace_permission(user, ws_id, "match", "update")
            body = VetoConfigUpsert.model_validate(_payload(data))

            veto_session_service.validate_veto_config(body.sequence, body.map_ids)
            if body.round is not None and body.stage_id is None:
                raise HTTPException(status_code=422, detail="round requires stage_id")
            if body.stage_id is not None:
                stage_tournament_id = await session.scalar(
                    select(models.Stage.tournament_id).where(models.Stage.id == body.stage_id)
                )
                if stage_tournament_id is None:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stage not found")
                if stage_tournament_id != tournament_id:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Stage does not belong to this tournament",
                    )

            # Upsert key = (tournament_id, stage_id, round): replace fields +
            # pool of the existing cascade-level row, else insert a new one.
            existing_query = (
                select(models.MapVetoConfig)
                .where(models.MapVetoConfig.tournament_id == tournament_id)
                .options(selectinload(models.MapVetoConfig.map_pool))
            )
            if body.stage_id is None:
                existing_query = existing_query.where(models.MapVetoConfig.stage_id.is_(None))
            else:
                existing_query = existing_query.where(models.MapVetoConfig.stage_id == body.stage_id)
            if body.round is None:
                existing_query = existing_query.where(models.MapVetoConfig.round.is_(None))
            else:
                existing_query = existing_query.where(models.MapVetoConfig.round == body.round)
            config = await session.scalar(existing_query)

            if config is None:
                config = models.MapVetoConfig(
                    tournament_id=tournament_id,
                    stage_id=body.stage_id,
                    round=body.round,
                    preset=body.preset,
                    turn_timer_seconds=body.turn_timer_seconds,
                    veto_sequence_json=body.sequence,
                )
                session.add(config)
            else:
                config.preset = body.preset
                config.turn_timer_seconds = body.turn_timer_seconds
                config.veto_sequence_json = body.sequence
            # Full pool replace preserving order as sort_order (delete-orphan cascade).
            config.map_pool = [
                models.MapVetoConfigMap(map_id=map_id, sort_order=idx) for idx, map_id in enumerate(body.map_ids)
            ]
            await session.commit()
            await session.refresh(config, ["map_pool"])
            return _serialize_config(config)

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.admin_veto_config_delete")
    async def _admin_veto_config_delete(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            config_id = _require_id(data)
            config = await session.scalar(select(models.MapVetoConfig).where(models.MapVetoConfig.id == config_id))
            if config is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Veto config not found")
            ws_id = await auth.get_tournament_workspace_id(session, config.tournament_id)
            ensure_workspace_permission(user, ws_id, "match", "update")
            await session.delete(config)
            await session.commit()
            return {"deleted": True}

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.admin_veto_session_reset")
    async def _admin_veto_session_reset(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            encounter_id = _require_id(data)
            ws_id = await auth.get_encounter_workspace_id(session, encounter_id)
            ensure_workspace_permission(user, ws_id, "match", "update")
            encounter = await _load_encounter(session, encounter_id)
            # reset_veto_session commits internally; the response is the same
            # state shape the room polls (viewer_side stays null for admins).
            await veto_session_service.reset_veto_session(session, encounter)
            return await map_veto_service.get_map_pool_state(session, encounter_id, viewer_side=None)

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.admin_veto_act")
    async def _admin_veto_act(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            encounter_id = _require_id(data)
            ws_id = await auth.get_encounter_workspace_id(session, encounter_id)
            ensure_workspace_permission(user, ws_id, "match", "update")
            body = AdminVetoAct.model_validate(_payload(data))
            # Same engine as captain_veto, side supplied explicitly (bypasses
            # captain-side resolution); perform_veto_action commits internally.
            entry = await map_veto_service.perform_veto_action(
                session,
                encounter_id,
                body.side,
                body.map_id,
                body.action,
            )
            return {
                "id": entry.id,
                "map_id": entry.map_id,
                "status": entry.status,
                "picked_by": entry.picked_by,
            }

        return await _run(logger, op)
