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

Permission model — one helper per FastAPI dependency the routes used, each
returning the ``_Ctx`` (user, primary id, authorized workspace) the rest of the
handler works from. The workspace is threaded, never re-resolved, so what a
handler serializes for, broadcasts on and audits under is by construction the
workspace it was authorized against:
  * ``require_tournament_permission(res, act)`` -> ``_tournament_ctx``.
  * ``require_registration_permission(res, act)`` -> ``_registration_ctx``.
  * ``require_workspace_permission(res, act)`` -> ``_workspace_ctx`` (sync: the
    workspace IS the path param, so there is nothing to resolve).
  * ``reg_user_rank_history`` is the one exception — its workspace comes from a
    QUERY param, so it keeps the check inline.

Every per-registration mutation ends in ``_registration_response`` (status metas
-> realtime broadcast -> serialize) and stages its audit row through
``_stage_transition`` / ``_stage_bulk`` — see ``services/registration/audit.py``
for why staging happens before the service call.

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

from typing import Any, NamedTuple

from faststream.rabbit.annotations import RabbitMessage

from shared.balancer_registration_statuses import get_status_metas_map
from shared.core.errors import BaseAPIException as HTTPException
from shared.rpc.identity import ensure_workspace_permission
from shared.services.rank_snapshots import (
    fetch_latest_ow_ranks_by_account,
    normalize_ow_ranks_to_grid,
)
from shared.services.roster import roster_engine
from src import models, schemas
from src.core import auth
from src.domain.registration.ow_rank_selection import select_main_account_ow_ranks
from src.rpc._helpers import _bool, _dump, _identity, _path_int, _payload, _q1, _require_id, _run
from src.schemas.registration import (
    RegistrationFormUpsert,
    SubscriptionProviderConfigUpsert,
    WorkspaceSubscriptionRequirementUpsert,
)
from src.schemas.registration_build import AdmissionChips
from src.schemas.registration_team import (
    RegistrationTeamAdmissionRequest,
    RegistrationTeamListResponse,
    RegistrationTeamNotesRequest,
    RegistrationTeamPlaceMemberRequest,
    RegistrationTeamRejectRequest,
    RegistrationTeamRenameRequest,
)
from src.services.registration import _common as reg_common
from src.services.registration import audit as reg_audit
from src.services.registration import export as reg_export
from src.services.registration import (
    lifecycle,
    rank_autofill,
    rank_sources,
    status_catalog,
    subscription_config,
)
from src.services.registration import service as reg_svc
from src.services.registration import teams as team_service
from src.services.registration.realtime import emit_balancer_registrations_changed
from src.services.registration.serializers import (
    serialize_registration,
    serialize_registration_form,
    serialize_status,
)
from src.services.registration.windows import windows_service

# --- helpers -----------------------------------------------------------------

# Cap on bulk id lists — bulk operations must not
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


class _Ctx(NamedTuple):
    """What the authz preamble resolved: who, which row, and the workspace the
    permission was actually checked against.

    ``ws_id`` is threaded downstream rather than re-resolved, so the workspace a
    handler serializes for, broadcasts on and files its audit row under can never
    disagree with the one it was authorized against. ``id`` is the request's
    primary id -- a registration, a tournament or the workspace itself, depending
    on which of the three preambles below produced the context.
    """

    user: models.AuthUser
    id: int
    ws_id: int


async def _registration_ctx(session: Any, data: dict[str, Any], action: str, resource: str = "team") -> _Ctx:
    """``require_registration_permission(resource, action)``: workspace resolved
    from the registration in ``data["id"]`` (404s on a missing row)."""
    user = _identity(data)
    registration_id = _require_id(data)
    ws_id = await auth.get_registration_workspace_id(session, registration_id)
    ensure_workspace_permission(user, ws_id, resource, action)
    return _Ctx(user, registration_id, ws_id)


async def _tournament_ctx(session: Any, data: dict[str, Any], action: str, resource: str = "team") -> _Ctx:
    """``require_tournament_permission(resource, action)``: workspace resolved
    from the tournament in ``data["id"]`` (404s on a missing tournament)."""
    user = _identity(data)
    tournament_id = _require_id(data)
    ws_id = await auth.get_tournament_workspace_id(session, tournament_id)
    ensure_workspace_permission(user, ws_id, resource, action)
    return _Ctx(user, tournament_id, ws_id)


def _workspace_ctx(data: dict[str, Any], action: str, resource: str = "team") -> _Ctx:
    """``require_workspace_permission(resource, action)``: the workspace IS the
    path param, so there is nothing to resolve and no session to resolve it with
    -- hence sync, and ``id``/``ws_id`` are the same value by definition."""
    user = _identity(data)
    workspace_id = _path_int(data, "workspace_id")
    ensure_workspace_permission(user, workspace_id, resource, action)
    return _Ctx(user, workspace_id, workspace_id)


async def _registration_response(session: Any, ctx: _Ctx, registration: Any) -> Any:
    """The response every per-registration admin mutation returns.

    The signal is STAGED here, not published: the caller's own commit is what
    releases it, so a response body can never describe a broadcast that outlived
    a failed transaction.
    """
    status_meta_map = await get_status_metas_map(session, workspace_id=ctx.ws_id)
    await emit_balancer_registrations_changed(
        session,
        registration.tournament_id,
        actor_user_id=ctx.user.id,
    )
    # The lifecycle services commit their own writes, so this session is clean
    # by now: the commit here is what releases the staged event (the rail stages
    # on before_commit precisely so a clean session still publishes).
    await session.commit()
    rosters = await roster_engine.resolve(session, [registration], workspace_id=ctx.ws_id)
    return _dump(
        serialize_registration(
            registration,
            workspace_id=ctx.ws_id,
            status_meta_map=status_meta_map,
            roster=rosters.get(registration.id),
        )
    )


