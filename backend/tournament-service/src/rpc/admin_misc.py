"""Bespoke (non-CRUD) admin tournament methods over typed RPC.

The gateway passes path params as ``data["<name>"]`` (and the primary id as
``data["id"]`` when the RouteSpec sets IDParam), query params as
``data["query"][key] = [values]``, and the JSON body as ``data["payload"]``.
Responses are plain ``model_dump(mode="json")`` (nulls kept); the custom
dict-returning handlers return their dicts verbatim.

Commit semantics: every write service called here commits internally
(update_match, swap_slots, set_encounter_result, toggle_finished,
transition_status, recalculate_standings, upsert_report_form), so the handlers
add no extra commit. job_get/job_list, report_form_get and the encounter-reports /
parsed-matches reads are read-only.
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit.annotations import RabbitMessage

from shared import models
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.rpc.identity import ensure_workspace_permission
from shared.rpc.query import build_query_model
from shared.services.audit import record_admin_audit
from shared.services.encounter.participants import active_teams
from shared.services.match_reads import match_header_fields
from src import schemas
from src.core import auth
from src.rpc._helpers import (
    _actor_player_id,
    _bool,
    _dump,
    _identity,
    _path_int,
    _payload,
    _q1,
    _require_id,
    _require_q1,
    _run,
)
from src.schemas import encounter_report_form as report_form_schemas
from src.services.admin import encounter as enc_service
from src.services.admin import encounter_reports as reports_service
from src.services.admin import preview_access as preview_access
from src.services.admin.matches import matches_service
from src.services.admin.stage import stage_service as admin_stage_service
from src.services.admin.standing import standing_service
from src.services.admin.tournament import tournament_service
from src.services.bracket.usability import assert_encounter_live
from src.services.computation import jobs as computation_jobs
from src.services.encounter.captain import ReportResultIn, captain_service
from src.services.encounter.report_form import report_form_service
from src.services.tournament import flows as tournament_flows
from src.services.tournament.schedule import schedule_service


async def _serialize_result(session: Any, encounter: models.Encounter) -> dict:
    """The settled result state both result endpoints return.

    The standing lives on the participations, so the seats are re-read rather
    than taken off the encounter row: the result writer has just rewritten them
    and the caller holds no loaded collection.
    """
    seats = await active_teams(session, encounter.id)
    return schemas.EncounterResultRead(
        id=encounter.id,
        status=encounter.status,
        result_status=encounter.result_status,
        result_source=encounter.result_source,
        result_version=encounter.result_version,
        teams=[
            schemas.EncounterResultSnapshotLine(encounter_team_id=seat.id, score=seat.score, placement=seat.placement)
            for seat in seats
        ],
        closeness=encounter.closeness,
        confirmed_at=encounter.confirmed_at,
    ).model_dump(mode="json")


async def _assert_source_correction_allowed(session: Any, encounter_id: int) -> None:
    """Refuse a result correction whose downstream qualification is already live.

    Both result endpoints rewrite a result that a later stage may have been
    seeded from; the stage service owns that rule (it is the one that would have
    to re-resolve the frozen seeds). A missing encounter is left to the service
    below to 404 on.
    """
    encounter = await enc_service.encounter_service.get_encounter(session, encounter_id)
    if encounter is not None:
        await admin_stage_service.assert_source_correction_allowed(session, encounter)


async def _assert_bracket_live(session: Any, encounter_id: int) -> None:
    """Refuse a result on a preview bracket until its stage is activated.
    A missing encounter is left to the service to 404 on."""
    encounter = await enc_service.encounter_service.get_encounter(session, encounter_id)
    if encounter is not None:
        await assert_encounter_live(session, encounter)


async def _slot_state(session: Any, encounter: models.Encounter) -> schemas.EncounterSlotRead:
    """One side of a slot swap, as the bracket re-renders it."""
    return schemas.EncounterSlotRead(
        id=encounter.id,
        teams=[
            schemas.EncounterSeatRead(id=seat.id, slot=seat.slot, team_id=seat.team_id, name=seat.name)
            for seat in await active_teams(session, encounter.id)
        ],
        name=encounter.name,
    )


def register(broker: Any, logger: Any) -> None:
    # ── encounters ────────────────────────────────────────────────────────

    @broker.subscriber("rpc.tournament.encounter_update_match")
    async def _encounter_update_match(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            match_id = _require_id(data)
            ws_id = await auth.get_match_workspace_id(session, match_id)
            ensure_workspace_permission(user, ws_id, "match", "result")
            body = schemas.MatchUpdate.model_validate(_payload(data))
            encounter_id = await enc_service.encounter_service.get_match_encounter_id(session, match_id)
            await record_admin_audit(
                session,
                action="encounter.update_match",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="encounter",
                entity_id=encounter_id,
                after={"match_id": match_id, **body.model_dump(mode="json", exclude_unset=True)},
            )
            # update_match commits internally; the edited observation comes back as the native match header.
            match = await enc_service.encounter_service.update_match(session, match_id, body, actor=user)
            return _dump(schemas.MatchRead(**match_header_fields(match)))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.encounter_set_result")
    async def _encounter_set_result(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            encounter_id = _require_id(data)
            ws_id = await auth.get_encounter_workspace_id(session, encounter_id)
            ensure_workspace_permission(user, ws_id, "match", "result")
            await _assert_bracket_live(session, encounter_id)
            body = schemas.SetResultIn.model_validate(_payload(data))
            await record_admin_audit(
                session,
                action="encounter.set_result",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="encounter",
                entity_id=encounter_id,
                after=body.model_dump(mode="json", exclude_none=True),
            )
            await _assert_source_correction_allowed(session, encounter_id)
            # set_encounter_result commits internally.
            encounter = await captain_service.set_encounter_result(
                session,
                encounter_id,
                actor_user_id=await _actor_player_id(session, user),
                reason=body.reason,
                results=[
                    ReportResultIn(
                        encounter_team_id=line.encounter_team_id,
                        score=line.score,
                        placement=line.placement,
                    )
                    for line in body.results
                ],
                closeness=body.closeness,
                adopt_report_team_id=body.adopt_report_team_id,
            )
            return await _serialize_result(session, encounter)

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.encounter_swap_slot")
    async def _encounter_swap_slot(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            encounter_id = _require_id(data)
            ws_id = await auth.get_encounter_workspace_id(session, encounter_id)
            ensure_workspace_permission(user, ws_id, "match", "update")
            body = schemas.EncounterSwapSlotInput.model_validate(_payload(data))
            await record_admin_audit(
                session,
                action="encounter.swap_slot",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="encounter",
                entity_id=encounter_id,
                after=body.model_dump(mode="json"),
            )
            # swap_slots commits internally; both sides come back so the bracket
            # re-renders the pair without a refetch.
            source, target = await enc_service.encounter_service.swap_slots(session, encounter_id, body)
            return schemas.EncounterSlotSwapRead(
                source=await _slot_state(session, source),
                target=await _slot_state(session, target),
            ).model_dump(mode="json")

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.encounter_reopen_result")
    async def _encounter_reopen_result(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            encounter_id = _require_id(data)
            ws_id = await auth.get_encounter_workspace_id(session, encounter_id)
            ensure_workspace_permission(user, ws_id, "match", "result")
            body = schemas.ReopenResultIn.model_validate(_payload(data))
            await record_admin_audit(
                session,
                action="encounter.reopen_result",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="encounter",
                entity_id=encounter_id,
                after=body.model_dump(mode="json"),
            )
            await _assert_source_correction_allowed(session, encounter_id)
            encounter = await captain_service.reopen_encounter_result(
                session,
                encounter_id,
                actor_user_id=await _actor_player_id(session, user),
                reason=body.reason,
            )
            return await _serialize_result(session, encounter)

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.encounter_result_audit")
    async def _encounter_result_audit(data: dict, msg: RabbitMessage) -> Any:
        async def op(session: Any) -> Any:
            user = _identity(data)
            encounter_id = _require_id(data)
            ws_id = await auth.get_encounter_workspace_id(session, encounter_id)
            ensure_workspace_permission(user, ws_id, "match", "read")
            return await captain_service.get_result_audit(session, encounter_id)

        return await _run(logger, op)

    # ── match report form (per-tournament captain-report config) ──────────

    @broker.subscriber("rpc.tournament.report_form_get")
    async def _report_form_get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            ws_id = await auth.get_tournament_workspace_id(session, tournament_id)
            ensure_workspace_permission(user, ws_id, "match", "read")
            # Always a full defaults-merged config, never null — deliberately
            # unlike rpc.tournament.reg_form_get. "No row yet" is the normal
            # state (rows are created lazily on first save), so the client gets
            # a config to render instead of an empty branch to special-case.
            # resolve_report_form is read-only: it never materializes the row.
            return _dump(await report_form_service.resolve_report_form(session, tournament_id))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.report_form_upsert")
    async def _report_form_upsert(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            ws_id = await auth.get_tournament_workspace_id(session, tournament_id)
            ensure_workspace_permission(user, ws_id, "match", "update")
            body = report_form_schemas.MatchReportFormUpsert.model_validate(_payload(data))
            await record_admin_audit(
                session,
                action="report_form.upsert",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="tournament",
                entity_id=tournament_id,
                after={
                    "built_in_fields": {
                        key: config.model_dump(mode="json") for key, config in body.built_in_fields.items()
                    },
                    "custom_field_keys": [field.key for field in body.custom_fields],
                },
            )
            # get_tournament_workspace_id above already 404s on a missing
            # tournament; upsert_report_form commits internally.
            return _dump(await report_form_service.upsert_report_form(session, tournament_id, body))

        return await _run(logger, op)

    # ── tournaments ───────────────────────────────────────────────────────

    @broker.subscriber("rpc.tournament.tournament_finish")
    async def _tournament_finish(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            if not user.is_superuser:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Superuser privileges required",
                )
            tournament_id = _require_id(data)
            ws_id = await auth.get_tournament_workspace_id(session, tournament_id)
            await record_admin_audit(
                session,
                action="tournament.finish",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="tournament",
                entity_id=tournament_id,
            )
            # toggle_finished commits internally.
            tournament = await tournament_service.toggle_finished(session, tournament_id)
            return _dump(await tournament_flows.flows_service.to_pydantic(session, tournament, ["stages"]))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.tournament_status")
    async def _tournament_status(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            ws_id = await auth.get_tournament_workspace_id(session, tournament_id)
            ensure_workspace_permission(user, ws_id, "tournament", "update")
            body = schemas.TournamentStatusTransition.model_validate(_payload(data))
            if body.force and not user.is_superuser:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only superusers can bypass tournament status transitions",
                )
            await record_admin_audit(
                session,
                action="tournament.status",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="tournament",
                entity_id=tournament_id,
                after={"status": body.status.value, "force": body.force},
            )
            # transition_status commits internally.
            tournament = await tournament_service.transition_status(
                session,
                tournament_id,
                body.status,
                force=body.force,
            )
            return _dump(await tournament_flows.flows_service.to_pydantic(session, tournament, ["stages"]))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.tournament_schedule_set")
    async def _tournament_schedule_set(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            ws_id = await auth.get_tournament_workspace_id(session, tournament_id)
            ensure_workspace_permission(user, ws_id, "tournament", "update")
            body = schemas.TournamentScheduleSet.model_validate(_payload(data))
            await record_admin_audit(
                session,
                action="tournament.schedule",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="tournament",
                entity_id=tournament_id,
                after={"count": len(body.schedule)},
            )
            # set_schedule commits internally (full replace of the phase rows).
            tournament = await schedule_service.set_schedule(session, tournament_id, body.schedule)
            return _dump(await tournament_flows.flows_service.to_pydantic(session, tournament, ["stages"]))

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
            rows = await preview_access.preview_access_service.list_preview_access(session, tournament_id)
            return [preview_access.serialize_entry(row) for row in rows]

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
            await record_admin_audit(
                session,
                action="tournament.preview_access.add",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="tournament",
                entity_id=tournament_id,
                after={"auth_user_id": auth_user_id},
            )
            row = await preview_access.preview_access_service.add_preview_access(session, tournament_id, auth_user_id)
            return preview_access.serialize_entry(row)

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.preview_access_remove")
    async def _preview_access_remove(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            ws_id = await auth.get_tournament_workspace_id(session, tournament_id)
            _require_ws_admin(user, ws_id)
            auth_user_id = _path_int(data, "auth_user_id")
            await record_admin_audit(
                session,
                action="tournament.preview_access.remove",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="tournament",
                entity_id=tournament_id,
                after={"auth_user_id": auth_user_id},
            )
            await preview_access.preview_access_service.remove_preview_access(session, tournament_id, auth_user_id)
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
                action="update",
            )
            ws_id = await auth.get_tournament_workspace_id(session, tournament_id)
            await record_admin_audit(
                session,
                action="standing.recalculate",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="tournament",
                entity_id=tournament_id,
            )
            # recalculate_standings commits internally; returns a job.
            job = await standing_service.recalculate_standings(
                session,
                tournament_id,
                requested_by_user_id=int(user.id),
            )
            return _dump(schemas.TournamentComputationJobRead.model_validate(job, from_attributes=True))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.standing_pins_set")
    async def _standing_pins_set(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            stage_id = _path_int(data, "stage_id")
            ws_id = await auth.get_stage_workspace_id(session, stage_id)
            ensure_workspace_permission(user, ws_id, "standing", "update")
            body = schemas.StandingPinsUpdate.model_validate(_payload(data) or {})
            stage = await admin_stage_service.get_stage(session, stage_id)
            before = await standing_service.get_pins(session, stage_id, body.stage_item_id)
            await record_admin_audit(
                session,
                action="standing.pins_set",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="stage",
                entity_id=stage_id,
                entity_label=stage.name,
                before={"stage_item_id": body.stage_item_id, "pins": before},
                after={"stage_item_id": body.stage_item_id, "pins": {pin.team_id: pin.position for pin in body.pins}},
            )
            # set_pins commits (the audit row with it) and returns the recalculation job.
            job = await standing_service.set_pins(session, stage, body, requested_by_user_id=int(user.id))
            return _dump(schemas.TournamentComputationJobRead.model_validate(job, from_attributes=True))

        return await _run(logger, op)

    # ── computation jobs (read-only) ──────────────────────────────────────

    @broker.subscriber("rpc.tournament.job_get")
    async def _job_get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            job_id = _require_id(data)
            job = await computation_jobs.jobs_service.get_job(session, job_id)
            if job is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament job not found")
            await auth.require_tournament_id_permission(
                session,
                user,
                tournament_id=job.tournament_id,
                resource="standing" if job.kind == "standings" else "stage",
                action="update",
            )
            return _dump(schemas.TournamentComputationJobRead.model_validate(job, from_attributes=True))

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
                scoped_tournament_id = await admin_stage_service.get_tournament_id(session, stage_id)
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
            jobs_list = await computation_jobs.jobs_service.list_jobs(
                session,
                tournament_id=scoped_tournament_id,
                stage_id=stage_id,
                active_only=active_only,
                limit=limit,
            )
            return [
                _dump(schemas.TournamentComputationJobRead.model_validate(job, from_attributes=True))
                for job in jobs_list
            ]

        return await _run(logger, op)

    # ── captain reports (cross-tournament, workspace-scoped) ──────────────

    def _reports_params(data: dict) -> tuple[int, Any]:
        """Resolve the workspace and parse the shared filter set.

        The workspace is an explicit query param rather than inferred: this list
        spans every tournament in it, so there is no single tournament to derive
        the scope from.
        """
        user = _identity(data)
        workspace_id = _require_q1(data, "workspace_id", int)
        ensure_workspace_permission(user, workspace_id, "match", "read")
        qp = build_query_model(schemas.EncounterReportsQueryParams, data.get("query"))
        return workspace_id, schemas.EncounterReportsSearchParams.from_query_params(qp)

    @broker.subscriber("rpc.tournament.admin_encounter_reports_list")
    async def _admin_encounter_reports_list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspace_id, params = _reports_params(data)
            return _dump(
                await reports_service.encounter_reports_service.list_encounter_reports(
                    session, workspace_id=workspace_id, params=params
                )
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.admin_encounter_reports_stats")
    async def _admin_encounter_reports_stats(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspace_id, params = _reports_params(data)
            return _dump(
                await reports_service.encounter_reports_service.get_reports_stats(
                    session, workspace_id=workspace_id, params=params
                )
            )

        return await _run(logger, op)

    # ── parsed matches (cross-tournament, workspace-scoped) ───────────────

    def _matches_workspace(data: dict) -> int:
        """The scope both match reads are gated on.

        An explicit query param, never derived from the row: deriving it would
        scope the read to whatever tenant already owns the id, which is the check
        inverted.
        """
        user = _identity(data)
        workspace_id = _require_q1(data, "workspace_id", int)
        ensure_workspace_permission(user, workspace_id, "match", "read")
        return workspace_id

    def _matches_params(data: dict) -> tuple[int, Any]:
        """Same shape as ``_reports_params``: the list spans every tournament in
        the workspace, so there is no single tournament to derive the scope from.
        """
        workspace_id = _matches_workspace(data)
        qp = build_query_model(schemas.AdminMatchesQueryParams, data.get("query"))
        return workspace_id, schemas.AdminMatchesSearchParams.from_query_params(qp)

    @broker.subscriber("rpc.tournament.admin_matches_list")
    async def _admin_matches_list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspace_id, params = _matches_params(data)
            return _dump(await matches_service.list_admin_matches(session, workspace_id=workspace_id, params=params))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.admin_match_get")
    async def _admin_match_get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspace_id = _matches_workspace(data)
            match_id = _require_id(data)
            return _dump(await matches_service.get_admin_match(session, workspace_id=workspace_id, match_id=match_id))

        return await _run(logger, op)
