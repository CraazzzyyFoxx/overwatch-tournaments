"""Stage WORKFLOW admin methods over typed RPC.

Each handler mirrors a workflow route in ``src/routes/admin/stage.py`` exactly:
it rehydrates the gateway-injected identity, runs the SAME imperative permission
check the route's dependency performed, validates the SAME body schema, calls the
SAME service function with the SAME args, and serializes the SAME way the route
returned (admin routes do NOT use ``response_model_exclude_none`` -> plain
``model_dump(mode="json")``; the custom dict/list-returning progress route and the
job-returning routes return their payloads as the route did).

Scope: ONLY the stage workflow endpoints (progress, merge-group-stages, activate,
generate, activate-and-generate, wire-from-groups, seed-teams). Stage / stage_item
/ stage_item_input CRUD creates & updates go through the generic CRUD engine and
are handled separately.

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

from collections.abc import Awaitable, Callable
from typing import Any

from shared.core.errors import BaseAPIException as HTTPException
from faststream.rabbit.annotations import RabbitMessage
from pydantic import ValidationError

from shared.rpc.identity import MissingIdentityError, ensure_workspace_permission, rehydrate_user
from shared.schemas.rpc import rpc_error, rpc_ok, status_to_code

from src import models
from src.core import auth, db
from src.schemas.admin import stage as admin_schemas
from src.schemas.admin.computation import TournamentComputationJobRead
from src.services.admin import stage as stage_service
from src.services.computation import jobs as computation_jobs


# --- helpers -----------------------------------------------------------------


def _identity(data: dict[str, Any]) -> models.AuthUser:
    """Rehydrate the gateway-injected identity into a transient AuthUser."""
    return rehydrate_user(data.get("identity"))


def _payload(data: dict[str, Any]) -> dict[str, Any]:
    return data.get("payload") or {}


def _path_int(data: dict[str, Any], name: str) -> int:
    raw = data.get(name)
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"{name} is required") from exc


def _dump(obj: Any) -> Any:
    """Plain serialization (admin routes keep nulls — no exclude_none)."""
    if obj is None:
        return None
    if isinstance(obj, list):
        return [_dump(x) for x in obj]
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    return obj


async def _run(logger: Any, op: Callable[[Any], Awaitable[Any]]) -> dict[str, Any]:
    """Envelope wrapper mirroring admin_misc._run, with identity-failure mapping."""
    try:
        async with db.async_session_maker() as session:
            return rpc_ok(await op(session))
    except MissingIdentityError as exc:
        return rpc_error("unauthorized", str(exc) or "Not authenticated")
    except HTTPException as exc:
        return rpc_error(status_to_code(exc.status_code), str(exc.detail))
    except ValidationError as exc:
        return rpc_error("unprocessable", str(exc))
    except Exception:  # pragma: no cover - defensive worker guard
        logger.exception("tournament stage-admin rpc failed")
        return rpc_error("internal", "internal error")


def register(broker: Any, logger: Any) -> None:
    # ── progress (read-only) ──────────────────────────────────────────────

    @broker.subscriber("rpc.tournament.stage_progress")
    async def _stage_progress(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _path_int(data, "tournament_id")
            # Route: require_tournament_permission("stage", "read").
            ws_id = await auth._get_tournament_workspace_id(session, tournament_id)
            ensure_workspace_permission(user, ws_id, "stage", "read")
            # get_stage_progress is read-only; returns a custom list[dict].
            return await stage_service.get_stage_progress(session, tournament_id)

        return await _run(logger, op)

    # ── merge group stages ────────────────────────────────────────────────

    @broker.subscriber("rpc.tournament.stage_merge")
    async def _stage_merge(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            stage_id = _path_int(data, "stage_id")
            # Route: require_stage_permission("stage", "update").
            ws_id = await auth._get_stage_workspace_id(session, stage_id)
            ensure_workspace_permission(user, ws_id, "stage", "update")
            body = admin_schemas.MergeGroupStagesRequest.model_validate(_payload(data))
            # merge_group_stages commits internally; returns a Stage.
            stage = await stage_service.merge_group_stages(
                session,
                target_stage_id=stage_id,
                source_stage_ids=body.source_stage_ids,
                target_name=body.target_name,
            )
            from src import schemas  # noqa: PLC0415

            return _dump(schemas.StageRead.model_validate(stage, from_attributes=True))

        return await _run(logger, op)

    # ── activate ──────────────────────────────────────────────────────────

    @broker.subscriber("rpc.tournament.stage_activate")
    async def _stage_activate(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            stage_id = _path_int(data, "stage_id")
            # Route: require_stage_permission("stage", "update").
            ws_id = await auth._get_stage_workspace_id(session, stage_id)
            ensure_workspace_permission(user, ws_id, "stage", "update")
            # activate_stage commits internally (commit=True default).
            stage = await stage_service.activate_stage(session, stage_id)
            from src import schemas  # noqa: PLC0415

            return _dump(schemas.StageRead.model_validate(stage, from_attributes=True))

        return await _run(logger, op)

    # ── generate (202; enqueues bracket job) ──────────────────────────────

    @broker.subscriber("rpc.tournament.stage_generate")
    async def _stage_generate(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            stage_id = _path_int(data, "stage_id")
            # Route: require_stage_permission("stage", "update").
            ws_id = await auth._get_stage_workspace_id(session, stage_id)
            ensure_workspace_permission(user, ws_id, "stage", "update")
            # Route loads the stage to obtain tournament_id, then requests a
            # bracket job and commits explicitly (create_job does NOT commit).
            stage = await stage_service.get_stage(session, stage_id)
            job = await computation_jobs.request_bracket_job(
                session,
                tournament_id=stage.tournament_id,
                stage_id=stage.id,
                operation="generate_stage",
                requested_by_user_id=int(user.id),
            )
            await session.commit()
            return _dump(TournamentComputationJobRead.model_validate(job, from_attributes=True))

        return await _run(logger, op)

    # ── activate-and-generate (202; force flag) ───────────────────────────

    @broker.subscriber("rpc.tournament.stage_activate_and_generate")
    async def _stage_activate_and_generate(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            stage_id = _path_int(data, "stage_id")
            # Route: require_stage_permission("stage", "update").
            ws_id = await auth._get_stage_workspace_id(session, stage_id)
            ensure_workspace_permission(user, ws_id, "stage", "update")
            # Route reads ``force`` from the query string (bool, default False).
            force_vals = (data.get("query") or {}).get("force")
            if isinstance(force_vals, list):
                force_raw = force_vals[0] if force_vals else None
            else:
                force_raw = force_vals
            force = str(force_raw).lower() in ("1", "true", "yes", "on") if force_raw is not None else False

            stage = await stage_service.get_stage(session, stage_id)
            job = await computation_jobs.request_bracket_job(
                session,
                tournament_id=stage.tournament_id,
                stage_id=stage.id,
                operation="activate_and_generate",
                payload={"force": force},
                requested_by_user_id=int(user.id),
            )
            await session.commit()
            return _dump(TournamentComputationJobRead.model_validate(job, from_attributes=True))

        return await _run(logger, op)

    # ── wire from groups ──────────────────────────────────────────────────

    @broker.subscriber("rpc.tournament.stage_wire")
    async def _stage_wire(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            stage_id = _path_int(data, "stage_id")
            # Route: require_stage_permission("stage", "update").
            ws_id = await auth._get_stage_workspace_id(session, stage_id)
            ensure_workspace_permission(user, ws_id, "stage", "update")
            body = admin_schemas.WireFromGroupsRequest.model_validate(_payload(data))
            # wire_from_groups commits internally; returns a Stage.
            stage = await stage_service.wire_from_groups(
                session,
                target_stage_id=stage_id,
                source_stage_id=body.source_stage_id,
                top=body.top,
                top_lb=body.top_lb,
                mode=body.mode,
            )
            from src import schemas  # noqa: PLC0415

            return _dump(schemas.StageRead.model_validate(stage, from_attributes=True))

        return await _run(logger, op)

    # ── seed teams ────────────────────────────────────────────────────────

    @broker.subscriber("rpc.tournament.stage_seed")
    async def _stage_seed(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            stage_id = _path_int(data, "stage_id")
            # Route: require_stage_permission("stage", "update").
            ws_id = await auth._get_stage_workspace_id(session, stage_id)
            ensure_workspace_permission(user, ws_id, "stage", "update")
            body = admin_schemas.SeedTeamsRequest.model_validate(_payload(data))
            # seed_teams commits internally; returns a Stage.
            stage = await stage_service.seed_teams(
                session,
                stage_id=stage_id,
                team_ids=body.team_ids,
                mode=body.mode,
            )
            from src import schemas  # noqa: PLC0415

            return _dump(schemas.StageRead.model_validate(stage, from_attributes=True))

        return await _run(logger, op)