async def _stage_transition(
    session: Any,
    data: dict[str, Any],
    ctx: _Ctx,
    *,
    action: str,
    after: dict[str, Any],
) -> None:
    """Stage the audit row for a lifecycle transition on one registration.

    Reads the row first, so ``before`` is the state actually being left and the
    feed carries the registration's name rather than only its id. ``before`` is
    narrowed to the same keys ``after`` names: the journal records a transition,
    not a snapshot of the row. Staged before the service runs -- see
    ``services/registration/audit.py`` on call order.
    """
    current = await lifecycle.lifecycle_service.get_registration_by_id(session, ctx.id)
    await reg_audit.audit_service.stage(
        session,
        action=action,
        actor=ctx.user,
        workspace_id=ctx.ws_id,
        data=data,
        entity_id=ctx.id,
        entity_label=reg_audit.label(current),
        before={field: getattr(current, field) for field in after},
        after=after,
    )


async def _stage_bulk(session: Any, data: dict[str, Any], ctx: _Ctx, *, action: str, after: dict[str, Any]) -> None:
    """Stage the audit row for a request that touches many registrations at once.

    Filed on the TOURNAMENT (``ctx.id``), never fanned out per registration: it is
    one request over many rows, and a row each would bury every single-registration
    edit in the same feed. ``after`` names what was REQUESTED -- which ids actually
    qualified is only known once the service has committed, and by then the row can
    no longer ride its transaction.
    """
    await reg_audit.audit_service.stage(
        session,
        action=action,
        actor=ctx.user,
        workspace_id=ctx.ws_id,
        data=data,
        entity_id=ctx.id,
        entity_type="tournament",
        after=after,
    )


