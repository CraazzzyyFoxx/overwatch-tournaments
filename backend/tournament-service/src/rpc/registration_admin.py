"""Admin registration + registration-status methods over typed RPC.

Each handler mirrors a route in ``src/routes/admin/registration.py`` and
``src/routes/admin/registration_status.py`` exactly: it rehydrates the
gateway-injected identity, runs the SAME imperative permission check the route's
dependency performed, validates the SAME body schema, calls the SAME service
function with the SAME args, and serializes the SAME way the route returned.

Admin routes do NOT use ``response_model_exclude_none`` -> plain
``model_dump(mode="json")``; routes that return ``None`` (e.g. the form GET) or
nothing (DELETE 204) return ``None`` verbatim.

The gateway passes path params as ``data["<name>"]`` (and the primary id as
``data["id"]`` when the RouteSpec sets IDParam), query params as
``data["query"][key] = [values]``, and the JSON body as ``data["payload"]``.

Permission model — replicated per route:
  * ``require_tournament_permission(res, act)`` -> resolve tournament workspace,
    ``ensure_workspace_permission(user, ws, res, act)``.
  * ``require_registration_permission(res, act)`` -> resolve registration
    workspace, ``ensure_workspace_permission``.
  * ``require_workspace_permission(res, act)`` (workspace-scoped routes) ->
    ``ensure_workspace_permission`` on the path ``workspace_id`` directly.

Commit semantics: every registration mutation service called here commits
internally (create_manual_registration / update_registration_profile /
approve / reject / bulk_approve / set_exclusion / withdraw / restore /
soft_delete / set_balancer_status / bulk_add_to_balancer / check_in /
uncheck_in / export_registrations_to_users) and so do all status_catalog
mutations (create/update/delete custom, upsert/reset builtin override). The
rank-autofill service commits internally on ``apply=True`` when something
changed (preview never writes). The form upsert is done inline here exactly as
the route did (``session.commit()`` + ``session.refresh``). ``emit_*`` runs in
its own session and is a realtime broadcast — it needs no extra commit. So no
handler adds a redundant commit.
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit.annotations import RabbitMessage
from sqlalchemy import select

from shared.balancer_registration_statuses import get_status_metas_map
from shared.core.errors import BaseAPIException as HTTPException
from shared.rpc.identity import ensure_workspace_permission
from shared.services.rank_snapshots import (
    fetch_latest_ow_ranks_by_account,
    normalize_ow_ranks_to_grid,
)
from src import models
from src.core import auth
from src.rpc._helpers import _bool, _dump, _identity, _path_int, _payload, _q1, _require_id, _run
from src.schemas.admin import balancer as admin_schemas
from src.schemas.registration import RegistrationFormUpsert
from src.services.registration import admin as registration_service
from src.services.registration import service as reg_svc
from src.services.registration import status_catalog
from src.services.registration.ow_rank_selection import select_main_account_ow_ranks
from src.services.registration.realtime import emit_balancer_registrations_changed
from src.services.registration.serializers import (
    serialize_registration,
    serialize_registration_form,
    serialize_status,
)

# --- helpers -----------------------------------------------------------------

# Same cap as BulkEncounterUpdate.encounter_ids — bulk operations must not
# accept unbounded id lists.
_MAX_BULK_IDS = 500


def _bulk_ids(payload: dict[str, Any], key: str = "registration_ids") -> list[int]:
    try:
        ids = [int(value) for value in payload.get(key) or []]
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"{key} must be a list of integers") from exc
    if len(ids) > _MAX_BULK_IDS:
        raise HTTPException(status_code=422, detail=f"{key} accepts at most {_MAX_BULK_IDS} items")
    return ids


def _require_scope(data: dict[str, Any]) -> str:
    """Validate the {scope} path param against the StatusScope literal (route 422 on mismatch)."""
    scope = data.get("scope")
    if scope not in ("registration", "balancer"):
        raise HTTPException(status_code=422, detail="scope must be 'registration' or 'balancer'")
    return str(scope)


def _require_slug(data: dict[str, Any]) -> str:
    slug = data.get("slug")
    if slug is None:
        raise HTTPException(status_code=422, detail="slug is required")
    return str(slug)


def register(broker: Any, logger: Any) -> None:
    # ══════════════════════════════════════════════════════════════════════
    #  registration.py  (router prefix /balancer)
    # ══════════════════════════════════════════════════════════════════════

    # GET /balancer/tournaments/{tournament_id}/registration-form
    #   dep: require_tournament_permission("team", "read")
    @broker.subscriber("rpc.tournament.reg_form_get")
    async def _reg_form_get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            ws_id = await auth.get_tournament_workspace_id(session, tournament_id)
            ensure_workspace_permission(user, ws_id, "team", "read")
            form = await registration_service.get_registration_form(session, tournament_id)
            if form is None:
                return None
            return _dump(serialize_registration_form(form))

        return await _run(logger, op)

    # PUT /balancer/tournaments/{tournament_id}/registration-form
    #   dep: require_tournament_permission("team", "import")
    @broker.subscriber("rpc.tournament.reg_form_upsert")
    async def _reg_form_upsert(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            ws_id = await auth.get_tournament_workspace_id(session, tournament_id)
            ensure_workspace_permission(user, ws_id, "team", "import")
            body = RegistrationFormUpsert.model_validate(_payload(data))
            # get_tournament_workspace_id above already 404s on a missing
            # tournament; upsert_registration_form commits internally.
            form = await reg_svc.upsert_registration_form(session, tournament_id, body, workspace_id=ws_id)
            return _dump(serialize_registration_form(form))

        return await _run(logger, op)

    # GET /balancer/tournaments/{tournament_id}/registrations
    #   dep: require_tournament_permission("team", "read")
    #   FAT handler: list + status-meta map + per-registration OW-rank snapshot join.
    @broker.subscriber("rpc.tournament.reg_list")
    async def _reg_list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            ws_id = await auth.get_tournament_workspace_id(session, tournament_id)
            ensure_workspace_permission(user, ws_id, "team", "read")

            status_filter = _q1(data, "status_filter")
            inclusion_filter = _q1(data, "inclusion_filter")
            source_filter = _q1(data, "source_filter")
            include_deleted = _q1(data, "include_deleted", _bool, default=False)

            registrations = await registration_service.list_registrations(
                session,
                tournament_id,
                status_filter=status_filter,
                inclusion_filter=inclusion_filter,
                source_filter=source_filter,
                include_deleted=include_deleted,
            )
            status_meta_map = await get_status_metas_map(session, workspace_id=ws_id) if registrations else None
            # Registrations are anchored on workspace_member (eager-loaded by
            # list_registrations); the player id is the member's player_id.
            user_ids = [r.workspace_member.player_id for r in registrations if r.workspace_member is not None]
            grid = await registration_service.get_tournament_grid(session, tournament_id)
            accounts_by_user = await fetch_latest_ow_ranks_by_account(session, user_ids)
            # Per registration, prefer the player's main (non-smurf) accounts and take the max rank.
            raw_ow_ranks_by_registration = {
                registration.id: select_main_account_ow_ranks(
                    accounts_by_user.get(registration.workspace_member.player_id, {}),
                    registration.smurf_tags_json,
                )
                for registration in registrations
                if registration.workspace_member is not None
            }
            ow_ranks = normalize_ow_ranks_to_grid(raw_ow_ranks_by_registration, grid)
            return [
                _dump(
                    serialize_registration(
                        registration,
                        workspace_id=ws_id,
                        status_meta_map=status_meta_map,
                        ow_ranks_for_user=ow_ranks.get(registration.id),
                    )
                )
                for registration in registrations
            ]

        return await _run(logger, op)

    # POST /balancer/tournaments/{tournament_id}/registrations  (201)
    #   dep: require_tournament_permission("team", "import")
    @broker.subscriber("rpc.tournament.reg_create_manual")
    async def _reg_create_manual(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            ws_id = await auth.get_tournament_workspace_id(session, tournament_id)
            ensure_workspace_permission(user, ws_id, "team", "import")
            body = admin_schemas.BalancerRegistrationCreateRequest.model_validate(_payload(data))

            await registration_service.ensure_tournament_exists(session, tournament_id)
            registration = await registration_service.create_manual_registration(
                session,
                tournament_id=tournament_id,
                display_name=body.display_name,
                battle_tag=body.battle_tag,
                smurf_tags_json=body.smurf_tags_json,
                discord_nick=body.discord_nick,
                twitch_nick=body.twitch_nick,
                stream_pov=body.stream_pov,
                notes=body.notes,
                admin_notes=body.admin_notes,
                roles=[role.model_dump() for role in body.roles],
                auth_user_id=body.auth_user_id,
            )
            status_meta_map = await get_status_metas_map(session, workspace_id=ws_id)
            await emit_balancer_registrations_changed(
                registration.tournament_id,
                workspace_id=ws_id,
                actor_user_id=user.id,
            )
            return _dump(serialize_registration(registration, workspace_id=ws_id, status_meta_map=status_meta_map))

        return await _run(logger, op)

    # PATCH /balancer/registrations/{registration_id}
    #   dep: require_registration_permission("team", "update")
    @broker.subscriber("rpc.tournament.reg_update")
    async def _reg_update(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            registration_id = _require_id(data)
            ws_id = await auth.get_registration_workspace_id(session, registration_id)
            ensure_workspace_permission(user, ws_id, "team", "update")
            body = admin_schemas.BalancerRegistrationUpdateRequest.model_validate(_payload(data))

            registration = await registration_service.update_registration_profile(
                session,
                registration_id,
                display_name=body.display_name,
                battle_tag=body.battle_tag,
                smurf_tags_json=body.smurf_tags_json,
                discord_nick=body.discord_nick,
                twitch_nick=body.twitch_nick,
                stream_pov=body.stream_pov,
                notes=body.notes,
                admin_notes=body.admin_notes,
                status_value=body.status,
                balancer_status_value=body.balancer_status,
                roles=[role.model_dump() for role in body.roles] if body.roles is not None else None,
                auth_user_id=body.auth_user_id,
            )
            status_meta_map = await get_status_metas_map(session, workspace_id=ws_id)
            await emit_balancer_registrations_changed(
                registration.tournament_id,
                workspace_id=ws_id,
                actor_user_id=user.id,
            )
            return _dump(serialize_registration(registration, workspace_id=ws_id, status_meta_map=status_meta_map))

        return await _run(logger, op)

    # PATCH /balancer/registrations/{registration_id}/approve
    #   dep: require_registration_permission("team", "import")
    @broker.subscriber("rpc.tournament.reg_approve")
    async def _reg_approve(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            registration_id = _require_id(data)
            ws_id = await auth.get_registration_workspace_id(session, registration_id)
            ensure_workspace_permission(user, ws_id, "team", "import")
            registration = await registration_service.approve_registration(
                session,
                registration_id,
                reviewed_by=user.id,
            )
            status_meta_map = await get_status_metas_map(session, workspace_id=ws_id)
            await emit_balancer_registrations_changed(
                registration.tournament_id,
                workspace_id=ws_id,
                actor_user_id=user.id,
            )
            return _dump(serialize_registration(registration, workspace_id=ws_id, status_meta_map=status_meta_map))

        return await _run(logger, op)

    # PATCH /balancer/registrations/{registration_id}/reject
    #   dep: require_registration_permission("team", "import")
    @broker.subscriber("rpc.tournament.reg_reject")
    async def _reg_reject(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            registration_id = _require_id(data)
            ws_id = await auth.get_registration_workspace_id(session, registration_id)
            ensure_workspace_permission(user, ws_id, "team", "import")
            registration = await registration_service.reject_registration(
                session,
                registration_id,
                reviewed_by=user.id,
            )
            status_meta_map = await get_status_metas_map(session, workspace_id=ws_id)
            await emit_balancer_registrations_changed(
                registration.tournament_id,
                workspace_id=ws_id,
                actor_user_id=user.id,
            )
            return _dump(serialize_registration(registration, workspace_id=ws_id, status_meta_map=status_meta_map))

        return await _run(logger, op)

    # PATCH /balancer/registrations/{registration_id}/exclusion
    #   dep: require_registration_permission("team", "update")
    @broker.subscriber("rpc.tournament.reg_exclusion")
    async def _reg_exclusion(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            registration_id = _require_id(data)
            ws_id = await auth.get_registration_workspace_id(session, registration_id)
            ensure_workspace_permission(user, ws_id, "team", "update")
            body = admin_schemas.BalancerRegistrationExclusionRequest.model_validate(_payload(data))
            registration = await registration_service.set_registration_exclusion(
                session,
                registration_id,
                exclude_from_balancer=body.exclude_from_balancer,
                exclude_reason=body.exclude_reason,
            )
            status_meta_map = await get_status_metas_map(session, workspace_id=ws_id)
            await emit_balancer_registrations_changed(
                registration.tournament_id,
                workspace_id=ws_id,
                actor_user_id=user.id,
            )
            return _dump(serialize_registration(registration, workspace_id=ws_id, status_meta_map=status_meta_map))

        return await _run(logger, op)

    # PATCH /balancer/registrations/{registration_id}/withdraw
    #   dep: require_registration_permission("team", "update")
    @broker.subscriber("rpc.tournament.reg_withdraw")
    async def _reg_withdraw(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            registration_id = _require_id(data)
            ws_id = await auth.get_registration_workspace_id(session, registration_id)
            ensure_workspace_permission(user, ws_id, "team", "update")
            registration = await registration_service.withdraw_registration(session, registration_id)
            status_meta_map = await get_status_metas_map(session, workspace_id=ws_id)
            await emit_balancer_registrations_changed(
                registration.tournament_id,
                workspace_id=ws_id,
                actor_user_id=user.id,
            )
            return _dump(serialize_registration(registration, workspace_id=ws_id, status_meta_map=status_meta_map))

        return await _run(logger, op)

    # PATCH /balancer/registrations/{registration_id}/restore
    #   dep: require_registration_permission("team", "update")
    @broker.subscriber("rpc.tournament.reg_restore")
    async def _reg_restore(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            registration_id = _require_id(data)
            ws_id = await auth.get_registration_workspace_id(session, registration_id)
            ensure_workspace_permission(user, ws_id, "team", "update")
            registration = await registration_service.restore_registration(session, registration_id)
            status_meta_map = await get_status_metas_map(session, workspace_id=ws_id)
            await emit_balancer_registrations_changed(
                registration.tournament_id,
                workspace_id=ws_id,
                actor_user_id=user.id,
            )
            return _dump(serialize_registration(registration, workspace_id=ws_id, status_meta_map=status_meta_map))

        return await _run(logger, op)

    # DELETE /balancer/registrations/{registration_id}  (204)
    #   dep: require_registration_permission("team", "import")
    @broker.subscriber("rpc.tournament.reg_delete")
    async def _reg_delete(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            registration_id = _require_id(data)
            ws_id = await auth.get_registration_workspace_id(session, registration_id)
            ensure_workspace_permission(user, ws_id, "team", "import")
            tournament_id = await session.scalar(
                select(models.BalancerRegistration.tournament_id).where(
                    models.BalancerRegistration.id == registration_id
                )
            )
            await registration_service.soft_delete_registration(
                session,
                registration_id,
                deleted_by=user.id,
            )
            if tournament_id is not None:
                await emit_balancer_registrations_changed(int(tournament_id), actor_user_id=user.id)
            return None

        return await _run(logger, op)

    # POST /balancer/tournaments/{tournament_id}/registrations/bulk-approve
    #   dep: require_tournament_permission("team", "import")
    @broker.subscriber("rpc.tournament.reg_bulk_approve")
    async def _reg_bulk_approve(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            ws_id = await auth.get_tournament_workspace_id(session, tournament_id)
            ensure_workspace_permission(user, ws_id, "team", "import")
            payload = _payload(data)
            registration_ids = _bulk_ids(payload)
            approved, skipped = await registration_service.bulk_approve_registrations(
                session,
                tournament_id,
                registration_ids,
                reviewed_by=user.id,
            )
            if approved:
                await emit_balancer_registrations_changed(tournament_id, actor_user_id=user.id)
            return _dump(admin_schemas.BulkApproveResponse(approved=approved, skipped=skipped))

        return await _run(logger, op)

    # PATCH /balancer/registrations/{registration_id}/balancer-status
    #   dep: require_registration_permission("team", "update")
    @broker.subscriber("rpc.tournament.reg_set_balancer_status")
    async def _reg_set_balancer_status(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            registration_id = _require_id(data)
            ws_id = await auth.get_registration_workspace_id(session, registration_id)
            ensure_workspace_permission(user, ws_id, "team", "update")
            body = admin_schemas.SetBalancerStatusRequest.model_validate(_payload(data))
            registration = await registration_service.set_balancer_status(
                session,
                registration_id,
                balancer_status=body.balancer_status,
            )
            status_meta_map = await get_status_metas_map(session, workspace_id=ws_id)
            await emit_balancer_registrations_changed(
                registration.tournament_id,
                workspace_id=ws_id,
                actor_user_id=user.id,
            )
            return _dump(serialize_registration(registration, workspace_id=ws_id, status_meta_map=status_meta_map))

        return await _run(logger, op)

    # POST /balancer/tournaments/{tournament_id}/registrations/bulk-add-to-balancer
    #   dep: require_tournament_permission("team", "import")
    @broker.subscriber("rpc.tournament.reg_bulk_add_balancer")
    async def _reg_bulk_add_balancer(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            ws_id = await auth.get_tournament_workspace_id(session, tournament_id)
            ensure_workspace_permission(user, ws_id, "team", "import")
            payload = _payload(data)
            registration_ids = _bulk_ids(payload)
            balancer_status = payload.get("balancer_status", "ready")
            updated, skipped = await registration_service.bulk_add_to_balancer(
                session,
                tournament_id,
                registration_ids,
                balancer_status=balancer_status,
            )
            if updated:
                await emit_balancer_registrations_changed(tournament_id, actor_user_id=user.id)
            return _dump(admin_schemas.BulkBalancerStatusResponse(updated=updated, skipped=skipped))

        return await _run(logger, op)

    # POST /balancer/tournaments/{tournament_id}/registrations/rank-autofill/preview
    #   dep: require_tournament_permission("team", "read")
    @broker.subscriber("rpc.tournament.reg_rank_autofill_preview")
    async def _reg_rank_autofill_preview(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            ws_id = await auth.get_tournament_workspace_id(session, tournament_id)
            ensure_workspace_permission(user, ws_id, "team", "read")
            body = admin_schemas.BalancerRegistrationRankAutofillRequest.model_validate(_payload(data))
            result = await registration_service.autofill_registration_ranks_from_parsed(
                session,
                tournament_id,
                registration_ids=body.registration_ids,
                overwrite_existing=body.overwrite_existing,
                add_to_balancer=body.add_to_balancer,
                allow_partial=body.allow_partial,
                mode=body.mode,
                stages=body.stages,
                apply=False,
            )
            return _dump(admin_schemas.BalancerRegistrationRankAutofillResponse(**result))

        return await _run(logger, op)

    # POST /balancer/tournaments/{tournament_id}/registrations/rank-autofill/apply
    #   dep: require_tournament_permission("team", "update")
    @broker.subscriber("rpc.tournament.reg_rank_autofill_apply")
    async def _reg_rank_autofill_apply(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            ws_id = await auth.get_tournament_workspace_id(session, tournament_id)
            ensure_workspace_permission(user, ws_id, "team", "update")
            body = admin_schemas.BalancerRegistrationRankAutofillRequest.model_validate(_payload(data))
            result = await registration_service.autofill_registration_ranks_from_parsed(
                session,
                tournament_id,
                registration_ids=body.registration_ids,
                overwrite_existing=body.overwrite_existing,
                add_to_balancer=body.add_to_balancer,
                allow_partial=body.allow_partial,
                mode=body.mode,
                stages=body.stages,
                apply=True,
            )
            await emit_balancer_registrations_changed(tournament_id, actor_user_id=user.id)
            return _dump(admin_schemas.BalancerRegistrationRankAutofillResponse(**result))

        return await _run(logger, op)

    # GET /balancer/users/{user_id}/registration-rank-history?workspace_id=
    #   dep: require_workspace_permission("team", "read")  -> ws from query workspace_id
    @broker.subscriber("rpc.tournament.reg_user_rank_history")
    async def _reg_user_rank_history(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            user_id = _path_int(data, "user_id")
            workspace_id = _q1(data, "workspace_id", int)
            if workspace_id is None:
                raise HTTPException(status_code=422, detail="workspace_id is required")
            ensure_workspace_permission(user, workspace_id, "team", "read")
            entries = await registration_service.load_user_balancer_rank_history(
                session,
                user_id=user_id,
                workspace_id=workspace_id,
            )
            return _dump(admin_schemas.BalancerRegistrationRankHistoryResponse(entries=entries))

        return await _run(logger, op)

    # POST /balancer/tournaments/{tournament_id}/registrations/export-users
    #   dep: require_tournament_permission("team", "import")
    @broker.subscriber("rpc.tournament.reg_export_users")
    async def _reg_export_users(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            ws_id = await auth.get_tournament_workspace_id(session, tournament_id)
            ensure_workspace_permission(user, ws_id, "team", "import")
            result = await registration_service.export_registrations_to_users(session, tournament_id)
            return _dump(admin_schemas.RegistrationUserExportResponse(**result))

        return await _run(logger, op)

    # PATCH /balancer/registrations/{registration_id}/check-in
    #   dep: require_registration_permission("team", "update")
    @broker.subscriber("rpc.tournament.reg_check_in")
    async def _reg_check_in(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            registration_id = _require_id(data)
            ws_id = await auth.get_registration_workspace_id(session, registration_id)
            ensure_workspace_permission(user, ws_id, "team", "update")
            body = admin_schemas.CheckInRequest.model_validate(_payload(data))
            if body.checked_in:
                registration = await registration_service.check_in_registration(
                    session,
                    registration_id,
                    checked_in_by=user.id,
                )
            else:
                registration = await registration_service.uncheck_in_registration(session, registration_id)
            status_meta_map = await get_status_metas_map(session, workspace_id=ws_id)
            await emit_balancer_registrations_changed(
                registration.tournament_id,
                workspace_id=ws_id,
                actor_user_id=user.id,
            )
            return _dump(serialize_registration(registration, workspace_id=ws_id, status_meta_map=status_meta_map))

        return await _run(logger, op)

    # ══════════════════════════════════════════════════════════════════════
    #  registration_status.py  (router prefix /ws/{workspace_id}/balancer-statuses)
    #  All deps: require_workspace_permission(...) -> ws from path workspace_id.
    # ══════════════════════════════════════════════════════════════════════

    # GET /ws/{workspace_id}/balancer-statuses/catalog
    #   dep: require_workspace_permission("team", "read")
    @broker.subscriber("rpc.tournament.regstatus_catalog")
    async def _regstatus_catalog(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            workspace_id = _path_int(data, "workspace_id")
            ensure_workspace_permission(user, workspace_id, "team", "read")
            statuses = await status_catalog.list_status_catalog(session, workspace_id)
            return [_dump(serialize_status(status_row)) for status_row in statuses]

        return await _run(logger, op)

    # GET /ws/{workspace_id}/balancer-statuses
    #   dep: require_workspace_permission("team", "read")
    @broker.subscriber("rpc.tournament.regstatus_list")
    async def _regstatus_list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            workspace_id = _path_int(data, "workspace_id")
            ensure_workspace_permission(user, workspace_id, "team", "read")
            statuses = await status_catalog.list_custom_statuses(session, workspace_id)
            return [_dump(serialize_status(status_row)) for status_row in statuses]

        return await _run(logger, op)

    # POST /ws/{workspace_id}/balancer-statuses/custom  (201)
    #   dep: require_workspace_permission("team", "update")
    @broker.subscriber("rpc.tournament.regstatus_create")
    async def _regstatus_create(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            workspace_id = _path_int(data, "workspace_id")
            ensure_workspace_permission(user, workspace_id, "team", "update")
            body = admin_schemas.BalancerRegistrationStatusCreate.model_validate(_payload(data))
            status_row = await status_catalog.create_custom_status(
                session,
                workspace_id=workspace_id,
                scope=body.scope,
                icon_slug=body.icon_slug,
                icon_color=body.icon_color,
                name=body.name,
                description=body.description,
            )
            return _dump(serialize_status(status_row))

        return await _run(logger, op)

    # PATCH /ws/{workspace_id}/balancer-statuses/custom/{status_id}
    #   dep: require_workspace_permission("team", "update")
    @broker.subscriber("rpc.tournament.regstatus_update")
    async def _regstatus_update(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            workspace_id = _path_int(data, "workspace_id")
            status_id = _path_int(data, "status_id")
            ensure_workspace_permission(user, workspace_id, "team", "update")
            body = admin_schemas.BalancerRegistrationStatusUpdate.model_validate(_payload(data))
            status_row = await status_catalog.update_custom_status(
                session,
                workspace_id=workspace_id,
                status_id=status_id,
                icon_slug=body.icon_slug,
                icon_color=body.icon_color,
                name=body.name,
                description=body.description,
            )
            return _dump(serialize_status(status_row))

        return await _run(logger, op)

    # DELETE /ws/{workspace_id}/balancer-statuses/custom/{status_id}  (204)
    #   dep: require_workspace_permission("team", "update")
    @broker.subscriber("rpc.tournament.regstatus_delete")
    async def _regstatus_delete(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            workspace_id = _path_int(data, "workspace_id")
            status_id = _path_int(data, "status_id")
            ensure_workspace_permission(user, workspace_id, "team", "update")
            await status_catalog.delete_custom_status(
                session,
                workspace_id=workspace_id,
                status_id=status_id,
            )
            return None

        return await _run(logger, op)

    # PUT /ws/{workspace_id}/balancer-statuses/system/{scope}/{slug}
    #   dep: require_workspace_permission("team", "update")
    @broker.subscriber("rpc.tournament.regstatus_builtin_upsert")
    async def _regstatus_builtin_upsert(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            workspace_id = _path_int(data, "workspace_id")
            ensure_workspace_permission(user, workspace_id, "team", "update")
            scope = _require_scope(data)
            slug = _require_slug(data)
            body = admin_schemas.BalancerRegistrationStatusUpdate.model_validate(_payload(data))
            status_row = await status_catalog.upsert_builtin_override(
                session,
                workspace_id=workspace_id,
                scope=scope,
                slug=slug,
                icon_slug=body.icon_slug,
                icon_color=body.icon_color,
                name=body.name,
                description=body.description,
            )
            return _dump(serialize_status(status_row))

        return await _run(logger, op)

    # DELETE /ws/{workspace_id}/balancer-statuses/system/{scope}/{slug}  (204)
    #   dep: require_workspace_permission("team", "update")
    @broker.subscriber("rpc.tournament.regstatus_builtin_reset")
    async def _regstatus_builtin_reset(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            workspace_id = _path_int(data, "workspace_id")
            ensure_workspace_permission(user, workspace_id, "team", "update")
            scope = _require_scope(data)
            slug = _require_slug(data)
            await status_catalog.reset_builtin_override(
                session,
                workspace_id=workspace_id,
                scope=scope,
                slug=slug,
            )
            return None

        return await _run(logger, op)
