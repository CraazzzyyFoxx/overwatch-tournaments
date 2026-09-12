"""Generic pick-ban admin methods over typed RPC (``PickBanConfig`` CRUD for
both ``map`` and ``hero`` kinds).

Mirrors ``veto_admin.py``'s FORMER upsert/list/delete shape exactly — same
cascade key ``(tournament_id, stage_id, round)``, now additionally
partitioned by ``kind`` (design: docs/plans/2026-08-09-generic-pickban-engine.md)
— plus a ``kind`` field on every route so one admin surface configures both
map veto and hero bans. Since the map-veto cutover, this IS the sole config
CRUD surface for both kinds; ``veto_admin.py`` keeps only the two
live-session operations (reset/act) that have no pick-ban equivalent.
"""

from __future__ import annotations

from typing import Any, Literal

from faststream.rabbit.annotations import RabbitMessage
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from shared.core import http_status as status
from shared.core.enums import (
    FirstBanRotation,
    FirstPickRule,
    MapVetoMode,
    PickBanKind,
    PickBanNoRepeatScope,
)
from shared.core.errors import BaseAPIException as HTTPException
from shared.models.tournament.pick_ban import (
    PickBanConfig,
    PickBanConfigSlot,
)
from shared.rpc.identity import ensure_workspace_permission
from shared.services.audit import record_admin_audit
from src import models
from src.core import auth
from src.rpc._helpers import _identity, _payload, _require_id, _run
from src.services.encounter import pick_ban_action as pick_ban_action
from src.services.encounter import pick_ban_config
from src.services.encounter import pick_ban_session as pick_ban_session

_CONFIG_LOAD = (
    selectinload(PickBanConfig.items),
    selectinload(PickBanConfig.slots).selectinload(PickBanConfigSlot.items),
)
_serialize_config = pick_ban_session.serialize_pick_ban_config


async def _load_encounter(session: Any, encounter_id: int) -> models.Encounter:
    encounter = await session.scalar(select(models.Encounter).where(models.Encounter.id == encounter_id))
    if encounter is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encounter not found")
    return encounter


class PickBanAdminReset(BaseModel):
    """Body for the admin session-reset route -- which kind's live session to
    drop and re-create (map veto and hero bans reset independently)."""

    kind: PickBanKind


class PickBanAdminAct(BaseModel):
    """Body for the admin act-for-a-side route: perform one step on behalf of
    an absent captain. Generalizes ``veto_admin.AdminVetoAct`` with ``kind``
    and the ``protect`` action the generic engine adds."""

    kind: PickBanKind
    side: Literal["home", "away"]
    item_id: int
    action: Literal["pick", "ban", "protect"]


class PickBanAdminElectOpener(BaseModel):
    """Body for the admin elect-opener route: name who opens the round a
    ``result_loser_choice`` rotation is holding, on behalf of a losing captain
    who is not there to name it themselves."""

    kind: PickBanKind
    first_side: Literal["home", "away"]


class PickBanConfigSlotUpsert(BaseModel):
    """One slot of a slot-mode upsert body. No ``position``: list order IS the
    play order (same rationale as ``veto_admin.VetoConfigSlotUpsert``)."""

    candidates: list[int]
    reserve_item_id: int | None = None


