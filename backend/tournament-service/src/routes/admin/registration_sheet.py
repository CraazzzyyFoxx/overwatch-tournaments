"""Admin Google Sheets and active registration export endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.core import auth, db
from src.schemas.admin import balancer as admin_schemas
from src.services.registration import admin as registration_service
from src.services.registration.serializers import serialize_feed

router = APIRouter(
    prefix="/balancer",
    tags=["registration-sheet"],
)


@router.get(
    "/tournaments/{tournament_id}/sheet",
    response_model=admin_schemas.BalancerGoogleSheetFeedRead | None,
)
async def get_tournament_sheet(
    tournament_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("team", "read")),
):
    feed = await registration_service.get_google_sheet_feed(session, tournament_id)
    if feed is None:
        return None
    return serialize_feed(feed)


@router.put(
    "/tournaments/{tournament_id}/sheet",
    response_model=admin_schemas.BalancerGoogleSheetFeedRead,
)
async def upsert_tournament_sheet(
    tournament_id: int,
    data: admin_schemas.BalancerGoogleSheetFeedUpsert,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("team", "import")),
):
    feed = await registration_service.upsert_google_sheet_feed(
        session,
        tournament_id,
        source_url=data.source_url,
        title=data.title,
        auto_sync_enabled=data.auto_sync_enabled,
        auto_sync_interval_seconds=data.auto_sync_interval_seconds,
        mapping_config_json=data.mapping_config_json,
        value_mapping_json=data.value_mapping_json,
    )
    return serialize_feed(feed)


@router.post(
    "/tournaments/{tournament_id}/sheet/sync",
    response_model=admin_schemas.BalancerGoogleSheetFeedSyncResponse,
)
async def sync_tournament_sheet(
    tournament_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("team", "import")),
):
    result = await registration_service.sync_google_sheet_feed(
        session,
        tournament_id,
    )
    return admin_schemas.BalancerGoogleSheetFeedSyncResponse(
        created=result.created,
        updated=result.updated,
        withdrawn=result.withdrawn,
        total=result.total,
        skipped=result.skipped,
        errors=[admin_schemas.MappingPreviewFieldError(**error) for error in result.errors],
        feed=serialize_feed(result.feed),
    )


@router.get(
    "/tournaments/{tournament_id}/sheet/mapping-catalog",
    response_model=admin_schemas.BalancerGoogleSheetMappingCatalogResponse,
)
async def get_sheet_mapping_catalog(
    tournament_id: int,
    include_headers: bool = False,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("team", "read")),
):
    catalog = await registration_service.get_mapping_catalog(
        session,
        tournament_id,
        include_headers=include_headers,
    )
    return admin_schemas.BalancerGoogleSheetMappingCatalogResponse(**catalog)


@router.post(
    "/tournaments/{tournament_id}/sheet/suggest-mapping",
    response_model=admin_schemas.BalancerGoogleSheetMappingSuggestResponse,
)
async def suggest_sheet_mapping(
    tournament_id: int,
    data: admin_schemas.BalancerGoogleSheetMappingSuggestRequest,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("team", "read")),
):
    _, headers, mapping = await registration_service.suggest_google_sheet_mapping(
        session,
        tournament_id,
        source_url=data.source_url,
    )
    return admin_schemas.BalancerGoogleSheetMappingSuggestResponse(
        headers=headers,
        mapping_config_json=mapping,
    )


@router.post(
    "/tournaments/{tournament_id}/sheet/preview",
    response_model=admin_schemas.BalancerGoogleSheetMappingPreviewResponse,
)
async def preview_sheet_mapping(
    tournament_id: int,
    data: admin_schemas.BalancerGoogleSheetMappingPreviewRequest,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("team", "read")),
):
    preview = await registration_service.preview_google_sheet_mapping(
        session,
        tournament_id,
        source_url=data.source_url,
        mapping_config_json=data.mapping_config_json,
        value_mapping_json=data.value_mapping_json,
        sample_rows=data.sample_rows,
    )
    return admin_schemas.BalancerGoogleSheetMappingPreviewResponse(**preview)


@router.get("/tournaments/{tournament_id}/players/export", response_model=admin_schemas.BalancerPlayerExportResponse)
async def export_active_registrations(
    tournament_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("player", "read")),
):
    payload = await registration_service.export_active_registrations(session, tournament_id)
    return admin_schemas.BalancerPlayerExportResponse(**payload)
