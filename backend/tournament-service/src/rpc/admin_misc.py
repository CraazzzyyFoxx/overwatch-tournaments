"""Bespoke (non-CRUD) admin tournament methods over typed RPC.

Each handler mirrors a route in ``src/routes/admin/{encounter,tournament,standing,
computation}.py`` exactly: it rehydrates the gateway-injected identity, runs the
SAME imperative permission check the route's dependency performed, validates the
SAME body schema, calls the SAME service function with the SAME args, and
serializes the SAME way the route returned (admin routes do NOT use
``response_model_exclude_none`` -> plain ``model_dump(mode="json")``; the custom
dict-returning routes return their dicts verbatim).

The gateway passes path params as ``data["<name>"]`` (and the primary id as
``data["id"]`` when the RouteSpec sets IDParam), query params as
``data["query"][key] = [values]``, and the JSON body as ``data["payload"]``.

Commit semantics: every write service called here commits internally
(bulk_update_encounters, update_match, admin_confirm_result, initialize_map_pool,
toggle_finished, transition_status, recalculate_standings), so the handlers add no
extra commit. job_get/job_list are read-only.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from faststream.rabbit.annotations import RabbitMessage
from pydantic import BaseModel

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.rpc.identity import ensure_workspace_permission
from src import models
from src.core import auth
from src.rpc._helpers import _bool, _dump, _identity, _path_int, _payload, _q1, _require_id, _run
from src.schemas.admin import encounter as enc_schemas
from src.schemas.admin import tournament as tournament_schemas
from src.schemas.admin.computation import TournamentComputationJobRead
from src.services.admin import encounter as enc_service
from src.services.admin import preview_access as preview_access_service
from src.services.admin import standing as standing_service
from src.services.admin import tournament as tournament_service
from src.services.computation import jobs as computation_jobs
from src.services.encounter import captain as captain_service
from src.services.encounter import map_veto as map_veto_service
from src.services.tournament import flows as tournament_flows
from src.services.tournament import schedule as schedule_service
from src.services.tournament.cache_invalidation import invalidate_tournament_cache


class AdminMapPoolAssign(BaseModel):
    """Body for the admin map-pool assignment route."""

    map_ids: list[int]


# --- helpers -----------------------------------------------------------------


def register(broker: Any, logger: Any) -> None:
    # ── encounters ────────────────────────────────────────────────────────

    @broker.subscriber("rpc.tournament.encounter_bulk_update")
    async def _encounter_bulk_update(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            body = enc_schemas.BulkEncounterUpdate.model_validate(_payload(data))
            await auth.require_encounter_ids_permission(
                session,
                user,
                encounter_ids=body.encounter_ids,
                resource="match",
                action="update",
            )
            # bulk_update_encounters commits internally; returns a custom dict.
            return await enc_service.bulk_update_encounters(session, body)

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.encounter_update_match")
    async def _encounter_update_match(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            match_id = _require_id(data)
            ws_id = await auth.get_match_workspace_id(session, match_id)
            ensure_workspace_permission(user, ws_id, "match", "update")
            body = enc_schemas.MatchUpdate.model_validate(_payload(data))
            # update_match commits internally; route returns a custom dict.
            match = await enc_service.update_match(session, match_id, body)
            return {
                "id": match.id,
                "encounter_id": match.encounter_id,
                "home_team_id": match.home_team_id,
                "away_team_id": match.away_team_id,
                "home_score": match.home_score,
                "away_score": match.away_score,
                "map_id": match.map_id,
                "code": match.code,
                "time": match.time,
                "log_name": match.log_name,
            }

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.encounter_confirm_result")
    async def _encounter_confirm_result(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            encounter_id = _require_id(data)
            ws_id = await auth.get_encounter_workspace_id(session, encounter_id)
            ensure_workspace_permission(user, ws_id, "match", "update")
            # admin_confirm_result commits internally; route returns a custom dict.
            encounter = await captain_service.admin_confirm_result(session, encounter_id)
            return {
                "id": encounter.id,
                "result_status": encounter.result_status,
                "status": encounter.status,
            }

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.encounter_assign_map_pool")
    async def _encounter_assign_map_pool(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            encounter_id = _require_id(data)
            ws_id = await auth.get_encounter_workspace_id(session, encounter_id)
            ensure_workspace_permission(user, ws_id, "match", "update")
            body = AdminMapPoolAssign.model_validate(_payload(data))
            # initialize_map_pool commits internally; route returns {"assigned": N}.
            entries = await map_veto_service.initialize_map_pool(session, encounter_id, body.map_ids)
            return {"assigned": len(entries)}

        return await _run(logger, op)

    # ── tournaments ───────────────────────────────────────────────────────

    @broker.subscriber("rpc.tournament.tournament_finish")
    async def _tournament_finish(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            # Route gates on get_current_superuser.
            if not user.is_superuser:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Superuser privileges required",
                )
            tournament_id = _require_id(data)
            # toggle_finished commits internally.
            tournament = await tournament_service.toggle_finished(session, tournament_id)
            return _dump(await tournament_flows.to_pydantic(session, tournament, ["stages"]))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.tournament_status")
    async def _tournament_status(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            ws_id = await auth.get_tournament_workspace_id(session, tournament_id)
            ensure_workspace_permission(user, ws_id, "tournament", "update")
            body = tournament_schemas.TournamentStatusTransition.model_validate(_payload(data))
            # force bypass is superuser-only (matches the route's explicit gate).
            if body.force and not user.is_superuser:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only superusers can bypass tournament status transitions",
                )
            # transition_status commits internally.
            tournament = await tournament_service.transition_status(
                session,
                tournament_id,
                body.status,
                force=body.force,
            )
            return _dump(await tournament_flows.to_pydantic(session, tournament, ["stages"]))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.tournament_schedule_set")
    async def _tournament_schedule_set(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            ws_id = await auth.get_tournament_workspace_id(session, tournament_id)
            ensure_workspace_permission(user, ws_id, "tournament", "update")
            body = tournament_schemas.TournamentScheduleSet.model_validate(_payload(data))
            # set_schedule commits internally (full replace of the phase rows).
            tournament = await schedule_service.set_schedule(session, tournament_id, body.schedule)
            return _dump(await tournament_flows.to_pydantic(session, tournament, ["stages"]))

        return await _run(logger, op)

    # ── preview access (hidden-tournament allowlist; workspace-admin gated) ─

    def _require_ws_admin(user: models.AuthUser, ws_id: int) -> None:
        if not user.is_workspace_admin(ws_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Workspace admin privileges required",
            )

    @broker.subscriber("rpc.tournament.preview_access_list")
    async def _preview_access_list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            ws_id = await auth.get_tournament_workspace_id(session, tournament_id)
            _require_ws_admin(user, ws_id)
            rows = await preview_access_service.list_preview_access(session, tournament_id)
            return [preview_access_service.serialize_entry(row) for row in rows]

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.preview_access_add")
    async def _preview_access_add(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            ws_id = await auth.get_tournament_workspace_id(session, tournament_id)
            _require_ws_admin(user, ws_id)
            payload = _payload(data)
            try:
                auth_user_id = int(payload["auth_user_id"])
            except (KeyError, TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail="auth_user_id is required") from exc
            row = await preview_access_service.add_preview_access(session, tournament_id, auth_user_id)
            # Refresh the (viewer-agnostic) cached tournament read so the badge/state update.
            await invalidate_tournament_cache(tournament_id, "structure_changed")
            return preview_access_service.serialize_entry(row)

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.preview_access_remove")
    async def _preview_access_remove(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            ws_id = await auth.get_tournament_workspace_id(session, tournament_id)
            _require_ws_admin(user, ws_id)
            auth_user_id = _path_int(data, "auth_user_id")
            await preview_access_service.remove_preview_access(session, tournament_id, auth_user_id)
            await invalidate_tournament_cache(tournament_id, "structure_changed")
            return None

        return await _run(logger, op)

    # ── standings ─────────────────────────────────────────────────────────

    @broker.subscriber("rpc.tournament.standing_recalculate")
    async def _standing_recalculate(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            await auth.require_tournament_id_permission(
                session,
                user,
                tournament_id=tournament_id,
                resource="standing",
                action="recalculate",
            )
            # recalculate_standings commits internally; returns a job.
            job = await standing_service.recalculate_standings(
                session,
                tournament_id,
                requested_by_user_id=int(user.id),
            )
            return _dump(TournamentComputationJobRead.model_validate(job, from_attributes=True))

        return await _run(logger, op)

    # ── computation jobs (read-only) ──────────────────────────────────────

    @broker.subscriber("rpc.tournament.job_get")
    async def _job_get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            job_id = _require_id(data)
            job = await computation_jobs.get_job(session, job_id)
            if job is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament job not found")
            await auth.require_tournament_id_permission(
                session,
                user,
                tournament_id=job.tournament_id,
                resource="standing" if job.kind == "standings" else "stage",
                action="recalculate" if job.kind == "standings" else "update",
            )
            return _dump(TournamentComputationJobRead.model_validate(job, from_attributes=True))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.job_list")
    async def _job_list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _q1(data, "tournament_id", int)
            stage_id = _q1(data, "stage_id", int)
            active_only = _q1(data, "active_only", _bool, default=False)
            limit = _q1(data, "limit", int, default=50)
            if limit < 1 or limit > 100:
                raise HTTPException(status_code=422, detail="limit must be between 1 and 100")

            scoped_tournament_id = tournament_id
            if scoped_tournament_id is None and stage_id is not None:
                scoped_tournament_id = await session.scalar(
                    sa.select(models.Stage.tournament_id).where(models.Stage.id == stage_id)
                )
                if scoped_tournament_id is None:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stage not found")
            if scoped_tournament_id is None and not user.is_superuser:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="tournament_id or stage_id is required",
                )
            if scoped_tournament_id is not None:
                await auth.require_tournament_id_permission(
                    session,
                    user,
                    tournament_id=scoped_tournament_id,
                    resource="stage",
                    action="read",
                )
            jobs_list = await computation_jobs.list_jobs(
                session,
                tournament_id=scoped_tournament_id,
                stage_id=stage_id,
                active_only=active_only,
                limit=limit,
            )
            return [_dump(TournamentComputationJobRead.model_validate(job, from_attributes=True)) for job in jobs_list]

        return await _run(logger, op)
