"""Public / captain tournament methods over typed RPC.

Each handler preserves the contract of the former HTTP route it replaced (the
``src/routes/`` HTTP service has been decommissioned): it rehydrates the
gateway-injected identity where a user was required, validates the SAME body
schema, calls the SAME service function with the SAME args, and serializes the
SAME way the route returned. The request schemas and read-model builders now
live in ``src/schemas/{captain,registration,registration_build}.py``.

Serialization parity:
- captain handlers return custom dicts -> returned verbatim.
- registration handlers do NOT use ``response_model_exclude_none`` -> plain
  ``model_dump(mode="json")`` (keep nulls). ``RegistrationFormRead | None`` and
  ``RegistrationRead | None`` may serialize to ``None``.
- saved-view writes DID use ``response_model_exclude_none=True`` ->
  ``model_dump(mode="json", exclude_none=True)``; the delete returns 204 -> None.

Commit semantics: every write service called here commits internally
(captain.submit_result/submit_match_report/confirm_result/dispute_result,
map_veto.perform_veto_action, reg_service.create/update/withdraw/check_in,
encounter service.upsert_saved_view/delete_saved_view), so the handlers add no
extra commit.

The gateway passes path params as ``data["<name>"]`` (and the primary id as
``data["id"]`` when the RouteSpec sets IDParam), query params as
``data["query"][key] = [values]``, and the JSON body as ``data["payload"]``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import sqlalchemy as sa
from cashews import Command, cache
from shared.core.errors import BaseAPIException as HTTPException
from faststream.rabbit.annotations import RabbitMessage
from pydantic import ValidationError
from shared.balancer_registration_statuses import build_unknown_status_meta, get_status_metas_map
from shared.balancer_subrole_catalog import resolve_subrole_catalog
from shared.rpc.identity import MissingIdentityError, rehydrate_user
from shared.schemas.rpc import rpc_error, rpc_ok, status_to_code
from shared.services.profile_visibility import resolve_profiles_open
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from src import models, schemas
from src.core import db
from src.schemas.captain import (
    CaptainMatchReport,
    DisputeRequest,
    ResultSubmission,
    VetoAction,
    resolve_optional_viewer_side,
)
from src.schemas.registration_build import (
    _build_tournament_history,
    _form_to_read,
    _reg_to_read,
    _resolve_tournament_workspace,
    _resolve_top_heroes_config,
)
from src.schemas.registration import (
    RegistrationCreate,
    RegistrationListRead,
    RegistrationListResponse,
    RegistrationStatusResponse,
    RegistrationUpdate,
)
from src.services.encounter import captain as captain_service
from src.services.encounter import flows as encounter_flows
from src.services.encounter import map_veto as map_veto_service
from src.services.registration import service as reg_service
from src.services.registration.validation import (
    validate_registration_input,
    validate_verified_identity,
)


# --- helpers -----------------------------------------------------------------


def _identity(data: dict[str, Any]) -> models.AuthUser:
    """Rehydrate the gateway-injected identity into a transient AuthUser."""
    return rehydrate_user(data.get("identity"))


def _optional_identity(data: dict[str, Any]) -> models.AuthUser | None:
    """Rehydrate identity for AuthOptional routes; None when anonymous.

    The gateway injects ``identity`` only when a valid token is present on an
    AuthOptional route, so the absence of the key means the caller is anonymous.
    """
    if not data.get("identity"):
        return None
    return rehydrate_user(data.get("identity"))


def _payload(data: dict[str, Any]) -> dict[str, Any]:
    return data.get("payload") or {}


def _require_id(data: dict[str, Any]) -> int:
    try:
        return int(data["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="id is required") from exc


def _path_int(data: dict[str, Any], name: str) -> int:
    raw = data.get(name)
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"{name} is required") from exc


def _q(data: dict[str, Any], key: str) -> list[str] | None:
    vals = (data.get("query") or {}).get(key)
    if vals is None:
        return None
    return vals if isinstance(vals, list) else [vals]


def _q1(data: dict[str, Any], key: str, cast: Callable[[str], Any] = str, default: Any = None) -> Any:
    vals = _q(data, key)
    if not vals:
        return default
    try:
        return cast(vals[0])
    except (TypeError, ValueError):
        return default


def _require_q1(data: dict[str, Any], key: str, cast: Callable[[str], Any] = str) -> Any:
    val = _q1(data, key, cast)
    if val is None:
        raise HTTPException(status_code=422, detail=f"{key} is required")
    return val


def _dump(obj: Any, *, exclude_none: bool = False) -> Any:
    if obj is None:
        return None
    if isinstance(obj, list):
        return [_dump(x, exclude_none=exclude_none) for x in obj]
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json", exclude_none=exclude_none)
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
        logger.exception("tournament public rpc failed")
        return rpc_error("internal", "internal error")


def register(broker: Any, logger: Any) -> None:
    # ── captain: identity / result submission ─────────────────────────────

    @broker.subscriber("rpc.tournament.captain_my_role")
    async def _captain_my_role(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            encounter_id = _require_id(data)
            encounter = await captain_service._load_encounter(session, encounter_id)
            try:
                side = await captain_service.resolve_captain_side(session, user, encounter)
            except HTTPException:
                side = None
            return {"side": side}

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.captain_submit_result")
    async def _captain_submit_result(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            encounter_id = _require_id(data)
            body = ResultSubmission.model_validate(_payload(data))
            # submit_result commits internally; route returns a custom dict.
            encounter = await captain_service.submit_result(
                session,
                user,
                encounter_id,
                body.home_score,
                body.away_score,
            )
            return {
                "id": encounter.id,
                "result_status": encounter.result_status,
                "home_score": encounter.home_score,
                "away_score": encounter.away_score,
            }

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.captain_submit_match_report")
    async def _captain_submit_match_report(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            encounter_id = _require_id(data)
            body = CaptainMatchReport.model_validate(_payload(data))
            # submit_match_report commits internally; route returns a custom dict.
            encounter = await captain_service.submit_match_report(
                session,
                user,
                encounter_id,
                home_score=body.home_score,
                away_score=body.away_score,
                closeness_score=body.closeness,
            )
            return {
                "id": encounter.id,
                "result_status": encounter.result_status,
                "home_score": encounter.home_score,
                "away_score": encounter.away_score,
                "closeness": encounter.closeness,
            }

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.captain_confirm_result")
    async def _captain_confirm_result(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            encounter_id = _require_id(data)
            # confirm_result commits internally; route returns a custom dict.
            encounter = await captain_service.confirm_result(session, user, encounter_id)
            return {
                "id": encounter.id,
                "result_status": encounter.result_status,
                "status": encounter.status,
            }

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.captain_dispute_result")
    async def _captain_dispute_result(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            encounter_id = _require_id(data)
            body = DisputeRequest.model_validate(_payload(data))
            # dispute_result commits internally; route returns a custom dict.
            encounter = await captain_service.dispute_result(
                session,
                user,
                encounter_id,
                body.reason,
            )
            return {
                "id": encounter.id,
                "result_status": encounter.result_status,
            }

        return await _run(logger, op)

    # ── captain: map veto ─────────────────────────────────────────────────

    @broker.subscriber("rpc.tournament.captain_map_pool")
    async def _captain_map_pool(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            # Public route — no identity required.
            encounter_id = _require_id(data)
            pool = await map_veto_service.get_map_pool(session, encounter_id)
            return [map_veto_service.serialize_map_pool_entry(entry) for entry in pool]

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.captain_map_pool_state")
    async def _captain_map_pool_state(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            # Optional auth: a captain sees their side annotated, anyone else gets
            # viewer_side=None (the pool serializes identically either way).
            encounter_id = _require_id(data)
            user = _optional_identity(data)
            encounter = await captain_service._load_encounter(session, encounter_id)
            viewer_side = await resolve_optional_viewer_side(session, user, encounter)
            return await map_veto_service.get_map_pool_state(
                session,
                encounter_id,
                viewer_side=viewer_side,
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.captain_veto")
    async def _captain_veto(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            encounter_id = _require_id(data)
            body = VetoAction.model_validate(_payload(data))
            encounter = await captain_service._load_encounter(session, encounter_id)
            captain_side = await captain_service.resolve_captain_side(session, user, encounter)
            # perform_veto_action commits internally; route returns a custom dict.
            entry = await map_veto_service.perform_veto_action(
                session,
                encounter_id,
                captain_side,
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

    # ── public registration (user sign-up) ────────────────────────────────

    @broker.subscriber("rpc.tournament.reg_pub_form")
    async def _reg_pub_form(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            # Public route — no identity required.
            tournament_id = _path_int(data, "tournament_id")
            form = await reg_service.get_registration_form(session, tournament_id)
            if form is None:
                return None
            subrole_catalog = await resolve_subrole_catalog(session, form.workspace_id)
            return _dump(_form_to_read(form, subrole_catalog=subrole_catalog))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.reg_pub_create")
    async def _reg_pub_create(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _path_int(data, "tournament_id")
            body = RegistrationCreate.model_validate(_payload(data))

            form = await reg_service.get_registration_form(session, tournament_id)
            if form is None or not form.is_open:
                raise HTTPException(status_code=400, detail="Registration is not open for this tournament")

            workspace_id = form.workspace_id

            subrole_catalog = await resolve_subrole_catalog(session, workspace_id)
            hero_catalog, max_heroes = await _resolve_top_heroes_config(session, form)
            validate_registration_input(
                form,
                body,
                subrole_catalog=subrole_catalog,
                hero_catalog=hero_catalog,
            )

            existing = await reg_service.get_registration(session, tournament_id, user.id)
            if existing is not None:
                if existing.status == "withdrawn":
                    raise HTTPException(status_code=409, detail="Withdrawn registrations cannot be submitted again")
                raise HTTPException(status_code=409, detail="Already registered for this tournament")

            # Resolve player profile from auth_user (explicit query to avoid lazy load)
            user_player_id: int | None = await session.scalar(
                sa.select(models.User.id).where(models.User.auth_user_id == user.id)
            )

            # Identity fields flagged ``require_verified`` must match an
            # OAuth-verified social account on the registrant's player profile.
            await validate_verified_identity(
                session,
                form=form,
                payload=body,
                player_id=user_player_id,
            )

            role_entries = reg_service.build_registration_roles(
                body.roles,
                hero_catalog=hero_catalog,
                max_heroes=max_heroes,
            )

            try:
                registration = await reg_service.create_registration(
                    session,
                    tournament_id=tournament_id,
                    workspace_id=workspace_id,
                    auth_user_id=user.id,
                    user_id=user_player_id,
                    battle_tag=body.battle_tag,
                    smurf_tags=body.smurf_tags,
                    discord_nick=body.discord_nick,
                    twitch_nick=body.twitch_nick,
                    stream_pov=body.stream_pov,
                    notes=body.notes,
                    custom_fields=body.custom_fields,
                    auto_approve=form.auto_approve,
                    auth_user=user,
                )

                # Write normalized roles
                for entry in role_entries:
                    entry.registration_id = registration.id
                    session.add(entry)
                await session.commit()
            except IntegrityError:
                raise HTTPException(status_code=409, detail="Already registered for this tournament")

            result = await session.execute(
                sa.select(models.BalancerRegistration)
                .where(models.BalancerRegistration.id == registration.id)
                .options(
                    selectinload(models.BalancerRegistration.roles)
                    .selectinload(models.BalancerRegistrationRole.hero_entries)
                    .selectinload(models.BalancerRegistrationRoleHero.hero)
                )
            )
            registration = result.scalar_one()
            status_meta_map = await get_status_metas_map(session, workspace_id=workspace_id)
            return _dump(
                _reg_to_read(
                    registration,
                    workspace_id=workspace_id,
                    status_meta_map=status_meta_map,
                    show_ranks=form.show_ranks,
                )
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.reg_pub_get_me")
    async def _reg_pub_get_me(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _path_int(data, "tournament_id")
            reg = await reg_service.get_registration(session, tournament_id, user.id)
            if reg is None:
                return None
            form = await reg_service.get_registration_form(session, tournament_id)
            show_ranks = form.show_ranks if form is not None else False
            workspace_id = form.workspace_id if form is not None else await _resolve_tournament_workspace(
                session, tournament_id
            )
            status_meta_map = await get_status_metas_map(session, workspace_id=workspace_id)
            return _dump(
                _reg_to_read(reg, workspace_id=workspace_id, status_meta_map=status_meta_map, show_ranks=show_ranks)
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.reg_pub_update_me")
    async def _reg_pub_update_me(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _path_int(data, "tournament_id")
            body = RegistrationUpdate.model_validate(_payload(data))

            form = await reg_service.get_registration_form(session, tournament_id)
            if form is None:
                raise HTTPException(status_code=404, detail="Registration form not found")

            reg = await reg_service.get_registration(session, tournament_id, user.id)
            if reg is None:
                raise HTTPException(status_code=404, detail="No registration found")
            if reg.status != "pending":
                raise HTTPException(status_code=400, detail="Cannot update a registration that is not pending")

            validate_registration_input(form, body, partial=True)
            await validate_verified_identity(
                session,
                form=form,
                payload=body,
                player_id=reg.user_id,
                partial=True,
            )

            # update_registration commits internally.
            updated = await reg_service.update_registration(
                session,
                reg,
                **body.model_dump(exclude_unset=True),
            )
            status_meta_map = await get_status_metas_map(session, workspace_id=form.workspace_id)
            return _dump(
                _reg_to_read(
                    updated,
                    workspace_id=form.workspace_id,
                    status_meta_map=status_meta_map,
                    show_ranks=form.show_ranks,
                )
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.reg_pub_withdraw_me")
    async def _reg_pub_withdraw_me(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _path_int(data, "tournament_id")
            reg = await reg_service.get_registration(session, tournament_id, user.id)
            if reg is None:
                raise HTTPException(status_code=404, detail="No registration found")
            # withdraw_registration commits internally.
            await reg_service.withdraw_registration(session, reg)
            return _dump(RegistrationStatusResponse(status="withdrawn", message="Registration withdrawn"))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.reg_pub_check_in")
    async def _reg_pub_check_in(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _path_int(data, "tournament_id")
            reg = await reg_service.get_registration(session, tournament_id, user.id)
            if reg is None:
                raise HTTPException(status_code=404, detail="No registration found")

            # "All profiles open" admission gate: block check-in only when the profile is
            # confirmed closed. Unknown (not yet fetched) fails open.
            form = await reg_service.get_registration_form(session, tournament_id)
            if form is not None and form.require_open_profile:
                verdict = (
                    await resolve_profiles_open(session, [reg], scope=form.open_profile_scope)
                ).get(reg.id)
                if verdict is False:
                    raise HTTPException(
                        status_code=400,
                        detail="Your Overwatch profile is private. Make it public to check in.",
                    )

            # check_in_registration commits internally.
            checked_in = await reg_service.check_in_registration(
                session,
                reg,
                checked_in_by=user.id,
            )
            workspace_id = await _resolve_tournament_workspace(session, tournament_id)
            status_meta_map = await get_status_metas_map(session, workspace_id=workspace_id)
            return _dump(
                _reg_to_read(
                    checked_in,
                    workspace_id=workspace_id,
                    status_meta_map=status_meta_map,
                    show_ranks=form.show_ranks if form else False,
                )
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.reg_pub_list")
    async def _reg_pub_list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            # Public route — no identity required.
            tournament_id = _path_int(data, "tournament_id")
            workspace_id = await _resolve_tournament_workspace(session, tournament_id)

            # The registration list must always reflect live data; run the query (and
            # the workspace-config reads riding along) with the query cache disabled.
            # Tournament-history building is deliberately kept OUTSIDE this block: it
            # relies on the Redis-cached division-grid snapshots on this global cache.
            with cache.disabling(Command.GET, Command.SET):
                result = await session.execute(
                    sa.select(models.BalancerRegistration)
                    .where(
                        # tournament_id already pins this to a single workspace
                        # (BalancerRegistration has no denormalized workspace_id).
                        models.BalancerRegistration.tournament_id == tournament_id,
                        models.BalancerRegistration.deleted_at.is_(None),
                    )
                    .options(
                        selectinload(models.BalancerRegistration.roles)
                        .selectinload(models.BalancerRegistrationRole.hero_entries)
                        .selectinload(models.BalancerRegistrationRoleHero.hero),
                        # Needed by _build_tournament_history's user_id fallback below.
                        selectinload(models.BalancerRegistration.workspace_member),
                    )
                    .order_by(models.BalancerRegistration.submitted_at.asc())
                )
                registrations = result.scalars().all()
                status_meta_map = await get_status_metas_map(session, workspace_id=workspace_id)

                form = await reg_service.get_registration_form(session, tournament_id)
                profiles_open_map: dict[int, bool | None] = (
                    await resolve_profiles_open(session, registrations, scope=form.open_profile_scope)
                    if form is not None and form.require_open_profile
                    else {}
                )
                show_ranks = form.show_ranks if form is not None else False

            history_map, history_count_map, division_grids = await _build_tournament_history(
                session,
                registrations,
                tournament_id,
                workspace_id,
            )

            registrations_read = [
                RegistrationListRead(
                    **_reg_to_read(
                        r, workspace_id=workspace_id, status_meta_map=status_meta_map, show_ranks=show_ranks
                    ).model_dump(),
                    balancer_status=r.balancer_status,
                    balancer_status_meta=status_meta_map["balancer"].get(r.balancer_status)
                    or build_unknown_status_meta("balancer", r.balancer_status),
                    profiles_open=profiles_open_map.get(r.id),
                    tournament_history=history_map.get(r.id, []),
                    tournament_history_count=history_count_map.get(r.id, 0),
                )
                for r in registrations
            ]
            return _dump(
                RegistrationListResponse(
                    registrations=registrations_read,
                    division_grids=division_grids,
                )
            )

        return await _run(logger, op)

    # ── encounter saved-view writes ───────────────────────────────────────

    @broker.subscriber("rpc.tournament.saved_view_create")
    async def _saved_view_create(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            workspace_id = _require_q1(data, "workspace_id", int)
            body = schemas.EncounterSavedViewCreate.model_validate(_payload(data))
            # upsert_saved_view commits internally; route uses response_model_exclude_none=True.
            saved_view = await encounter_flows.save_view(
                session,
                workspace_id=workspace_id,
                auth_user_id=user.id,
                data=body,
            )
            return _dump(saved_view, exclude_none=True)

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.saved_view_delete")
    async def _saved_view_delete(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            saved_view_id = _path_int(data, "saved_view_id")
            workspace_id = _require_q1(data, "workspace_id", int)
            # delete_saved_view commits internally; route returns 204 (no body).
            await encounter_flows.delete_saved_view(
                session,
                workspace_id=workspace_id,
                auth_user_id=user.id,
                saved_view_id=saved_view_id,
            )
            return None

        return await _run(logger, op)
