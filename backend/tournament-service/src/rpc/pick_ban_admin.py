"""Generic pick-ban admin methods over typed RPC (``PickBanConfig`` CRUD for
both ``map`` and ``hero`` kinds, plus the live-session organizer overrides).

Mirrors ``veto_admin.py``'s FORMER upsert/list/delete shape exactly — same
cascade key ``(tournament_id, stage_id, round)``, now additionally
partitioned by ``kind`` (design: docs/plans/2026-08-09-generic-pickban-engine.md)
— plus a ``kind`` field on every route so one admin surface configures both
map veto and hero bans. Since the map-veto cutover, this IS the sole config
CRUD surface for both kinds.

Ruleset v2 (docs/plans/2026-09-28-pick-ban-constructor.md) replaced the flat
token sequence with a rules DOCUMENT, so this module also carries the two
constructor-support ops — ``rules_validate`` and ``rules_preview`` — which
answer "would this save?" and "what would a Bo5 look like?" without writing
anything. They are gated exactly like the upsert they precede: an organizer
who may not save a config may not probe the engine with one either.
"""

from __future__ import annotations

from typing import Any, Literal

from faststream.rabbit.annotations import RabbitMessage
from pydantic import BaseModel, Field
from sqlalchemy import select

from shared.core import http_status as status
from shared.core.enums import (
    FirstBanRotation,
    FirstPickRule,
    MapVetoMode,
    PickBanKind,
)
from shared.core.errors import BaseAPIException as HTTPException
from shared.domain import pick_ban_rules as pbr
from shared.rpc.identity import ensure_workspace_permission
from shared.services.audit import record_admin_audit
from src import models
from src.core import auth
from src.rpc._helpers import _identity, _path_int, _payload, _require_id, _run
from src.schemas import captain as captain_schemas
from src.services.encounter import pick_ban_action as pick_ban_action
from src.services.encounter import pick_ban_config
from src.services.encounter import pick_ban_session as pick_ban_session
from src.services.encounter.game_correction import game_correction_service

_serialize_config = pick_ban_config.serialize_pick_ban_config