class PickBanConfigUpsert(BaseModel):
    """Body for the generic pick-ban config upsert route."""

    kind: PickBanKind
    stage_id: int | None = None
    round: int | None = None
    mode: MapVetoMode
    first_pick_rule: FirstPickRule = FirstPickRule.HIGHER_SEED
    first_ban_rotation: FirstBanRotation = FirstBanRotation.FIXED
    preset: str | None = Field(default=None, max_length=32)
    turn_timer_seconds: int | None = Field(default=None, ge=1)
    no_repeat_scope: PickBanNoRepeatScope = PickBanNoRepeatScope.NONE
    unique_attribute_per_side_per_round: str | None = Field(default=None, max_length=32)
    allow_protect: bool = False
    sequence: list[str] = Field(default_factory=list)
    item_ids: list[int] = Field(default_factory=list)
    slots: list[PickBanConfigSlotUpsert] = Field(default_factory=list)


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.tournament.admin_pick_ban_config_list")
    async def _admin_pick_ban_config_list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            ws_id = await auth.get_tournament_workspace_id(session, tournament_id)
            ensure_workspace_permission(user, ws_id, "match", "update")
            configs = await pick_ban_config.pick_ban_config_service.list_configs(session, tournament_id=tournament_id)
            return {"configs": [_serialize_config(config) for config in configs]}

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.admin_pick_ban_config_upsert")
    async def _admin_pick_ban_config_upsert(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            ws_id = await auth.get_tournament_workspace_id(session, tournament_id)
            ensure_workspace_permission(user, ws_id, "match", "update")
            body = PickBanConfigUpsert.model_validate(_payload(data))
            pick_ban_session.validate_pick_ban_upsert(
                mode=body.mode,
                preset=body.preset,
                kind=body.kind,
                sequence=body.sequence,
                item_ids=body.item_ids,
                slots=[(slot.candidates, slot.reserve_item_id) for slot in body.slots],
                stage_id=body.stage_id,
                round=body.round,
            )
            config = await pick_ban_config.pick_ban_config_service.upsert_config(
                session,
                tournament_id=tournament_id,
                kind=body.kind,
                stage_id=body.stage_id,
                round=body.round,
                mode=body.mode,
                first_pick_rule=body.first_pick_rule,
                first_ban_rotation=body.first_ban_rotation,
                preset=body.preset,
                turn_timer_seconds=body.turn_timer_seconds,
                no_repeat_scope=body.no_repeat_scope,
                unique_attribute_per_side_per_round=body.unique_attribute_per_side_per_round,
                allow_protect=body.allow_protect,
                sequence=body.sequence,
                item_ids=body.item_ids,
                slots=[
                    pick_ban_config.SlotSpec(candidates=list(slot.candidates), reserve_item_id=slot.reserve_item_id)
                    for slot in body.slots
                ],
            )
            await record_admin_audit(
                session,
                action="pick_ban.config_upsert",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="tournament",
                entity_id=tournament_id,
                after={
                    "config_id": config.id,
                    "kind": body.kind,
                    "stage_id": body.stage_id,
                    "round": body.round,
                    "mode": body.mode,
                    "first_pick_rule": body.first_pick_rule,
                    "first_ban_rotation": body.first_ban_rotation,
                    "preset": body.preset,
                    "turn_timer_seconds": body.turn_timer_seconds,
                    "no_repeat_scope": body.no_repeat_scope,
                    "unique_attribute_per_side_per_round": body.unique_attribute_per_side_per_round,
                    "allow_protect": body.allow_protect,
                    # Counts, not the pools themselves: a slots-mode config can
                    # carry hundreds of candidate ids and the journal is not a
                    # config store.
                    "sequence_length": len(body.sequence),
                    "item_count": len(body.item_ids),
                    "slot_count": len(body.slots),
                },
            )
            payload = _serialize_config(config)
            await session.commit()
            return payload

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.admin_pick_ban_config_delete")
    async def _admin_pick_ban_config_delete(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            config_id = _require_id(data)
            config = await pick_ban_config.pick_ban_config_service.get_config(session, config_id)
            ws_id = await auth.get_tournament_workspace_id(session, config.tournament_id)
            ensure_workspace_permission(user, ws_id, "match", "update")
            # Staged before the delete so ``config``'s scope fields are still
            # loadable off a live row.
            await record_admin_audit(
                session,
                action="pick_ban.config_delete",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="tournament",
                entity_id=config.tournament_id,
                before={
                    "config_id": config.id,
                    "kind": config.kind,
                    "stage_id": config.stage_id,
                    "round": config.round,
                    "mode": config.mode,
                },
            )
            await pick_ban_config.pick_ban_config_service.delete_config(session, config_id)
            await session.commit()
            return {"deleted": True}

        return await _run(logger, op)

    # ── live-session admin overrides (map + hero) ───────────────────────────
    # Generalizes veto_admin.py's two live-session operations (reset + act
    # for an absent captain), which had no pick-ban equivalent before the
    # room unification. Both kinds share these two routes via a ``kind``
    # body field instead of two kind-hardcoded handlers.

    @broker.subscriber("rpc.tournament.admin_pick_ban_session_reset")
    async def _admin_pick_ban_session_reset(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            encounter_id = _require_id(data)
            ws_id = await auth.get_encounter_workspace_id(session, encounter_id)
            ensure_workspace_permission(user, ws_id, "match", "update")
            body = PickBanAdminReset.model_validate(_payload(data))
            encounter = await _load_encounter(session, encounter_id)
            await record_admin_audit(
                session,
                action="pick_ban.session_reset",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="encounter",
                entity_id=encounter.id,
                after={"kind": body.kind},
            )
            # reset_pick_ban_session commits internally; the response is the
            # same state shape the room polls (viewer_side stays null for
            # admins).
            await pick_ban_session.pick_ban_session_service.reset_pick_ban_session(session, encounter, body.kind)
            return await pick_ban_action.pick_ban_action_service.get_pick_ban_state(
                session, encounter_id, body.kind, viewer_side=None
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.admin_pick_ban_act")
    async def _admin_pick_ban_act(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            encounter_id = _require_id(data)
            ws_id = await auth.get_encounter_workspace_id(session, encounter_id)
            ensure_workspace_permission(user, ws_id, "match", "update")
            body = PickBanAdminAct.model_validate(_payload(data))
            await record_admin_audit(
                session,
                action="pick_ban.act",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="encounter",
                entity_id=encounter_id,
                after={
                    "kind": body.kind,
                    "side": body.side,
                    "action": body.action,
                    "item_id": body.item_id,
                },
            )
            # Same engine as the captain act route, side supplied explicitly
            # (bypasses captain-side resolution); commits internally.
            entry = await pick_ban_action.pick_ban_action_service.perform_pick_ban_action(
                session,
                encounter_id,
                body.kind,
                body.side,
                body.item_id,
                body.action,
            )
            return pick_ban_action.serialize_pick_ban_entry(entry)

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.admin_pick_ban_elect_opener")
    async def _admin_pick_ban_elect_opener(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            encounter_id = _require_id(data)
            ws_id = await auth.get_encounter_workspace_id(session, encounter_id)
            ensure_workspace_permission(user, ws_id, "match", "update")
            body = PickBanAdminElectOpener.model_validate(_payload(data))
            pick_ban = await pick_ban_session.pick_ban_session_service.get_pick_ban_session(
                session, encounter_id, body.kind
            )
            if pick_ban is None:
                raise HTTPException(status_code=400, detail="No round is awaiting an opener choice")
            await record_admin_audit(
                session,
                action="pick_ban.elect_opener",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="encounter",
                entity_id=encounter_id,
                after={"kind": body.kind, "first_side": body.first_side},
            )
            # `acting_side=None` IS the override: the losing captain's exclusive
            # right to choose does not apply to an organizer unsticking a room
            # they are not playing in. Commits inside `advance_to_next_round`;
            # the response is the state shape the room polls.
            await pick_ban_session.pick_ban_session_service.elect_round_opener(
                session, pick_ban, first_side=body.first_side, acting_side=None
            )
            return await pick_ban_action.pick_ban_action_service.get_pick_ban_state(
                session, encounter_id, body.kind, viewer_side=None
            )

        return await _run(logger, op)
