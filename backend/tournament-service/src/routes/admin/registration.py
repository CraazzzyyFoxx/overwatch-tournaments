"""Admin endpoints for tournament registrations."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status
from shared.balancer_registration_statuses import get_status_metas_map
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.core import auth, db
from src.schemas.admin import balancer as admin_schemas
from src.schemas.registration import RegistrationFormRead, RegistrationFormUpsert
from src.services.registration import admin as registration_service
from src.services.registration.serializers import (
    serialize_registration,
    serialize_registration_form,
)

router = APIRouter(
    prefix="/balancer",
    tags=["registration"],
)


@router.get("/tournaments/{tournament_id}/registration-form", response_model=RegistrationFormRead | None)
async def get_registration_form(
    tournament_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("team", "read")),
):
    form = await registration_service.get_registration_form(session, tournament_id)
    if form is None:
        return None
    return serialize_registration_form(form)


@router.put("/tournaments/{tournament_id}/registration-form", response_model=RegistrationFormRead)
async def upsert_registration_form(
    tournament_id: int,
    data: RegistrationFormUpsert,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("team", "import")),
):
    tournament = await registration_service.ensure_tournament_exists(session, tournament_id)
    form = await registration_service.get_registration_form(session, tournament_id)
    built_in_fields_json = {key: value.model_dump(exclude_none=True) for key, value in data.built_in_fields.items()}
    custom_fields_json = [field.model_dump(exclude_none=True) for field in data.custom_fields]

    if form is None:
        form = models.BalancerRegistrationForm(
            tournament_id=tournament_id,
            workspace_id=tournament.workspace_id,
            is_open=data.is_open,
            auto_approve=data.auto_approve,
            opens_at=data.opens_at,
            closes_at=data.closes_at,
            require_open_profile=data.require_open_profile,
            open_profile_scope=data.open_profile_scope,
            show_ranks=data.show_ranks,
            built_in_fields_json=built_in_fields_json,
            custom_fields_json=custom_fields_json,
        )
        session.add(form)
    else:
        form.is_open = data.is_open
        form.auto_approve = data.auto_approve
        form.opens_at = data.opens_at
        form.closes_at = data.closes_at
        form.require_open_profile = data.require_open_profile
        form.open_profile_scope = data.open_profile_scope
        form.show_ranks = data.show_ranks
        form.built_in_fields_json = built_in_fields_json
        form.custom_fields_json = custom_fields_json

    await session.commit()
    await session.refresh(form)
    return serialize_registration_form(form)


@router.get("/tournaments/{tournament_id}/registrations", response_model=list[admin_schemas.BalancerRegistrationRead])
async def list_registrations(
    tournament_id: int,
    status_filter: str | None = None,
    inclusion_filter: str | None = None,
    source_filter: str | None = None,
    include_deleted: bool = False,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("team", "read")),
):
    registrations = await registration_service.list_registrations(
        session,
        tournament_id,
        status_filter=status_filter,
        inclusion_filter=inclusion_filter,
        source_filter=source_filter,
        include_deleted=include_deleted,
    )
    status_meta_map = (
        await get_status_metas_map(session, workspace_id=registrations[0].workspace_id) if registrations else None
    )
    return [serialize_registration(registration, status_meta_map=status_meta_map) for registration in registrations]


@router.post(
    "/tournaments/{tournament_id}/registrations",
    response_model=admin_schemas.BalancerRegistrationRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_manual_registration(
    tournament_id: int,
    data: admin_schemas.BalancerRegistrationCreateRequest,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("team", "import")),
):
    tournament = await registration_service.ensure_tournament_exists(session, tournament_id)
    registration = await registration_service.create_manual_registration(
        session,
        tournament_id=tournament_id,
        workspace_id=tournament.workspace_id,
        display_name=data.display_name,
        battle_tag=data.battle_tag,
        smurf_tags_json=data.smurf_tags_json,
        discord_nick=data.discord_nick,
        twitch_nick=data.twitch_nick,
        stream_pov=data.stream_pov,
        notes=data.notes,
        admin_notes=data.admin_notes,
        roles=[role.model_dump() for role in data.roles],
    )
    status_meta_map = await get_status_metas_map(session, workspace_id=registration.workspace_id)
    return serialize_registration(registration, status_meta_map=status_meta_map)


@router.patch("/registrations/{registration_id}", response_model=admin_schemas.BalancerRegistrationRead)
async def update_registration(
    registration_id: int,
    data: admin_schemas.BalancerRegistrationUpdateRequest,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_registration_permission("team", "update")),
):
    registration = await registration_service.update_registration_profile(
        session,
        registration_id,
        display_name=data.display_name,
        battle_tag=data.battle_tag,
        smurf_tags_json=data.smurf_tags_json,
        discord_nick=data.discord_nick,
        twitch_nick=data.twitch_nick,
        stream_pov=data.stream_pov,
        notes=data.notes,
        admin_notes=data.admin_notes,
        status_value=data.status,
        balancer_status_value=data.balancer_status,
        roles=[role.model_dump() for role in data.roles] if data.roles is not None else None,
    )
    status_meta_map = await get_status_metas_map(session, workspace_id=registration.workspace_id)
    return serialize_registration(registration, status_meta_map=status_meta_map)


@router.patch("/registrations/{registration_id}/approve", response_model=admin_schemas.BalancerRegistrationRead)
async def approve_registration(
    registration_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_registration_permission("team", "import")),
):
    registration = await registration_service.approve_registration(
        session,
        registration_id,
        reviewed_by=user.id,
    )
    status_meta_map = await get_status_metas_map(session, workspace_id=registration.workspace_id)
    return serialize_registration(registration, status_meta_map=status_meta_map)


@router.patch("/registrations/{registration_id}/reject", response_model=admin_schemas.BalancerRegistrationRead)
async def reject_registration(
    registration_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_registration_permission("team", "import")),
):
    registration = await registration_service.reject_registration(
        session,
        registration_id,
        reviewed_by=user.id,
    )
    status_meta_map = await get_status_metas_map(session, workspace_id=registration.workspace_id)
    return serialize_registration(registration, status_meta_map=status_meta_map)


@router.patch("/registrations/{registration_id}/exclusion", response_model=admin_schemas.BalancerRegistrationRead)
async def set_registration_exclusion(
    registration_id: int,
    data: admin_schemas.BalancerRegistrationExclusionRequest,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_registration_permission("team", "update")),
):
    registration = await registration_service.set_registration_exclusion(
        session,
        registration_id,
        exclude_from_balancer=data.exclude_from_balancer,
        exclude_reason=data.exclude_reason,
    )
    status_meta_map = await get_status_metas_map(session, workspace_id=registration.workspace_id)
    return serialize_registration(registration, status_meta_map=status_meta_map)


@router.patch("/registrations/{registration_id}/withdraw", response_model=admin_schemas.BalancerRegistrationRead)
async def withdraw_registration(
    registration_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_registration_permission("team", "update")),
):
    registration = await registration_service.withdraw_registration(session, registration_id)
    status_meta_map = await get_status_metas_map(session, workspace_id=registration.workspace_id)
    return serialize_registration(registration, status_meta_map=status_meta_map)


@router.patch("/registrations/{registration_id}/restore", response_model=admin_schemas.BalancerRegistrationRead)
async def restore_registration(
    registration_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_registration_permission("team", "update")),
):
    registration = await registration_service.restore_registration(session, registration_id)
    status_meta_map = await get_status_metas_map(session, workspace_id=registration.workspace_id)
    return serialize_registration(registration, status_meta_map=status_meta_map)


@router.delete("/registrations/{registration_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_registration(
    registration_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_registration_permission("team", "import")),
):
    await registration_service.soft_delete_registration(
        session,
        registration_id,
        deleted_by=user.id,
    )


@router.post(
    "/tournaments/{tournament_id}/registrations/bulk-approve",
    response_model=admin_schemas.BulkApproveResponse,
)
async def bulk_approve_registrations(
    tournament_id: int,
    data: dict[str, Any],
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("team", "import")),
):
    registration_ids = [int(registration_id) for registration_id in data.get("registration_ids", [])]
    approved, skipped = await registration_service.bulk_approve_registrations(
        session,
        tournament_id,
        registration_ids,
        reviewed_by=user.id,
    )
    return admin_schemas.BulkApproveResponse(approved=approved, skipped=skipped)


@router.patch("/registrations/{registration_id}/balancer-status", response_model=admin_schemas.BalancerRegistrationRead)
async def set_balancer_status(
    registration_id: int,
    data: admin_schemas.SetBalancerStatusRequest,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_registration_permission("team", "update")),
):
    registration = await registration_service.set_balancer_status(
        session,
        registration_id,
        balancer_status=data.balancer_status,
    )
    status_meta_map = await get_status_metas_map(session, workspace_id=registration.workspace_id)
    return serialize_registration(registration, status_meta_map=status_meta_map)


@router.post(
    "/tournaments/{tournament_id}/registrations/bulk-add-to-balancer",
    response_model=admin_schemas.BulkBalancerStatusResponse,
)
async def bulk_add_to_balancer(
    tournament_id: int,
    data: dict[str, Any],
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("team", "import")),
):
    registration_ids = [int(registration_id) for registration_id in data.get("registration_ids", [])]
    balancer_status = data.get("balancer_status", "ready")
    updated, skipped = await registration_service.bulk_add_to_balancer(
        session,
        tournament_id,
        registration_ids,
        balancer_status=balancer_status,
    )
    return admin_schemas.BulkBalancerStatusResponse(updated=updated, skipped=skipped)


@router.post(
    "/tournaments/{tournament_id}/registrations/rank-autofill/preview",
    response_model=admin_schemas.BalancerRegistrationRankAutofillResponse,
)
async def preview_registration_rank_autofill(
    tournament_id: int,
    data: admin_schemas.BalancerRegistrationRankAutofillRequest,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("team", "read")),
):
    result = await registration_service.autofill_registration_ranks_from_parsed(
        session,
        tournament_id,
        registration_ids=data.registration_ids,
        overwrite_existing=data.overwrite_existing,
        add_to_balancer=data.add_to_balancer,
        apply=False,
    )
    return admin_schemas.BalancerRegistrationRankAutofillResponse(**result)


@router.post(
    "/tournaments/{tournament_id}/registrations/rank-autofill/apply",
    response_model=admin_schemas.BalancerRegistrationRankAutofillResponse,
)
async def apply_registration_rank_autofill(
    tournament_id: int,
    data: admin_schemas.BalancerRegistrationRankAutofillRequest,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("team", "update")),
):
    result = await registration_service.autofill_registration_ranks_from_parsed(
        session,
        tournament_id,
        registration_ids=data.registration_ids,
        overwrite_existing=data.overwrite_existing,
        add_to_balancer=data.add_to_balancer,
        apply=True,
    )
    return admin_schemas.BalancerRegistrationRankAutofillResponse(**result)


@router.post(
    "/tournaments/{tournament_id}/registrations/export-users",
    response_model=admin_schemas.RegistrationUserExportResponse,
)
async def export_registrations_to_users(
    tournament_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("team", "import")),
):
    result = await registration_service.export_registrations_to_users(session, tournament_id)
    return admin_schemas.RegistrationUserExportResponse(**result)


@router.patch("/registrations/{registration_id}/check-in", response_model=admin_schemas.BalancerRegistrationRead)
async def toggle_check_in(
    registration_id: int,
    data: admin_schemas.CheckInRequest,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_registration_permission("team", "update")),
):
    if data.checked_in:
        registration = await registration_service.check_in_registration(
            session,
            registration_id,
            checked_in_by=user.id,
        )
    else:
        registration = await registration_service.uncheck_in_registration(session, registration_id)
    status_meta_map = await get_status_metas_map(session, workspace_id=registration.workspace_id)
    return serialize_registration(registration, status_meta_map=status_meta_map)