async def _load_encounter(session: Any, encounter_id: int) -> models.Encounter:
    """Load the encounter under ``FOR UPDATE``.

    Every admin handler here mutates the live session or a game result, and the
    game-result path re-derives the encounter score from its games -- so it takes
    the same Encounter -> Game lock order the captain path uses (spec §7). Without
    it a concurrent captain claim and an admin correction can each materialise a
    score from a stale read. ``populate_existing`` rides along: a row already in
    the identity map would otherwise be served at the version this session first
    saw, defeating the lock.
    """
    encounter = await session.scalar(
        select(models.Encounter)
        .where(models.Encounter.id == encounter_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if encounter is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encounter not found")
    return encounter


class PickBanAdminReset(BaseModel):
    """Body for the admin session-reset route -- which kind's live session to
    drop and re-create (map veto and hero bans reset independently)."""

    kind: PickBanKind


class PickBanAdminAct(BaseModel):
    """Body for the admin act-for-a-side route: perform one step on behalf of
    an absent captain. ``target_player_id`` names the opponent roster player a
    per-player ban is spent on (ruleset v2 target steps); ``null`` everywhere
    else."""

    kind: PickBanKind
    side: Literal["home", "away"]
    item_id: int
    action: Literal["pick", "ban", "protect"]
    target_player_id: int | None = None


class PickBanAdminSubmit(BaseModel):
    """Body for the admin submit-for-a-side route: replace a BLIND step's draft
    on behalf of a captain who is not there to author it. Items reuse the
    captain schema so the two surfaces cannot drift."""

    kind: PickBanKind
    side: Literal["home", "away"]
    items: list[captain_schemas.PickBanSubmissionItemInput] = Field(default_factory=list)
    lock: bool = False


class PickBanAdminReopen(BaseModel):
    """Body for the admin reopen route: re-open the last revealed step for a
    fresh attempt. The organizer's version of a captain dispute -- no attempt
    budget, no ``dispute.enabled`` requirement."""

    kind: PickBanKind


class PickBanAdminElectOpener(BaseModel):
    """Body for the admin elect-opener route: name who opens the round a
    ``result_loser_choice`` rotation is holding, on behalf of a losing captain
    who is not there to name it themselves."""

    kind: PickBanKind
    first_side: Literal["home", "away"]


class AdminGameResultInput(BaseModel):
    """Body for the admin game-result correction: the position's score as the
    organizer decides it, plus the reason that goes into the audit journal (a
    correction is never anonymous -- spec §6.5)."""

    home_score: int = Field(ge=0)
    away_score: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=500)


class PickBanConfigSlotUpsert(BaseModel):
    """One slot of a slot-mode upsert body. No ``position``: list order IS the
    play order (same rationale as ``veto_admin.VetoConfigSlotUpsert``)."""

    candidates: list[int]
    reserve_item_id: int | None = None


class PickBanConfigUpsert(BaseModel):
    """Body for the generic pick-ban config upsert route (ruleset v2)."""

    kind: PickBanKind
    stage_id: int | None = None
    round: int | None = None
    mode: MapVetoMode
    first_pick_rule: FirstPickRule = FirstPickRule.HIGHER_SEED
    first_ban_rotation: FirstBanRotation = FirstBanRotation.FIXED
    ruleset: dict[str, Any]
    item_ids: list[int] = Field(default_factory=list)
    slots: list[PickBanConfigSlotUpsert] = Field(default_factory=list)


class PickBanRulesValidateInput(BaseModel):
    """Body for the constructor's live validation: a ruleset in the shape it
    would be saved at, without the pool or the cascade coordinates."""

    kind: PickBanKind
    mode: MapVetoMode = MapVetoMode.POOL
    ruleset: dict[str, Any]


class PickBanRulesPreviewInput(PickBanRulesValidateInput):
    """Body for the constructor's series preview: the rules plus the pool they
    would be played out of, since "how many supports survive map 5" is only
    answerable against real items."""

    best_of: int = Field(default=3, ge=1, le=9)
    item_ids: list[int] = Field(default_factory=list)
    slots: list[PickBanConfigSlotUpsert] = Field(default_factory=list)


def _pool_item_ids(mode: MapVetoMode, item_ids: list[int], slots: list[PickBanConfigSlotUpsert]) -> list[int]:
    """The items a preview may draw on, whichever mode authored them.

    Slot mode has no flat pool: its playable set is the union of every slot's
    candidates plus the reserves, deduplicated -- an item may sit in two slots.
    """
    if mode != MapVetoMode.SLOTS:
        return list(dict.fromkeys(item_ids))
    pooled: list[int] = []
    for slot in slots:
        pooled.extend(slot.candidates)
        if slot.reserve_item_id is not None:
            pooled.append(slot.reserve_item_id)
    return list(dict.fromkeys(pooled))


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
            pick_ban_config.validate_config_payload(
                kind=body.kind,
                mode=body.mode,
                ruleset=body.ruleset,
                item_ids=body.item_ids,
                slots=[(slot.candidates, slot.reserve_item_id) for slot in body.slots],
                stage_id=body.stage_id,
                round=body.round,
                groups=await pick_ban_config.group_vocabulary(session, body.kind),
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
                ruleset=body.ruleset,
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
                    # Counts, not the documents themselves: a ruleset is a tree
                    # and a slots-mode config can carry hundreds of candidate
                    # ids -- the journal is not a config store.
                    "phase_count": len(body.ruleset.get("phases") or []),
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

    # ── constructor support: validate + preview (no writes) ─────────────────

    @broker.subscriber("rpc.tournament.admin_pick_ban_rules_validate")
    async def _admin_pick_ban_rules_validate(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            ws_id = await auth.get_tournament_workspace_id(session, tournament_id)
            ensure_workspace_permission(user, ws_id, "match", "update")
            body = PickBanRulesValidateInput.model_validate(_payload(data))
            # Unlike the upsert this NEVER raises on a bad ruleset: the whole
            # point is to hand the editor the issue list while it is still being
            # typed. Warnings ride along with the errors; only errors decide
            # ``valid``.
            issues = pbr.validate_ruleset(
                body.ruleset,
                kind=body.kind.value,
                mode=body.mode.value,
                groups=await pick_ban_config.group_vocabulary(session, body.kind),
            )
            return {
                "valid": not any(issue.severity == "error" for issue in issues),
                "issues": [issue.to_json() for issue in issues],
            }

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.admin_pick_ban_rules_preview")
    async def _admin_pick_ban_rules_preview(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            ws_id = await auth.get_tournament_workspace_id(session, tournament_id)
            ensure_workspace_permission(user, ws_id, "match", "update")
            body = PickBanRulesPreviewInput.model_validate(_payload(data))
            return pbr.preview_series(
                body.ruleset,
                kind=body.kind.value,
                mode=body.mode.value,
                best_of=body.best_of,
                pool_groups=await pick_ban_config.pool_group_counts(
                    session, body.kind, _pool_item_ids(body.mode, body.item_ids, body.slots)
                ),
                # The tournament's own roster shape, not a workspace default:
                # it bounds how many of a per-player ban step's bans can land
                # on one role.
                roster_slots=await pick_ban_config.roster_slot_counts(session, tournament_id),
            )

        return await _run(logger, op)

    # ── live-session admin overrides (map + hero) ───────────────────────────
    # Generalizes veto_admin.py's two live-session operations (reset + act
    # for an absent captain), which had no pick-ban equivalent before the
    # room unification. Both kinds share these routes via a ``kind`` body
    # field instead of kind-hardcoded handlers.

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
                    "target_player_id": body.target_player_id,
                },
            )
            # Same engine as the captain act route, side supplied explicitly
            # (bypasses captain-side resolution); commits internally.
            # ``viewer_side=None``: an organizer sees the whole board, including
            # the other side's unrevealed draft, which a captain must not.
            return await pick_ban_action.pick_ban_action_service.perform_pick_ban_action(
                session,
                encounter_id,
                body.kind,
                body.side,
                item_id=body.item_id,
                action=body.action,
                target_player_id=body.target_player_id,
                viewer_side=None,
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.admin_pick_ban_submit")
    async def _admin_pick_ban_submit(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            encounter_id = _require_id(data)
            ws_id = await auth.get_encounter_workspace_id(session, encounter_id)
            ensure_workspace_permission(user, ws_id, "match", "update")
            body = PickBanAdminSubmit.model_validate(_payload(data))
            await record_admin_audit(
                session,
                action="pick_ban.submit",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="encounter",
                entity_id=encounter_id,
                after={
                    "kind": body.kind,
                    "side": body.side,
                    "lock": body.lock,
                    "item_ids": [item.item_id for item in body.items],
                },
            )
            return await pick_ban_action.pick_ban_action_service.submit_items(
                session,
                encounter_id,
                body.kind,
                body.side,
                items=[item.model_dump() for item in body.items],
                lock=body.lock,
                viewer_side=None,
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.admin_pick_ban_reopen")
    async def _admin_pick_ban_reopen(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            encounter_id = _require_id(data)
            ws_id = await auth.get_encounter_workspace_id(session, encounter_id)
            ensure_workspace_permission(user, ws_id, "match", "update")
            body = PickBanAdminReopen.model_validate(_payload(data))
            await record_admin_audit(
                session,
                action="pick_ban.reopen",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="encounter",
                entity_id=encounter_id,
                after={"kind": body.kind},
            )
            return await pick_ban_action.pick_ban_action_service.admin_reopen_step(session, encounter_id, body.kind)

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

    @broker.subscriber("rpc.tournament.admin_game_result")
    async def _admin_game_result(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            encounter_id = _require_id(data)
            ws_id = await auth.get_encounter_workspace_id(session, encounter_id)
            ensure_workspace_permission(user, ws_id, "match", "update")
            game_id = _path_int(data, "game_id")
            body = AdminGameResultInput.model_validate(_payload(data))
            encounter = await _load_encounter(session, encounter_id)
            await record_admin_audit(
                session,
                action="encounter.game_result",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="encounter",
                entity_id=encounter.id,
                after={
                    "game_id": game_id,
                    "home_score": body.home_score,
                    "away_score": body.away_score,
                    "reason": body.reason,
                },
            )
            # Commits internally (the accepted score, the live series score and
            # any rebuilt round land together).
            return await game_correction_service.correct(
                session,
                encounter,
                game_id=game_id,
                home_score=body.home_score,
                away_score=body.away_score,
                actor_user_id=user.id,
                reason=body.reason,
            )

        return await _run(logger, op)