def register(broker: Any, logger: Any) -> None:
    # ══════════════════════════════════════════════════════════════════════
    #  registration.py  (router prefix /balancer)
    # ══════════════════════════════════════════════════════════════════════

    # GET /balancer/tournaments/{tournament_id}/registration-form
    #   dep: require_tournament_permission("team", "read")
    @broker.subscriber("rpc.tournament.reg_form_get")
    async def _reg_form_get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            ctx = await _tournament_ctx(session, data, "read")
            form = await reg_common._common_service.get_registration_form(session, ctx.id)
            if form is None:
                return None
            # The rule is the workspace's now; one scalar read feeds the sync serializer.
            requirement = await subscription_config.subscription_config_service.load_workspace_requirement_blob(
                session, ctx.ws_id
            )
            is_open = await windows_service.load_registration_open(session, ctx.id)
            return _dump(serialize_registration_form(form, is_open=is_open, subscription_requirement=requirement))

        return await _run(logger, op)

    # PUT /balancer/tournaments/{tournament_id}/registration-form
    #   dep: require_tournament_permission("team", "create")
    @broker.subscriber("rpc.tournament.reg_form_upsert")
    async def _reg_form_upsert(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            ctx = await _tournament_ctx(session, data, "create")
            body = RegistrationFormUpsert.model_validate(_payload(data))
            # _tournament_ctx already 404s on a missing tournament;
            # upsert_registration_form commits internally.
            form = await reg_svc.registration_service.upsert_registration_form(
                session, ctx.id, body, workspace_id=ctx.ws_id
            )
            requirement = await subscription_config.subscription_config_service.load_workspace_requirement_blob(
                session, ctx.ws_id
            )
            is_open = await windows_service.load_registration_open(session, ctx.id)
            return _dump(serialize_registration_form(form, is_open=is_open, subscription_requirement=requirement))

        return await _run(logger, op)

    # GET /balancer/tournaments/{tournament_id}/registration-teams
    #   dep: require_tournament_permission("team", "read")
    #
    # §8/§12.5: the organizer's answer to "who is incomplete, and what are they
    # missing?". Occupancy is recomputed rather than read off the denormalized
    # ``status`` column, because the per-slot shortfall is what is actionable.
    @broker.subscriber("rpc.tournament.regteam_list")
    async def _regteam_list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            ctx = await _tournament_ctx(session, data, "read")
            # `_q1`, not `data.get`: `AllQuery` nests the query string, so a direct
            # lookup would silently read `False` for every request.
            include_terminal = _q1(data, "include_terminal", _bool, default=False)
            pairs = await team_service.teams_service.list_teams(
                session,
                tournament_id=ctx.id,
                include_terminal=include_terminal,
            )
            items = [
                await team_service.teams_service.describe_team(
                    session, team, include_invites=True, include_staff=True
                )
                for team, _occupancy in pairs
            ]
            # The number the organizer must see before pressing export: these
            # players are on no team, so the export cannot place them.
            return _dump(
                RegistrationTeamListResponse(
                    items=items,
                    total=len(items),
                    unassigned_players=await team_service.teams_service.count_unassigned_players(session, ctx.id),
                )
            )

        return await _run(logger, op)

    # POST /balancer/tournaments/{tournament_id}/registration-teams/{team_id}/reject
    #   dep: require_tournament_permission("team", "update")
    @broker.subscriber("rpc.tournament.regteam_reject")
    async def _regteam_reject(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            ctx = await _tournament_ctx(session, data, "update")
            body = RegistrationTeamRejectRequest.model_validate(_payload(data) or {})
            team_id = _path_int(data, "team_id")
            # Staged before the service, as everywhere else here: reject_team owns
            # its commit, so a row added after it would ride a second transaction.
            await reg_audit.audit_service.stage(
                session,
                action="registration_team.reject",
                actor=ctx.user,
                workspace_id=ctx.ws_id,
                data=data,
                entity_id=team_id,
                entity_type="registration_team",
                after={
                    "status": "rejected",
                    "tournament_id": ctx.id,
                    "withdraw_members": body.withdraw_members,
                    "reason": body.reason,
                },
            )
            team = await team_service.teams_service.reject_team(
                session,
                tournament_id=ctx.id,
                team_id=team_id,
                auth_user=ctx.user,
                withdraw_members=body.withdraw_members,
                reason=body.reason,
            )
            return _dump(
                await team_service.teams_service.describe_team(
                    session, team, include_invites=True, include_staff=True
                )
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.regteam_invite_revoke_admin")
    async def _regteam_invite_revoke_admin(data: dict, msg: RabbitMessage) -> dict:
        """An organizer withdraws an offer from a team they do not captain.

        A genuinely new privilege over someone else's roster, so the write records
        who did it. ``"update"`` rather than a bespoke action: it is the same power
        as rejecting a team, one rung smaller.

        The service re-checks that the invite belongs to THIS tournament. An invite
        id is global while this permission is not, so without that an organizer of
        any tournament could pass any id.
        """

        async def op(session: Any) -> Any:
            ctx = await _tournament_ctx(session, data, "update")
            invite_id = _path_int(data, "invite_id")
            # Filed on the TOURNAMENT: an invite id is all this request carries, and
            # resolving its team would cost a read the service is about to do anyway
            # (and would 404 on the same row). The invite is named in `after`.
            await reg_audit.audit_service.stage(
                session,
                action="registration_team.invite_revoke",
                actor=ctx.user,
                workspace_id=ctx.ws_id,
                data=data,
                entity_id=ctx.id,
                entity_type="tournament",
                after={"invite_id": invite_id, "state": "revoked", "by_organizer": True},
            )
            await team_service.teams_service.revoke_invite_as_organizer(
                session,
                invite_id=invite_id,
                tournament_id=ctx.id,
                auth_user=ctx.user,
            )
            return None

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.regteam_invite_cap_reset")
    async def _regteam_invite_cap_reset(data: dict, msg: RabbitMessage) -> dict:
        """Forgive a team's cumulative invite count.

        The recourse the cap's own error message names. Before this it named an
        intervention no endpoint provided, so a captain at the ceiling was simply
        stuck and the organizer they were sent to was powerless.
        """

        async def op(session: Any) -> Any:
            ctx = await _tournament_ctx(session, data, "update")
            team_id = _path_int(data, "team_id")
            await reg_audit.audit_service.stage(
                session,
                action="registration_team.invite_cap_reset",
                actor=ctx.user,
                workspace_id=ctx.ws_id,
                data=data,
                entity_id=team_id,
                entity_type="registration_team",
                after={"tournament_id": ctx.id},
            )
            await team_service.teams_service.reset_invite_cap(
                session,
                team_id=team_id,
                tournament_id=ctx.id,
                auth_user=ctx.user,
            )
            return None

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.regteam_invite_history")
    async def _regteam_invite_history(data: dict, msg: RabbitMessage) -> dict:
        """Every invite a team ever issued, with its cap standing.

        Read-scoped to organizers here; the captain reads the same history through
        the public handler, which authorizes by captaincy instead.
        """

        async def op(session: Any) -> Any:
            await _tournament_ctx(session, data, "read")
            return _dump(
                await team_service.teams_service.list_invite_history(session, team_id=_path_int(data, "team_id"))
            )

        return await _run(logger, op)


    async def _staff_team_dump(session: Any, team: Any) -> Any:
        return _dump(
            await team_service.teams_service.describe_team(
                session, team, include_invites=True, include_staff=True
            )
        )

    @broker.subscriber("rpc.tournament.regteam_rename_admin")
    async def _regteam_rename_admin(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            ctx = await _tournament_ctx(session, data, "update")
            body = RegistrationTeamRenameRequest.model_validate(_payload(data))
            team_id = _path_int(data, "team_id")
            await reg_audit.audit_service.stage(
                session,
                action="registration_team.rename",
                actor=ctx.user,
                workspace_id=ctx.ws_id,
                data=data,
                entity_id=team_id,
                entity_type="registration_team",
                after={"tournament_id": ctx.id, "name": body.name},
            )
            team = await team_service.teams_service.rename_team(
                session,
                team_id=team_id,
                auth_user=ctx.user,
                name=body.name,
                as_organizer=True,
                tournament_id=ctx.id,
            )
            return await _staff_team_dump(session, team)

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.regteam_unlock")
    async def _regteam_unlock(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            ctx = await _tournament_ctx(session, data, "update")
            team_id = _path_int(data, "team_id")
            await reg_audit.audit_service.stage(
                session,
                action="registration_team.unlock",
                actor=ctx.user,
                workspace_id=ctx.ws_id,
                data=data,
                entity_id=team_id,
                entity_type="registration_team",
                after={"tournament_id": ctx.id},
            )
            team = await team_service.teams_service.unlock_roster(
                session,
                tournament_id=ctx.id,
                team_id=team_id,
                auth_user=ctx.user,
            )
            return await _staff_team_dump(session, team)

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.regteam_admission")
    async def _regteam_admission(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            ctx = await _tournament_ctx(session, data, "update")
            body = RegistrationTeamAdmissionRequest.model_validate(_payload(data))
            team_id = _path_int(data, "team_id")
            await reg_audit.audit_service.stage(
                session,
                action="registration_team.admission",
                actor=ctx.user,
                workspace_id=ctx.ws_id,
                data=data,
                entity_id=team_id,
                entity_type="registration_team",
                after={"tournament_id": ctx.id, "admission": body.admission},
            )
            team = await team_service.teams_service.set_admission(
                session,
                tournament_id=ctx.id,
                team_id=team_id,
                admission=body.admission,
                auth_user=ctx.user,
            )
            return await _staff_team_dump(session, team)

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.regteam_notes")
    async def _regteam_notes(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            ctx = await _tournament_ctx(session, data, "update")
            body = RegistrationTeamNotesRequest.model_validate(_payload(data) or {})
            team_id = _path_int(data, "team_id")
            await reg_audit.audit_service.stage(
                session,
                action="registration_team.notes",
                actor=ctx.user,
                workspace_id=ctx.ws_id,
                data=data,
                entity_id=team_id,
                entity_type="registration_team",
                after={"tournament_id": ctx.id},
            )
            team = await team_service.teams_service.set_organizer_notes(
                session,
                tournament_id=ctx.id,
                team_id=team_id,
                notes=body.notes,
            )
            return await _staff_team_dump(session, team)

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.regteam_place_admin")
    async def _regteam_place_admin(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            ctx = await _tournament_ctx(session, data, "update")
            body = RegistrationTeamPlaceMemberRequest.model_validate(_payload(data) or {})
            team_id = _path_int(data, "team_id")
            registration_id = _path_int(data, "registration_id")
            await reg_audit.audit_service.stage(
                session,
                action="registration_team.place",
                actor=ctx.user,
                workspace_id=ctx.ws_id,
                data=data,
                entity_id=team_id,
                entity_type="registration_team",
                after={
                    "tournament_id": ctx.id,
                    "registration_id": registration_id,
                    "slot_code": body.slot_code,
                    "is_substitute": body.is_substitute,
                },
            )
            team = await team_service.teams_service.place_member_as_organizer(
                session,
                tournament_id=ctx.id,
                team_id=team_id,
                registration_id=registration_id,
                slot_code=body.slot_code,
                is_substitute=body.is_substitute,
            )
            return await _staff_team_dump(session, team)

        return await _run(logger, op)

    # GET /balancer/tournaments/{tournament_id}/registrations
    #   dep: require_tournament_permission("team", "read")
    #   FAT handler: list + status-meta map + per-registration OW-rank snapshot join.
    @broker.subscriber("rpc.tournament.reg_list")
    async def _reg_list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            ctx = await _tournament_ctx(session, data, "read")

            status_filter = _q1(data, "status_filter")
            inclusion_filter = _q1(data, "inclusion_filter")
            source_filter = _q1(data, "source_filter")
            include_deleted = _q1(data, "include_deleted", _bool, default=False)

            registrations = await lifecycle.lifecycle_service.list_registrations(
                session,
                ctx.id,
                status_filter=status_filter,
                inclusion_filter=inclusion_filter,
                source_filter=source_filter,
                include_deleted=include_deleted,
            )
            status_meta_map = await get_status_metas_map(session, workspace_id=ctx.ws_id) if registrations else None
            # Registrations are anchored on workspace_member (eager-loaded by
            # list_registrations); the player id is the member's player_id.
            user_ids = [r.workspace_member.player_id for r in registrations if r.workspace_member is not None]
            grid = await reg_common._common_service.get_tournament_grid(session, ctx.id)
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
            # The form and the grid are already in hand, so the engine reuses them
            # instead of re-reading either; this is the same roster the balancer
            # payload and the draft pool are built from.
            form = await reg_common._common_service.get_registration_form(session, ctx.id)
            rosters = await roster_engine.resolve(
                session, registrations, workspace_id=ctx.ws_id, tournament_id=ctx.id, form=form, grid=grid
            )
            # Same resolution the public participants list uses, so the admin
            # Admission / Subscription / Profile columns are byte-identical to what
            # the player sees on their own card.
            admissions = await reg_svc.registration_service.resolve_admission_list(session, registrations, form=form)
            out = []
            for registration in registrations:
                chips = AdmissionChips.of(admissions.get(registration.id))
                out.append(
                    _dump(
                        serialize_registration(
                            registration,
                            workspace_id=ctx.ws_id,
                            status_meta_map=status_meta_map,
                            ow_ranks_for_user=ow_ranks.get(registration.id),
                            admission=chips.admission,
                            profiles_open=chips.profiles_open,
                            subscription_outcome=chips.subscription_outcome,
                            roster=rosters.get(registration.id),
                        )
                    )
                )
            return out

        return await _run(logger, op)

    # POST /balancer/tournaments/{tournament_id}/registrations  (201)
    #   dep: require_tournament_permission("team", "create")
    @broker.subscriber("rpc.tournament.reg_create_manual")
    async def _reg_create_manual(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            ctx = await _tournament_ctx(session, data, "create")
            body = schemas.BalancerRegistrationCreateRequest.model_validate(_payload(data))

            await reg_common._common_service.ensure_tournament_exists(session, ctx.id)
            registration = await lifecycle.lifecycle_service.create_manual_registration(
                session,
                tournament_id=ctx.id,
                display_name=body.display_name,
                battle_tag=body.battle_tag,
                smurf_tags_json=body.smurf_tags_json,
                discord_nick=body.discord_nick,
                twitch_nick=body.twitch_nick,
                boosty_nick=body.boosty_nick,
                stream_pov=body.stream_pov,
                notes=body.notes,
                admin_notes=body.admin_notes,
                custom_fields_json=body.custom_fields_json,
                status_value=body.status,
                balancer_status_value=body.balancer_status,
                roles=[role.model_dump() for role in body.roles],
                auth_user_id=body.auth_user_id,
            )
            # ponytail: this row lands in a second transaction, unlike every other
            # call in this module. The id it names does not exist until the service
            # has run, and the service owns its commit, so there is no moment that
            # is both after the id and inside the write's transaction (same
            # trade-off as shared.rpc.crud's service-backed create). Ceiling: a
            # crash between the two commits loses the trail, never the other way
            # round.
            await reg_audit.audit_service.stage(
                session,
                action="registration.create",
                actor=ctx.user,
                workspace_id=ctx.ws_id,
                data=data,
                entity_id=registration.id,
                entity_label=reg_audit.label(registration),
                after={
                    "battle_tag": registration.battle_tag,
                    "status": registration.status,
                    "balancer_status": registration.balancer_status,
                    "roles": reg_audit.role_snapshot(registration),
                },
            )
            await session.commit()
            return await _registration_response(session, ctx, registration)

        return await _run(logger, op)

    # PATCH /balancer/registrations/{registration_id}
    #   dep: require_registration_permission("team", "update")
    @broker.subscriber("rpc.tournament.reg_update")
    async def _reg_update(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            ctx = await _registration_ctx(session, data, "update")
            body = schemas.BalancerRegistrationUpdateRequest.model_validate(_payload(data))
            # Staged before the service so the row rides the transaction it
            # commits. A save that changes nothing writes no row: the editor
            # round-trips its whole form, and a journal of no-ops is a journal
            # nobody reads.
            current = await lifecycle.lifecycle_service.get_registration_by_id(session, ctx.id)
            before, after = reg_audit.profile_changes(current, body.model_dump())
            if before or after:
                await reg_audit.audit_service.stage(
                    session,
                    action="registration.update",
                    actor=ctx.user,
                    workspace_id=ctx.ws_id,
                    data=data,
                    entity_id=ctx.id,
                    entity_label=reg_audit.label(current),
                    before=before,
                    after=after,
                )

            registration = await lifecycle.lifecycle_service.update_registration_profile(
                session,
                ctx.id,
                display_name=body.display_name,
                battle_tag=body.battle_tag,
                smurf_tags_json=body.smurf_tags_json,
                discord_nick=body.discord_nick,
                twitch_nick=body.twitch_nick,
                boosty_nick=body.boosty_nick,
                stream_pov=body.stream_pov,
                notes=body.notes,
                admin_notes=body.admin_notes,
                custom_fields_json=body.custom_fields_json,
                status_value=body.status,
                balancer_status_value=body.balancer_status,
                roles=[role.model_dump() for role in body.roles] if body.roles is not None else None,
                auth_user_id=body.auth_user_id,
                exclude_reason=body.exclude_reason,
                pin=body.pin,
                clear_pin=body.clear_pin,
            )
            return await _registration_response(session, ctx, registration)

        return await _run(logger, op)

    # PATCH /balancer/registrations/{registration_id}/approve
    #   dep: require_registration_permission("team", "create")
    @broker.subscriber("rpc.tournament.reg_approve")
    async def _reg_approve(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            ctx = await _registration_ctx(session, data, "create")
            await _stage_transition(session, data, ctx, action="registration.approve", after={"status": "approved"})
            registration = await lifecycle.lifecycle_service.approve_registration(
                session,
                ctx.id,
                reviewed_by=ctx.user.id,
            )
            return await _registration_response(session, ctx, registration)

        return await _run(logger, op)

    # PATCH /balancer/registrations/{registration_id}/reject
    #   dep: require_registration_permission("team", "create")
    @broker.subscriber("rpc.tournament.reg_reject")
    async def _reg_reject(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            ctx = await _registration_ctx(session, data, "create")
            await _stage_transition(session, data, ctx, action="registration.reject", after={"status": "rejected"})
            registration = await lifecycle.lifecycle_service.reject_registration(
                session,
                ctx.id,
                reviewed_by=ctx.user.id,
            )
            return await _registration_response(session, ctx, registration)

        return await _run(logger, op)

    # POST /balancer/registrations/{registration_id}/include
    #   dep: require_registration_permission("team", "update")
    @broker.subscriber("rpc.tournament.reg_include_balancer")
    async def _reg_include_balancer(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            ctx = await _registration_ctx(session, data, "update")
            # The balancer status this lands on is derived from the resolved
            # roster, so the after-image reuses the very function the service
            # applies. Hence the explicit stage instead of _stage_transition: the
            # after-value is computed, not a literal.
            current = await lifecycle.lifecycle_service.get_registration_by_id(session, ctx.id)
            await reg_audit.audit_service.stage(
                session,
                action="registration.balancer_include",
                actor=ctx.user,
                workspace_id=ctx.ws_id,
                data=data,
                entity_id=ctx.id,
                entity_label=reg_audit.label(current),
                before={
                    "balancer_status": current.balancer_status,
                    "exclude_reason": current.exclude_reason,
                },
                after={
                    "balancer_status": reg_common.included_balancer_status(
                        await reg_common.resolve_roster(session, current)
                    ),
                    "exclude_reason": None,
                },
            )
            registration = await lifecycle.lifecycle_service.add_to_balancer(session, ctx.id)
            return await _registration_response(session, ctx, registration)

        return await _run(logger, op)

    # PATCH /balancer/registrations/{registration_id}/withdraw
    #   dep: require_registration_permission("team", "update")
    @broker.subscriber("rpc.tournament.reg_withdraw")
    async def _reg_withdraw(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            ctx = await _registration_ctx(session, data, "update")
            await _stage_transition(session, data, ctx, action="registration.withdraw", after={"status": "withdrawn"})
            registration = await lifecycle.lifecycle_service.withdraw_registration(session, ctx.id)
            return await _registration_response(session, ctx, registration)

        return await _run(logger, op)

    # PATCH /balancer/registrations/{registration_id}/restore
    #   dep: require_registration_permission("team", "update")
    @broker.subscriber("rpc.tournament.reg_restore")
    async def _reg_restore(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            ctx = await _registration_ctx(session, data, "update")
            await _stage_transition(session, data, ctx, action="registration.restore", after={"status": "approved"})
            registration = await lifecycle.lifecycle_service.restore_registration(session, ctx.id)
            return await _registration_response(session, ctx, registration)

        return await _run(logger, op)

    # DELETE /balancer/registrations/{registration_id}  (204)
    #   dep: require_registration_permission("team", "create")
    @broker.subscriber("rpc.tournament.reg_delete")
    async def _reg_delete(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            ctx = await _registration_ctx(session, data, "create")
            # One read instead of a tournament_id-only scalar select: the audit row
            # needs the name and status being removed anyway, and
            # soft_delete_registration 404s on a missing id either way.
            current = await lifecycle.lifecycle_service.get_registration_by_id(session, ctx.id)
            await reg_audit.audit_service.stage(
                session,
                action="registration.delete",
                actor=ctx.user,
                workspace_id=ctx.ws_id,
                data=data,
                entity_id=ctx.id,
                entity_label=reg_audit.label(current),
                before={"status": current.status, "balancer_status": current.balancer_status},
            )
            tournament_id = current.tournament_id
            await lifecycle.lifecycle_service.soft_delete_registration(
                session,
                ctx.id,
                deleted_by=ctx.user.id,
            )
            await emit_balancer_registrations_changed(session, tournament_id, actor_user_id=ctx.user.id)
            await session.commit()
            return None

        return await _run(logger, op)

    # POST /balancer/tournaments/{tournament_id}/registrations/bulk-approve
    #   dep: require_tournament_permission("team", "create")
    @broker.subscriber("rpc.tournament.reg_bulk_approve")
    async def _reg_bulk_approve(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            ctx = await _tournament_ctx(session, data, "create")
            registration_ids = _bulk_ids(_payload(data))
            await _stage_bulk(
                session,
                data,
                ctx,
                action="registration.bulk_approve",
                after={"status": "approved", "registration_ids": registration_ids},
            )
            approved, skipped = await lifecycle.lifecycle_service.bulk_approve_registrations(
                session,
                ctx.id,
                registration_ids,
                reviewed_by=ctx.user.id,
            )
            if approved:
                await emit_balancer_registrations_changed(session, ctx.id, actor_user_id=ctx.user.id)
                await session.commit()
            return _dump(schemas.BulkApproveResponse(approved=approved, skipped=skipped))

        return await _run(logger, op)

    # PATCH /balancer/registrations/{registration_id}/balancer-status
    #   dep: require_registration_permission("team", "update")
    @broker.subscriber("rpc.tournament.reg_set_balancer_status")
    async def _reg_set_balancer_status(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            ctx = await _registration_ctx(session, data, "update")
            body = schemas.SetBalancerStatusRequest.model_validate(_payload(data))
            await _stage_transition(
                session,
                data,
                ctx,
                action="registration.balancer_status",
                after={
                    "balancer_status": body.balancer_status,
                    "exclude_reason": body.exclude_reason,
                },
            )
            registration = await lifecycle.lifecycle_service.set_balancer_status(
                session,
                ctx.id,
                balancer_status=body.balancer_status,
                exclude_reason=body.exclude_reason,
            )
            return await _registration_response(session, ctx, registration)

        return await _run(logger, op)

    # POST /balancer/tournaments/{tournament_id}/registrations/bulk-add-to-balancer
    #   dep: require_tournament_permission("team", "create")
    @broker.subscriber("rpc.tournament.reg_bulk_add_balancer")
    async def _reg_bulk_add_balancer(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            ctx = await _tournament_ctx(session, data, "create")
            registration_ids = _bulk_ids(_payload(data))
            await _stage_bulk(
                session,
                data,
                ctx,
                action="registration.bulk_balancer_include",
                after={"registration_ids": registration_ids},
            )
            updated, skipped = await lifecycle.lifecycle_service.bulk_add_to_balancer(
                session,
                ctx.id,
                registration_ids,
            )
            if updated:
                await emit_balancer_registrations_changed(session, ctx.id, actor_user_id=ctx.user.id)
                await session.commit()
            return _dump(schemas.BulkBalancerStatusResponse(updated=updated, skipped=skipped))

        return await _run(logger, op)

    # POST /balancer/tournaments/{tournament_id}/registrations/bulk-set-balancer-status
    #   dep: require_tournament_permission("team", "update")
    @broker.subscriber("rpc.tournament.reg_bulk_set_balancer_status")
    async def _reg_bulk_set_balancer_status(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            ctx = await _tournament_ctx(session, data, "update")
            body = schemas.BulkSetBalancerStatusRequest.model_validate(_payload(data))
            await _stage_bulk(
                session,
                data,
                ctx,
                action="registration.bulk_balancer_status",
                after={
                    "balancer_status": body.balancer_status,
                    "exclude_reason": body.exclude_reason,
                    "registration_ids": body.registration_ids,
                },
            )
            updated, skipped = await lifecycle.lifecycle_service.bulk_set_balancer_status(
                session,
                ctx.id,
                body.registration_ids,
                balancer_status=body.balancer_status,
                exclude_reason=body.exclude_reason,
            )
            if updated:
                await emit_balancer_registrations_changed(session, ctx.id, actor_user_id=ctx.user.id)
                await session.commit()
            return _dump(schemas.BulkBalancerStatusResponse(updated=updated, skipped=skipped))

        return await _run(logger, op)

    # POST /balancer/tournaments/{tournament_id}/registrations/rank-autofill/preview
    #   dep: require_tournament_permission("team", "read")
    @broker.subscriber("rpc.tournament.reg_rank_autofill_preview")
    async def _reg_rank_autofill_preview(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            ctx = await _tournament_ctx(session, data, "read")
            body = schemas.BalancerRegistrationRankAutofillRequest.model_validate(_payload(data))
            result = await rank_autofill.rank_autofill_service.autofill_registration_ranks_from_parsed(
                session,
                ctx.id,
                registration_ids=body.registration_ids,
                overwrite_existing=body.overwrite_existing,
                add_to_balancer=body.add_to_balancer,
                allow_partial=body.allow_partial,
                mode=body.mode,
                stages=body.stages,
                apply=False,
            )
            return _dump(schemas.BalancerRegistrationRankAutofillResponse(**result))

        return await _run(logger, op)

    # POST /balancer/tournaments/{tournament_id}/registrations/rank-autofill/apply
    #   dep: require_tournament_permission("team", "update")
    @broker.subscriber("rpc.tournament.reg_rank_autofill_apply")
    async def _reg_rank_autofill_apply(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            ctx = await _tournament_ctx(session, data, "update")
            body = schemas.BalancerRegistrationRankAutofillRequest.model_validate(_payload(data))
            # Rank autofill rewrites the numbers the balancer sorts on, across as
            # many registrations as the request names, so the parameters it ran
            # with are the audit. `registration_ids: None` means every
            # registration in the tournament (the service's own default).
            await _stage_bulk(
                session,
                data,
                ctx,
                action="registration.rank_autofill",
                after={
                    "registration_ids": body.registration_ids,
                    "overwrite_existing": body.overwrite_existing,
                    "add_to_balancer": body.add_to_balancer,
                    "mode": body.mode,
                    "stages": [stage.model_dump() for stage in body.stages] if body.stages else None,
                },
            )
            result = await rank_autofill.rank_autofill_service.autofill_registration_ranks_from_parsed(
                session,
                ctx.id,
                registration_ids=body.registration_ids,
                overwrite_existing=body.overwrite_existing,
                add_to_balancer=body.add_to_balancer,
                allow_partial=body.allow_partial,
                mode=body.mode,
                stages=body.stages,
                apply=True,
            )
            await emit_balancer_registrations_changed(session, ctx.id, actor_user_id=ctx.user.id)
            await session.commit()
            return _dump(schemas.BalancerRegistrationRankAutofillResponse(**result))

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
            entries = await rank_sources.rank_sources_service.load_user_balancer_rank_history(
                session,
                user_id=user_id,
                workspace_id=workspace_id,
            )
            return _dump(schemas.BalancerRegistrationRankHistoryResponse(entries=entries))

        return await _run(logger, op)

    # POST /balancer/tournaments/{tournament_id}/registrations/export-users
    #   dep: require_tournament_permission("team", "create")
    @broker.subscriber("rpc.tournament.reg_export_users")
    async def _reg_export_users(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            ctx = await _tournament_ctx(session, data, "create")
            result = await reg_export.export_service.export_registrations_to_users(session, ctx.id)
            return _dump(schemas.RegistrationUserExportResponse(**result))

        return await _run(logger, op)

    # PATCH /balancer/registrations/{registration_id}/check-in
    #   dep: require_registration_permission("team", "update")
    @broker.subscriber("rpc.tournament.reg_check_in")
    async def _reg_check_in(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            ctx = await _registration_ctx(session, data, "update")
            body = schemas.CheckInRequest.model_validate(_payload(data))
            await _stage_transition(
                session,
                data,
                ctx,
                action="registration.check_in" if body.checked_in else "registration.check_in_undo",
                after={"checked_in": body.checked_in},
            )
            if body.checked_in:
                registration = await lifecycle.lifecycle_service.check_in_registration(
                    session,
                    ctx.id,
                    checked_in_by=ctx.user.id,
                )
            else:
                registration = await lifecycle.lifecycle_service.uncheck_in_registration(session, ctx.id)
            return await _registration_response(session, ctx, registration)

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
            ctx = _workspace_ctx(data, "read")
            statuses = await status_catalog.status_catalog_service.list_status_catalog(session, ctx.ws_id)
            return [_dump(serialize_status(status_row)) for status_row in statuses]

        return await _run(logger, op)

    # GET /ws/{workspace_id}/balancer-statuses
    #   dep: require_workspace_permission("team", "read")
    @broker.subscriber("rpc.tournament.regstatus_list")
    async def _regstatus_list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            ctx = _workspace_ctx(data, "read")
            statuses = await status_catalog.status_catalog_service.list_custom_statuses(session, ctx.ws_id)
            return [_dump(serialize_status(status_row)) for status_row in statuses]

        return await _run(logger, op)

    # POST /ws/{workspace_id}/balancer-statuses/custom  (201)
    #   dep: require_workspace_permission("team", "update")
    @broker.subscriber("rpc.tournament.regstatus_create")
    async def _regstatus_create(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            ctx = _workspace_ctx(data, "update")
            body = schemas.BalancerRegistrationStatusCreate.model_validate(_payload(data))
            # Staged before the service, like every other write here: the service
            # owns its commit, so the row rides that transaction. The trade-off is
            # `entity_id`: the id does not exist yet, so the row carries the name
            # instead rather than landing in a second transaction to learn it.
            await reg_audit.audit_service.stage(
                session,
                action="registration_status.create",
                actor=ctx.user,
                workspace_id=ctx.ws_id,
                data=data,
                entity_id=None,
                entity_type="registration_status",
                entity_label=body.name,
                after={
                    "scope": body.scope,
                    "name": body.name,
                    "excludes_from_balancer": body.excludes_from_balancer,
                    "excludes_from_ready": body.excludes_from_ready,
                },
            )
            status_row = await status_catalog.status_catalog_service.create_custom_status(
                session,
                workspace_id=ctx.ws_id,
                scope=body.scope,
                icon_slug=body.icon_slug,
                icon_color=body.icon_color,
                name=body.name,
                description=body.description,
                excludes_from_balancer=body.excludes_from_balancer,
                excludes_from_ready=body.excludes_from_ready,
            )
            return _dump(serialize_status(status_row))

        return await _run(logger, op)

    # PATCH /ws/{workspace_id}/balancer-statuses/custom/{status_id}
    #   dep: require_workspace_permission("team", "update")
    @broker.subscriber("rpc.tournament.regstatus_update")
    async def _regstatus_update(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            ctx = _workspace_ctx(data, "update")
            status_id = _path_int(data, "status_id")
            body = schemas.BalancerRegistrationStatusUpdate.model_validate(_payload(data))
            # `exclude_none` is the change set, not a shortcut: the service treats a
            # None as "leave this field alone", so dumping them would file fields the
            # request never touched as if it had set them to null.
            await reg_audit.audit_service.stage(
                session,
                action="registration_status.update",
                actor=ctx.user,
                workspace_id=ctx.ws_id,
                data=data,
                entity_id=status_id,
                entity_type="registration_status",
                after=body.model_dump(exclude_none=True),
            )
            status_row = await status_catalog.status_catalog_service.update_custom_status(
                session,
                workspace_id=ctx.ws_id,
                status_id=status_id,
                icon_slug=body.icon_slug,
                icon_color=body.icon_color,
                name=body.name,
                description=body.description,
                excludes_from_balancer=body.excludes_from_balancer,
                excludes_from_ready=body.excludes_from_ready,
            )
            return _dump(serialize_status(status_row))

        return await _run(logger, op)

    # DELETE /ws/{workspace_id}/balancer-statuses/custom/{status_id}  (204)
    #   dep: require_workspace_permission("team", "update")
    @broker.subscriber("rpc.tournament.regstatus_delete")
    async def _regstatus_delete(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            ctx = _workspace_ctx(data, "update")
            status_id = _path_int(data, "status_id")
            await reg_audit.audit_service.stage(
                session,
                action="registration_status.delete",
                actor=ctx.user,
                workspace_id=ctx.ws_id,
                data=data,
                entity_id=status_id,
                entity_type="registration_status",
            )
            await status_catalog.status_catalog_service.delete_custom_status(
                session,
                workspace_id=ctx.ws_id,
                status_id=status_id,
            )
            return None

        return await _run(logger, op)

    # PUT /ws/{workspace_id}/balancer-statuses/system/{scope}/{slug}
    #   dep: require_workspace_permission("team", "update")
    @broker.subscriber("rpc.tournament.regstatus_builtin_upsert")
    async def _regstatus_builtin_upsert(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            ctx = _workspace_ctx(data, "update")
            scope = _require_scope(data)
            slug = _require_slug(data)
            body = schemas.BalancerRegistrationStatusUpdate.model_validate(_payload(data))
            # A builtin override has no id of its own that survives a reset, so the
            # row is keyed by the (scope, slug) pair the request addresses.
            await reg_audit.audit_service.stage(
                session,
                action="registration_status.builtin_upsert",
                actor=ctx.user,
                workspace_id=ctx.ws_id,
                data=data,
                entity_id=None,
                entity_type="registration_status",
                entity_label=slug,
                after={"scope": scope, "slug": slug, **body.model_dump(exclude_none=True)},
            )
            status_row = await status_catalog.status_catalog_service.upsert_builtin_override(
                session,
                workspace_id=ctx.ws_id,
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
            ctx = _workspace_ctx(data, "update")
            scope = _require_scope(data)
            slug = _require_slug(data)
            await reg_audit.audit_service.stage(
                session,
                action="registration_status.builtin_reset",
                actor=ctx.user,
                workspace_id=ctx.ws_id,
                data=data,
                entity_id=None,
                entity_type="registration_status",
                entity_label=slug,
                after={"scope": scope, "slug": slug},
            )
            await status_catalog.status_catalog_service.reset_builtin_override(
                session,
                workspace_id=ctx.ws_id,
                scope=scope,
                slug=slug,
            )
            return None

        return await _run(logger, op)

    # GET /balancer/workspaces/{workspace_id}/subscription-providers
    #   dep: require_workspace_permission("team", "read")
    @broker.subscriber("rpc.tournament.sub_config_list")
    async def _sub_config_list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            ctx = _workspace_ctx(data, "read")
            return _dump(
                await subscription_config.subscription_config_service.list_provider_configs(session, ctx.ws_id)
            )

        return await _run(logger, op)

    # PUT /balancer/workspaces/{workspace_id}/subscription-providers
    #   dep: require_workspace_permission("team", "update")
    @broker.subscriber("rpc.tournament.sub_config_upsert")
    async def _sub_config_upsert(data: dict, msg: RabbitMessage) -> dict:
        """Create or update one provider's config.

        Plaintext challenge codes are hashed in the service and never persisted;
        omitting a field keeps whatever is stored (see subscription_config).
        """

        async def op(session: Any) -> Any:
            ctx = _workspace_ctx(data, "update")
            body = SubscriptionProviderConfigUpsert.model_validate(_payload(data))
            # Named fields only, and deliberately NOT the codes: they are hashed in
            # the service and a digest is still brute-forcible offline, so the trail
            # records only THAT the code set was replaced.
            await reg_audit.audit_service.stage(
                session,
                action="subscription.config_upsert",
                actor=ctx.user,
                workspace_id=ctx.ws_id,
                data=data,
                entity_id=ctx.ws_id,
                entity_type="workspace",
                after={
                    "provider": body.provider,
                    "enabled": body.enabled,
                    "verification_method": body.verification_method,
                    "codes_replaced": body.codes is not None,
                },
            )
            return _dump(
                await subscription_config.subscription_config_service.upsert_provider_config(
                    session, workspace_id=ctx.ws_id, body=body
                )
            )

        return await _run(logger, op)

    # GET /balancer/workspaces/{workspace_id}/subscription-requirement
    #   dep: require_workspace_permission("team", "read")
    @broker.subscriber("rpc.tournament.sub_requirement_get")
    async def _sub_requirement_get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            ctx = _workspace_ctx(data, "read")
            return _dump(
                await subscription_config.subscription_config_service.get_workspace_requirement(session, ctx.ws_id)
            )

        return await _run(logger, op)

    # PUT /balancer/workspaces/{workspace_id}/subscription-requirement
    #   dep: require_workspace_permission("team", "update")
    @broker.subscriber("rpc.tournament.sub_requirement_upsert")
    async def _sub_requirement_upsert(data: dict, msg: RabbitMessage) -> dict:
        """Replace the workspace's subscription rule.

        Wholesale, not merged: one edit here changes admission for every tournament in
        the workspace whose toggle is on, and an empty ``requirements`` list disarms
        them all. A malformed rule is rejected here (422) rather than at check-in.
        """

        async def op(session: Any) -> Any:
            ctx = _workspace_ctx(data, "update")
            body = WorkspaceSubscriptionRequirementUpsert.model_validate(_payload(data))
            # The rule itself is the domain field worth journaling: it is what changed,
            # it is already validated, and an empty blob is the "gate disarmed" event.
            await reg_audit.audit_service.stage(
                session,
                action="subscription.requirement_upsert",
                actor=ctx.user,
                workspace_id=ctx.ws_id,
                data=data,
                entity_id=ctx.ws_id,
                entity_type="workspace",
                after={"requirement": body.requirement},
            )
            return _dump(
                await subscription_config.subscription_config_service.upsert_workspace_requirement(
                    session, workspace_id=ctx.ws_id, body=body
                )
            )

        return await _run(logger, op)
