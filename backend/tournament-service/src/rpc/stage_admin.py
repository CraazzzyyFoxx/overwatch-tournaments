"""Stage WORKFLOW admin methods over typed RPC.

Each handler mirrors a workflow route in ``src/routes/admin/stage.py`` exactly:
it rehydrates the gateway-injected identity, runs the SAME imperative permission
check the route's dependency performed, validates the SAME body schema, calls the
SAME service function with the SAME args, and serializes the SAME way the route
returned (admin routes do NOT use ``response_model_exclude_none`` -> plain
``model_dump(mode="json")``; the custom dict/list-returning progress route and the
job-returning routes return their payloads as the route did).

Scope: ONLY the stage workflow endpoints (progress, merge-group-stages, activate,
generate, activate-and-generate, auto-wire, wire-from-groups, seed-teams). Stage /
stage_item / stage_item_input CRUD create/update/delete go through the generic CRUD
engine and are handled separately.

The gateway passes path params as ``data["<name>"]`` (and the primary id as
``data["id"]`` when the RouteSpec sets IDParam), query params as
``data["query"][key] = [values]``, and the JSON body as ``data["payload"]``.

Commit semantics:
- ``get_stage_progress`` is read-only.
- ``merge_group_stages``, ``seed_teams``, ``wire_from_groups`` commit internally.
- ``activate_stage`` commits internally (``commit=True`` default; route calls it
  plainly).
- ``request_bracket_job`` (generate / activate-and-generate) does NOT commit —
  ``create_job`` only flushes and enqueues an outbox event, so the route adds an
  explicit ``await session.commit()``; these handlers replicate that.
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit.annotations import RabbitMessage

from shared.rpc.identity import ensure_workspace_permission
from shared.services.audit import record_admin_audit
from shared.services.tournament.computation import request_bracket_job
from src import schemas
from src.core import auth
from src.rpc._helpers import _dump, _identity, _path_int, _payload, _run
from src.services.admin.stage import stage_service
from src.services.tournament.flows import flows_service as tournament_flows

# --- helpers -----------------------------------------------------------------


def register(broker: Any, logger: Any) -> None:
    # ── progress (read-only) ──────────────────────────────────────────────

    @broker.subscriber("rpc.tournament.stage_progress")
    async def _stage_progress(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _path_int(data, "tournament_id")
            # Route: require_tournament_permission("stage", "read").
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
            # Route: require_stage_permission("stage", "read").
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
            # Route: require_stage_permission("stage", "read").
            ws_id = await auth.get_stage_workspace_id(session, stage_id)
            ensure_workspace_permission(user, ws_id, "stage", "read")
            return await stage_service.get_bracket_preview(session, stage_id)

        return await _run(logger, op)

    # ── merge group stages ────────────────────────────────────────────────

    @broker.subscriber("rpc.tournament.stage_merge")
    async def _stage_merge(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            stage_id = _path_int(data, "stage_id")
            # Route: require_stage_permission("stage", "update").
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

    # ── activate ──────────────────────────────────────────────────────────

    @broker.subscriber("rpc.tournament.stage_activate")
    async def _stage_activate(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            stage_id = _path_int(data, "stage_id")
            # Route: require_stage_permission("stage", "update").
            ws_id = await auth.get_stage_workspace_id(session, stage_id)
            ensure_workspace_permission(user, ws_id, "stage", "update")
            await record_admin_audit(
                session,
                action="stage.activate",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="stage",
                entity_id=stage_id,
            )
            # activate_stage commits internally (commit=True default).
            stage = await stage_service.activate_stage(session, stage_id)
            return _dump(await tournament_flows.stage_read(session, stage))

        return await _run(logger, op)

    # ── deactivate (revert an accidental activation back to Draft) ────────

    @broker.subscriber("rpc.tournament.stage_deactivate")
    async def _stage_deactivate(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            stage_id = _path_int(data, "stage_id")
            # Route: require_stage_permission("stage", "update").
            ws_id = await auth.get_stage_workspace_id(session, stage_id)
            ensure_workspace_permission(user, ws_id, "stage", "update")
            await record_admin_audit(
                session,
                action="stage.deactivate",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="stage",
                entity_id=stage_id,
            )
            # deactivate_stage commits internally (commit=True default); 409s
            # if any of the stage's encounters left OPEN.
            stage = await stage_service.deactivate_stage(session, stage_id)
            return _dump(await tournament_flows.stage_read(session, stage))

        return await _run(logger, op)

    # ── generate (202; enqueues bracket job) ──────────────────────────────

    @broker.subscriber("rpc.tournament.stage_generate")
    async def _stage_generate(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            stage_id = _path_int(data, "stage_id")
            # Route: require_stage_permission("stage", "update").
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
            # Route: require_stage_permission("stage", "update").
            ws_id = await auth.get_stage_workspace_id(session, stage_id)
            ensure_workspace_permission(user, ws_id, "stage", "update")
            # Rewrites best_of on the stage's encounters from settings_json;
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
                after={"best_of": (stage.settings_json or {}).get("best_of")},
            )
            updated = await stage_service.apply_best_of_to_existing(session, stage_id)
            return {"updated": updated}

        return await _run(logger, op)

    # ── activate-and-generate (202; force flag) ───────────────────────────

    @broker.subscriber("rpc.tournament.stage_activate_and_generate")
    async def _stage_activate_and_generate(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            stage_id = _path_int(data, "stage_id")
            # Route: require_stage_permission("stage", "update").
            ws_id = await auth.get_stage_workspace_id(session, stage_id)
            ensure_workspace_permission(user, ws_id, "stage", "update")
            # Route reads ``force`` from the query string (bool, default False).
            force_vals = (data.get("query") or {}).get("force")
            if isinstance(force_vals, list):
                force_raw = force_vals[0] if force_vals else None
            else:
                force_raw = force_vals
            force = str(force_raw).lower() in ("1", "true", "yes", "on") if force_raw is not None else False

            await record_admin_audit(
                session,
                action="stage.activate_and_generate",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="stage",
                entity_id=stage_id,
                after={"force": force},
            )

            tournament_id = await stage_service.get_tournament_id(session, stage_id)
            job = await request_bracket_job(
                session,
                tournament_id=tournament_id,
                stage_id=stage_id,
                operation="activate_and_generate",
                payload={"force": force},
                requested_by_user_id=int(user.id),
            )
            await session.commit()
            return _dump(schemas.TournamentComputationJobRead.model_validate(job, from_attributes=True))

        return await _run(logger, op)

    # ── auto-wire (standalone trigger for the Activate & generate auto-wire) ──

    @broker.subscriber("rpc.tournament.stage_auto_wire")
    async def _stage_auto_wire(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            stage_id = _path_int(data, "stage_id")
            # Route: require_stage_permission("stage", "update").
            ws_id = await auth.get_stage_workspace_id(session, stage_id)
            ensure_workspace_permission(user, ws_id, "stage", "update")
            await record_admin_audit(
                session,
                action="stage.auto_wire",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="stage",
                entity_id=stage_id,
            )
            # auto_wire_stage commits internally; returns a Stage.
            stage = await stage_service.auto_wire_stage(session, stage_id)
            return _dump(await tournament_flows.stage_read(session, stage))

        return await _run(logger, op)

    # ── wire from groups ──────────────────────────────────────────────────

    @broker.subscriber("rpc.tournament.stage_wire")
    async def _stage_wire(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            stage_id = _path_int(data, "stage_id")
            # Route: require_stage_permission("stage", "update").
            ws_id = await auth.get_stage_workspace_id(session, stage_id)
            ensure_workspace_permission(user, ws_id, "stage", "update")
            body = schemas.WireFromGroupsRequest.model_validate(_payload(data))
            await record_admin_audit(
                session,
                action="stage.wire",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="stage",
                entity_id=stage_id,
                after={
                    "source_stage_id": body.source_stage_id,
                    "top": body.top,
                    "top_lb": body.top_lb,
                    "mode": body.mode,
                },
            )
            # wire_from_groups commits internally; returns a Stage.
            stage = await stage_service.wire_from_groups(
                session,
                target_stage_id=stage_id,
                source_stage_id=body.source_stage_id,
                top=body.top,
                top_lb=body.top_lb,
                mode=body.mode,
            )
            return _dump(await tournament_flows.stage_read(session, stage))

        return await _run(logger, op)

    # ── seed teams ────────────────────────────────────────────────────────

    @broker.subscriber("rpc.tournament.stage_seed")
    async def _stage_seed(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            stage_id = _path_int(data, "stage_id")
            # Route: require_stage_permission("stage", "update").
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
