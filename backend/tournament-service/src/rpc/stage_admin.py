"""Stage WORKFLOW admin methods over typed RPC.

Scope: ONLY the stage workflow endpoints (progress, merge-group-stages,
generate, seed-teams,
bracket-template read/save/reset). A stage's lifecycle is its flow node: ``rpc.tournament.flow_node_transition``. Stage /
stage_item / stage_item_input CRUD create/update/delete go through the generic CRUD
engine and are handled separately.

Responses are plain ``model_dump(mode="json")``; the progress read and the
job-returning subjects return their payloads as-is.

The gateway passes path params as ``data["<name>"]`` (and the primary id as
``data["id"]`` when the RouteSpec sets IDParam), query params as
``data["query"][key] = [values]``, and the JSON body as ``data["payload"]``.

Commit semantics:
- ``get_stage_progress`` is read-only.
- ``merge_group_stages``, ``seed_teams``,
  ``set_bracket_template``, ``clear_bracket_template`` commit internally.
- ``request_bracket_job`` (generate) does NOT commit —
  ``create_job`` only flushes and enqueues an outbox event, so the handler
  ``await session.commit()`` explicitly.
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit.annotations import RabbitMessage

from shared import models
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.rpc.identity import ensure_workspace_permission
from shared.services.audit import record_admin_audit
from shared.services.tournament.computation import request_bracket_job
from src import schemas
from src.core import auth
from src.domain.bracket import BracketTemplate
from src.rpc._helpers import _dump, _identity, _path_int, _payload, _require_id, _run
from src.schemas import individual_swiss as individual_swiss_schemas
from src.services.admin.stage import stage_service
from src.services.individual_swiss.pins import pins_service
from src.services.individual_swiss.qualification import qualification_service
from src.services.tournament.flows import flows_service as tournament_flows


async def _tournament_stage(
    session: Any, data: dict, user: Any, resource: str, action: str
) -> tuple[int, models.Stage]:
    """The path's stage, once the caller holds ``resource.action`` on its tournament's workspace.

    Permission first, so a stranger cannot tell a missing stage from a foreign one; a stage of another tournament
    is a 404 like a missing one.
    """
    tournament_id = _require_id(data)
    ws_id = await auth.get_tournament_workspace_id(session, tournament_id)
    ensure_workspace_permission(user, ws_id, resource, action)
    stage = await stage_service.get_stage(session, _path_int(data, "stage_id"))
    if stage.tournament_id != tournament_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stage not found")
    return ws_id, stage


def register(broker: Any, logger: Any) -> None:
    # ── progress (read-only) ──────────────────────────────────────────────

    @broker.subscriber("rpc.tournament.stage_progress")
    async def _stage_progress(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _path_int(data, "tournament_id")
            ws_id = await auth.get_tournament_workspace_id(session, tournament_id)
            ensure_workspace_permission(user, ws_id, "stage", "read")
            # get_stage_progress is read-only; returns a custom list[dict].
            return await stage_service.get_stage_progress(session, tournament_id)

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.stage_planned_rounds")
    async def _stage_planned_rounds(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            stage_id = _path_int(data, "stage_id")
            ws_id = await auth.get_stage_workspace_id(session, stage_id)
            ensure_workspace_permission(user, ws_id, "stage", "read")
            rounds = await stage_service.get_planned_rounds(session, stage_id)
            return {"rounds": rounds}

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.stage_bracket_preview")
    async def _stage_bracket_preview(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            stage_id = _path_int(data, "stage_id")
            ws_id = await auth.get_stage_workspace_id(session, stage_id)
            ensure_workspace_permission(user, ws_id, "stage", "read")
            return await stage_service.get_bracket_preview(session, stage_id)

        return await _run(logger, op)

    # ── bracket template (read / save / reset) ────────────────────────────

    @broker.subscriber("rpc.tournament.stage_bracket_template_get")
    async def _stage_bracket_template_get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            stage_id = _path_int(data, "stage_id")
            ws_id = await auth.get_stage_workspace_id(session, stage_id)
            ensure_workspace_permission(user, ws_id, "stage", "read")
            return await stage_service.get_bracket_template(session, stage_id)

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.stage_bracket_template_set")
    async def _stage_bracket_template_set(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            stage_id = _path_int(data, "stage_id")
            ws_id = await auth.get_stage_workspace_id(session, stage_id)
            ensure_workspace_permission(user, ws_id, "stage", "update")
            body = BracketTemplate.model_validate(_payload(data))
            await record_admin_audit(
                session,
                action="stage.bracket_template.set",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="stage",
                entity_id=stage_id,
                after={
                    "upper_seeds": body.upper_seeds,
                    "lower_seeds": body.lower_seeds,
                    "matches": len(body.matches),
                },
            )
            # set_bracket_template commits internally; the audit row is staged
            # first, so a refused write (409/422) leaves no row behind.
            return await stage_service.set_bracket_template(session, stage_id, body)

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.stage_bracket_template_clear")
    async def _stage_bracket_template_clear(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            stage_id = _path_int(data, "stage_id")
            ws_id = await auth.get_stage_workspace_id(session, stage_id)
            ensure_workspace_permission(user, ws_id, "stage", "update")
            await record_admin_audit(
                session,
                action="stage.bracket_template.clear",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="stage",
                entity_id=stage_id,
                after={},
            )
            # clear_bracket_template commits internally.
            return await stage_service.clear_bracket_template(session, stage_id)

        return await _run(logger, op)

    # ── merge group stages ────────────────────────────────────────────────

    @broker.subscriber("rpc.tournament.stage_merge")
    async def _stage_merge(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            stage_id = _path_int(data, "stage_id")
            ws_id = await auth.get_stage_workspace_id(session, stage_id)
            ensure_workspace_permission(user, ws_id, "stage", "update")
            body = schemas.MergeGroupStagesRequest.model_validate(_payload(data))
            await record_admin_audit(
                session,
                action="stage.merge",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="stage",
                entity_id=stage_id,
                after={
                    "source_stage_ids": body.source_stage_ids,
                    "target_stage_id": stage_id,
                    "target_name": body.target_name,
                },
            )
            # merge_group_stages commits internally; returns a Stage.
            stage = await stage_service.merge_group_stages(
                session,
                target_stage_id=stage_id,
                source_stage_ids=body.source_stage_ids,
                target_name=body.target_name,
            )
            return _dump(await tournament_flows.stage_read(session, stage))

        return await _run(logger, op)

    # ── generate (202; enqueues bracket job) ──────────────────────────────

    @broker.subscriber("rpc.tournament.stage_generate")
    async def _stage_generate(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            stage_id = _path_int(data, "stage_id")
            ws_id = await auth.get_stage_workspace_id(session, stage_id)
            ensure_workspace_permission(user, ws_id, "stage", "update")
            await record_admin_audit(
                session,
                action="stage.generate",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="stage",
                entity_id=stage_id,
            )
            tournament_id = await stage_service.get_tournament_id(session, stage_id)
            job = await request_bracket_job(
                session,
                tournament_id=tournament_id,
                stage_id=stage_id,
                operation="generate_stage",
                requested_by_user_id=int(user.id),
            )
            await session.commit()
            return _dump(schemas.TournamentComputationJobRead.model_validate(job, from_attributes=True))

        return await _run(logger, op)

    # ── apply best-of to existing encounters (backfill) ───────────────────

    @broker.subscriber("rpc.tournament.stage_apply_best_of")
    async def _stage_apply_best_of(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            stage_id = _path_int(data, "stage_id")
            ws_id = await auth.get_stage_workspace_id(session, stage_id)
            ensure_workspace_permission(user, ws_id, "stage", "update")
            # Rewrites best_of on the stage's encounters from its best-of config;
            # commits internally. Returns the number of rows changed.
            stage = await stage_service.get_stage(session, stage_id)
            await record_admin_audit(
                session,
                action="stage.apply_best_of",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="stage",
                entity_id=stage_id,
                entity_label=stage.name,
                after={"best_of": schemas.StageBestOf.model_validate(stage.best_of).model_dump(mode="json")},
            )
            updated = await stage_service.apply_best_of_to_existing(session, stage_id)
            return {"updated": updated}

        return await _run(logger, op)

    # ── seed teams ────────────────────────────────────────────────────────

    @broker.subscriber("rpc.tournament.stage_seed")
    async def _stage_seed(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            stage_id = _path_int(data, "stage_id")
            ws_id = await auth.get_stage_workspace_id(session, stage_id)
            ensure_workspace_permission(user, ws_id, "stage", "update")
            body = schemas.SeedTeamsRequest.model_validate(_payload(data))
            await record_admin_audit(
                session,
                action="stage.seed",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="stage",
                entity_id=stage_id,
                after={"team_count": len(body.team_ids), "mode": body.mode},
            )
            # seed_teams commits internally; returns a Stage.
            stage = await stage_service.seed_teams(
                session,
                stage_id=stage_id,
                team_ids=body.team_ids,
                mode=body.mode,
            )
            return _dump(await tournament_flows.stage_read(session, stage))

        return await _run(logger, op)

    # ── individual swiss: player-standing pins and the qualification lock ──

    @broker.subscriber("rpc.tournament.player_standing_pins_set")
    async def _player_standing_pins_set(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            ws_id, stage = await _tournament_stage(session, data, user, "standing", "update")
            body = individual_swiss_schemas.PlayerStandingPinsUpdate.model_validate(_payload(data))
            before = await pins_service.get_pins(session, stage.id)
            await record_admin_audit(
                session,
                action="standing.player_pins_set",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="stage",
                entity_id=stage.id,
                entity_label=stage.name,
                before={"pins": before},
                after={"pins": {pin.workspace_member_id: pin.position for pin in body.pins}},
            )
            # set_pins commits (the audit row with it); a refused write leaves no row behind.
            return _dump(await pins_service.set_pins(session, stage, body, requested_by_user_id=int(user.id)))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.individual_swiss_lock_qualification")
    async def _individual_swiss_lock_qualification(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            ws_id, stage = await _tournament_stage(session, data, user, "stage", "update")
            # The lock moves the tournament's status and trims its balancer pool: both need their own permission.
            ensure_workspace_permission(user, ws_id, "tournament", "update")
            await record_admin_audit(
                session,
                action="stage.lock_qualification",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="stage",
                entity_id=stage.id,
                entity_label=stage.name,
                after={},
            )
            # lock commits internally, the audit row with the first commit.
            return _dump(await qualification_service.lock(session, stage, actor_user_id=int(user.id)))

        return await _run(logger, op)
