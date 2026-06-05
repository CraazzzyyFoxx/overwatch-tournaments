"""Endpoints for managing tournament registration forms and registrations."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from shared.balancer_registration_statuses import (
    get_status_metas_map,
)
from shared.balancer_subrole_catalog import resolve_subrole_catalog
from shared.services.profile_visibility import resolve_profiles_open
from src import models
from src.composition import build_admin_registration_use_cases
from src.core import auth, db
from src.presentation.http.admin_registration_serializers import (
    serialize_registration as _serialize_registration,
)
from src.schemas.admin import balancer as admin_schemas
from src.schemas.admin.registration_form import (
    RegistrationFormRead,
    RegistrationFormUpsert,
)

router = APIRouter(
    prefix="/balancer",
    tags=["registration"],
    dependencies=[Depends(auth.require_admin_panel_access())],
)
use_cases = build_admin_registration_use_cases()


# ---------------------------------------------------------------------------
# Form management
# ---------------------------------------------------------------------------


@router.get("/tournaments/{tournament_id}/registration-form", response_model=RegistrationFormRead | None)
async def get_registration_form(
    tournament_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("team", "read")),
):
    form = await use_cases.get_registration_form.execute(session=session, tournament_id=tournament_id)
    if form is None:
        return None
    catalog = await resolve_subrole_catalog(session, form.workspace_id)
    return RegistrationFormRead.model_validate(form, from_attributes=True).model_copy(
        update={"subrole_catalog": catalog}
    )


@router.put("/tournaments/{tournament_id}/registration-form", response_model=RegistrationFormRead)
async def upsert_registration_form(
    tournament_id: int,
    data: RegistrationFormUpsert,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("team", "import")),
):
    form = await use_cases.upsert_registration_form.execute(
        session=session,
        tournament_id=tournament_id,
        payload=data,
    )
    catalog = await resolve_subrole_catalog(session, form.workspace_id)
    return RegistrationFormRead.model_validate(form, from_attributes=True).model_copy(
        update={"subrole_catalog": catalog}
    )


# ---------------------------------------------------------------------------
# Registration management
# ---------------------------------------------------------------------------


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
    registrations = await use_cases.list_registrations.execute(
        session=session,
        tournament_id=tournament_id,
        status_filter=status_filter,
        inclusion_filter=inclusion_filter,
        source_filter=source_filter,
        include_deleted=include_deleted,
    )
    status_meta_map = await get_status_metas_map(
        session,
        workspace_id=registrations[0].workspace_id,
    ) if registrations else None
    form = await use_cases.get_registration_form.execute(
        session=session, tournament_id=tournament_id
    )
    profiles_open_map: dict[int, bool | None] = (
        await resolve_profiles_open(session, registrations, scope=form.open_profile_scope)
        if form is not None and form.require_open_profile
        else {}
    )
    return [
        _serialize_registration(
            registration,
            status_meta_map=status_meta_map,
            profiles_open=profiles_open_map.get(registration.id),
        )
        for registration in registrations
    ]


@router.post(
    "/tournaments/{tournament_id}/registrations",
    response_model=admin_schemas.BalancerRegistrationRead,
    status_code=201,
)
async def create_manual_registration(
    tournament_id: int,
    data: admin_schemas.BalancerRegistrationCreateRequest,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("team", "import")),
):
    registration = await use_cases.create_registration.execute(
        session=session,
        tournament_id=tournament_id,
        payload=data,
    )
    status_meta_map = await get_status_metas_map(session, workspace_id=registration.workspace_id)
    return _serialize_registration(registration, status_meta_map=status_meta_map)


@router.patch("/registrations/{registration_id}", response_model=admin_schemas.BalancerRegistrationRead)
async def update_registration(
    registration_id: int,
    data: admin_schemas.BalancerRegistrationUpdateRequest,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_registration_permission("team", "update")),
):
    registration = await use_cases.update_registration.execute(
        session=session,
        registration_id=registration_id,
        payload=data,
    )
    status_meta_map = await get_status_metas_map(session, workspace_id=registration.workspace_id)
    return _serialize_registration(registration, status_meta_map=status_meta_map)


@router.patch("/registrations/{registration_id}/approve", response_model=admin_schemas.BalancerRegistrationRead)
async def approve_registration(
    registration_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_registration_permission("team", "import")),
):
    registration = await use_cases.approve_registration.execute(
        session=session,
        registration_id=registration_id,
        user=user,
    )
    status_meta_map = await get_status_metas_map(session, workspace_id=registration.workspace_id)
    return _serialize_registration(registration, status_meta_map=status_meta_map)


@router.patch("/registrations/{registration_id}/reject", response_model=admin_schemas.BalancerRegistrationRead)
async def reject_registration(
    registration_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_registration_permission("team", "import")),
):
    registration = await use_cases.reject_registration.execute(
        session=session,
        registration_id=registration_id,
        user=user,
    )
    status_meta_map = await get_status_metas_map(session, workspace_id=registration.workspace_id)
    return _serialize_registration(registration, status_meta_map=status_meta_map)


@router.patch("/registrations/{registration_id}/exclusion", response_model=admin_schemas.BalancerRegistrationRead)
async def set_registration_exclusion(
    registration_id: int,
    data: admin_schemas.BalancerRegistrationExclusionRequest,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_registration_permission("team", "update")),
):
    registration = await use_cases.set_registration_exclusion.execute(
        session=session,
        registration_id=registration_id,
        payload=data,
    )
    status_meta_map = await get_status_metas_map(session, workspace_id=registration.workspace_id)
    return _serialize_registration(registration, status_meta_map=status_meta_map)


@router.patch("/registrations/{registration_id}/withdraw", response_model=admin_schemas.BalancerRegistrationRead)
async def withdraw_registration(
    registration_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_registration_permission("team", "update")),
):
    registration = await use_cases.withdraw_registration.execute(
        session=session,
        registration_id=registration_id,
    )
    status_meta_map = await get_status_metas_map(session, workspace_id=registration.workspace_id)
    return _serialize_registration(registration, status_meta_map=status_meta_map)


@router.patch("/registrations/{registration_id}/restore", response_model=admin_schemas.BalancerRegistrationRead)
async def restore_registration(
    registration_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_registration_permission("team", "update")),
):
    registration = await use_cases.restore_registration.execute(
        session=session,
        registration_id=registration_id,
    )
    status_meta_map = await get_status_metas_map(session, workspace_id=registration.workspace_id)
    return _serialize_registration(registration, status_meta_map=status_meta_map)


@router.delete("/registrations/{registration_id}", status_code=204)
async def delete_registration(
    registration_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_registration_permission("team", "import")),
):
    await use_cases.delete_registration.execute(
        session=session,
        registration_id=registration_id,
        user=user,
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
    approved, skipped = await use_cases.bulk_approve_registrations.execute(
        session=session,
        tournament_id=tournament_id,
        registration_ids=registration_ids,
        user=user,
    )
    return admin_schemas.BulkApproveResponse(approved=approved, skipped=skipped)


# ---------------------------------------------------------------------------
# Balancer status management
# ---------------------------------------------------------------------------


@router.patch("/registrations/{registration_id}/balancer-status", response_model=admin_schemas.BalancerRegistrationRead)
async def set_balancer_status(
    registration_id: int,
    data: admin_schemas.SetBalancerStatusRequest,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_registration_permission("team", "update")),
):
    registration = await use_cases.set_balancer_status.execute(
        session=session,
        registration_id=registration_id,
        balancer_status=data.balancer_status,
    )
    status_meta_map = await get_status_metas_map(session, workspace_id=registration.workspace_id)
    return _serialize_registration(registration, status_meta_map=status_meta_map)


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
    registration_ids = [int(rid) for rid in data.get("registration_ids", [])]
    balancer_status = data.get("balancer_status", "ready")
    updated, skipped = await use_cases.bulk_add_to_balancer.execute(
        session=session,
        tournament_id=tournament_id,
        registration_ids=registration_ids,
        balancer_status=balancer_status,
    )
    return admin_schemas.BulkBalancerStatusResponse(updated=updated, skipped=skipped)


# ---------------------------------------------------------------------------
# Check-in management
# ---------------------------------------------------------------------------


@router.post(
    "/tournaments/{tournament_id}/registrations/export-users",
    response_model=admin_schemas.RegistrationUserExportResponse,
)
async def export_registrations_to_users(
    tournament_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("team", "import")),
):
    result = await use_cases.export_registrations_to_users.execute(
        session=session,
        tournament_id=tournament_id,
    )
    return admin_schemas.RegistrationUserExportResponse(**result)


@router.patch("/registrations/{registration_id}/check-in", response_model=admin_schemas.BalancerRegistrationRead)
async def toggle_check_in(
    registration_id: int,
    data: admin_schemas.CheckInRequest,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_registration_permission("team", "update")),
):
    registration = await use_cases.toggle_check_in.execute(
        session=session,
        registration_id=registration_id,
        checked_in=data.checked_in,
        user=user,
    )
    status_meta_map = await get_status_metas_map(session, workspace_id=registration.workspace_id)
    return _serialize_registration(registration, status_meta_map=status_meta_map)
