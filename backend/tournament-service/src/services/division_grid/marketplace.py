from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import urlparse

import sqlalchemy as sa
from fastapi import HTTPException
from shared.clients import S3Client
from shared.services import division_grid_cache
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src import models, schemas

MAX_GRID_SLUG_LENGTH = 128
IMAGE_CONTENT_TYPES = {"image/webp", "image/png", "image/jpeg", "image/gif"}


@dataclass(slots=True)
class DivisionImageCopy:
    public_url: str
    key: str


def _safe_key_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-") or "item"


def _truncate_slug_base(slug: str, suffix: str) -> str:
    max_base_length = MAX_GRID_SLUG_LENGTH - len(suffix)
    return slug[:max_base_length].rstrip("-") or "grid"


async def make_unique_grid_slug(session: AsyncSession, workspace_id: int, desired_slug: str) -> str:
    base = desired_slug[:MAX_GRID_SLUG_LENGTH].rstrip("-") or "grid"
    candidate = base
    index = 1
    while True:
        exists = await session.scalar(
            sa.select(models.DivisionGrid.id).where(
                models.DivisionGrid.workspace_id == workspace_id,
                models.DivisionGrid.slug == candidate,
            )
        )
        if exists is None:
            return candidate

        suffix = "-copy" if index == 1 else f"-copy-{index}"
        candidate = f"{_truncate_slug_base(base, suffix)}{suffix}"
        index += 1


def extract_s3_key_from_public_url(public_url: str | None, image_url: str | None) -> str | None:
    if not public_url or not image_url:
        return None

    normalized_public = public_url.rstrip("/")
    if image_url.startswith(f"{normalized_public}/"):
        return image_url.removeprefix(f"{normalized_public}/")

    public_parts = urlparse(normalized_public)
    image_parts = urlparse(image_url)
    if (public_parts.scheme, public_parts.netloc) != (image_parts.scheme, image_parts.netloc):
        return None

    prefix_path = public_parts.path.rstrip("/")
    if image_parts.path.startswith(f"{prefix_path}/"):
        return image_parts.path.removeprefix(f"{prefix_path}/")
    return None


def guess_content_type_from_key(key: str) -> str:
    suffix = PurePosixPath(key).suffix.lower()
    return {
        ".webp": "image/webp",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
    }.get(suffix, "application/octet-stream")


def extension_for_content_type(content_type: str, source_key: str) -> str:
    suffix = PurePosixPath(source_key).suffix.lower().lstrip(".")
    if suffix in {"webp", "png", "jpg", "jpeg", "gif"}:
        return "jpg" if suffix == "jpeg" else suffix

    return {
        "image/webp": "webp",
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/gif": "gif",
    }.get(content_type, "bin")


async def _candidate_division_asset_keys(
    s3: S3Client,
    *,
    source_workspace_slug: str,
    tier_slug: str,
    image_url: str | None,
) -> list[str]:
    candidates: list[str] = []
    key_from_url = extract_s3_key_from_public_url(getattr(s3, "_public_url", None), image_url)
    if key_from_url:
        candidates.append(key_from_url)

    parsed_path = PurePosixPath(urlparse(image_url or "").path)
    filename = parsed_path.name
    prefixes = []
    if filename:
        prefixes.append(f"assets/divisions/{source_workspace_slug}/{PurePosixPath(filename).stem}")
    prefixes.append(f"assets/divisions/{source_workspace_slug}/{tier_slug}")

    for prefix in dict.fromkeys(prefixes):
        for key in sorted(await s3.list_objects(prefix)):
            if key not in candidates:
                candidates.append(key)
    return candidates


async def copy_division_icon_asset(
    s3: S3Client,
    *,
    source_workspace: models.Workspace,
    target_workspace: models.Workspace,
    source_tier: models.DivisionGridTier,
    target_grid_slug: str,
    target_version: int,
) -> DivisionImageCopy:
    candidates = await _candidate_division_asset_keys(
        s3,
        source_workspace_slug=source_workspace.slug,
        tier_slug=source_tier.slug,
        image_url=source_tier.icon_url,
    )

    source_key: str | None = None
    content: bytes | None = None
    for candidate in candidates:
        content = await s3.get_object(candidate)
        if content is not None:
            source_key = candidate
            break

    if source_key is None or content is None:
        raise HTTPException(
            status_code=409,
            detail=f"Image asset for division tier '{source_tier.slug}' was not found in workspace '{source_workspace.slug}'",
        )

    head = await s3.head_object(source_key)
    content_type = (head or {}).get("ContentType") or guess_content_type_from_key(source_key)
    if content_type == "application/octet-stream":
        content_type = guess_content_type_from_key(source_key)
    if content_type not in IMAGE_CONTENT_TYPES:
        raise HTTPException(
            status_code=409,
            detail=f"Unsupported image content type for tier '{source_tier.slug}': {content_type}",
        )

    extension = extension_for_content_type(content_type, source_key)
    target_key = (
        f"assets/divisions/{target_workspace.slug}/imports/"
        f"{_safe_key_part(target_grid_slug)}/v{target_version}/"
        f"{_safe_key_part(source_tier.slug)}-{source_tier.id}.{extension}"
    )

    ok = await s3.put_object(target_key, content, content_type, public=True)
    if not ok:
        raise HTTPException(
            status_code=409,
            detail=f"Image asset for tier '{source_tier.slug}' could not be copied to target workspace",
        )

    return DivisionImageCopy(public_url=s3.get_public_url(target_key), key=target_key)


def build_marketplace_grid_read(grid: models.DivisionGrid) -> schemas.DivisionGridMarketplaceGridRead:
    versions = sorted(grid.versions, key=lambda version: version.version)
    preview_icon_urls: list[str] = []
    version_reads: list[schemas.DivisionGridMarketplaceVersionRead] = []
    tiers_count = 0

    for version in versions:
        tiers = sorted(version.tiers, key=lambda tier: tier.sort_order)
        tiers_count += len(tiers)
        version_preview = [tier.icon_url for tier in tiers[:5]]
        for icon_url in version_preview:
            if icon_url not in preview_icon_urls and len(preview_icon_urls) < 8:
                preview_icon_urls.append(icon_url)
        version_reads.append(
            schemas.DivisionGridMarketplaceVersionRead(
                id=version.id,
                version=version.version,
                label=version.label,
                status=version.status,
                tiers_count=len(tiers),
                preview_icon_urls=version_preview,
            )
        )

    return schemas.DivisionGridMarketplaceGridRead(
        id=grid.id,
        slug=grid.slug,
        name=grid.name,
        description=grid.description,
        versions_count=len(versions),
        tiers_count=tiers_count,
        preview_icon_urls=preview_icon_urls,
        versions=version_reads,
    )


async def list_marketplace_workspaces(
    session: AsyncSession,
    *,
    target_workspace_id: int,
    user: models.AuthUser,
) -> list[schemas.DivisionGridMarketplaceWorkspaceRead]:
    visible_workspace_ids = None if user.is_superuser else [
        workspace_id for workspace_id in user.get_workspace_ids() if workspace_id != target_workspace_id
    ]
    if visible_workspace_ids == []:
        return []

    query = (
        sa.select(
            models.Workspace.id,
            models.Workspace.slug,
            models.Workspace.name,
            sa.func.count(sa.distinct(models.DivisionGrid.id)).label("grids_count"),
            sa.func.count(sa.distinct(models.DivisionGridVersion.id)).label("versions_count"),
        )
        .join(models.DivisionGrid, models.DivisionGrid.workspace_id == models.Workspace.id)
        .outerjoin(models.DivisionGridVersion, models.DivisionGridVersion.grid_id == models.DivisionGrid.id)
        .where(models.Workspace.id != target_workspace_id)
        .group_by(models.Workspace.id, models.Workspace.slug, models.Workspace.name)
        .having(sa.func.count(sa.distinct(models.DivisionGrid.id)) > 0)
        .order_by(models.Workspace.name.asc())
    )
    if visible_workspace_ids is not None:
        query = query.where(models.Workspace.id.in_(visible_workspace_ids))

    result = await session.execute(query)
    return [
        schemas.DivisionGridMarketplaceWorkspaceRead(
            id=row.id,
            slug=row.slug,
            name=row.name,
            grids_count=int(row.grids_count),
            versions_count=int(row.versions_count),
        )
        for row in result
    ]


async def get_marketplace_grids_by_ids(
    session: AsyncSession,
    *,
    source_workspace_id: int,
    source_grid_ids: Sequence[int],
) -> list[models.DivisionGrid]:
    if not source_grid_ids:
        return []

    result = await session.execute(
        sa.select(models.DivisionGrid)
        .options(
            selectinload(models.DivisionGrid.versions).selectinload(models.DivisionGridVersion.tiers)
        )
        .where(
            models.DivisionGrid.workspace_id == source_workspace_id,
            models.DivisionGrid.id.in_(source_grid_ids),
        )
        .order_by(models.DivisionGrid.id.asc())
    )
    grids_by_id = {grid.id: grid for grid in result.scalars().unique().all()}
    missing_ids = sorted(set(source_grid_ids) - set(grids_by_id))
    if missing_ids:
        raise HTTPException(status_code=404, detail=f"Division grid(s) not found in source workspace: {missing_ids}")
    return [grids_by_id[grid_id] for grid_id in source_grid_ids]


async def list_marketplace_grids(
    session: AsyncSession,
    *,
    source_workspace_id: int,
) -> list[schemas.DivisionGridMarketplaceGridRead]:
    result = await session.execute(
        sa.select(models.DivisionGrid)
        .options(
            selectinload(models.DivisionGrid.versions).selectinload(models.DivisionGridVersion.tiers)
        )
        .where(models.DivisionGrid.workspace_id == source_workspace_id)
        .order_by(models.DivisionGrid.name.asc(), models.DivisionGrid.id.asc())
    )
    return [build_marketplace_grid_read(grid) for grid in result.scalars().unique().all()]


async def load_mappings_for_versions(
    session: AsyncSession,
    source_version_ids: set[int],
) -> list[models.DivisionGridMapping]:
    if not source_version_ids:
        return []

    result = await session.execute(
        sa.select(models.DivisionGridMapping)
        .options(selectinload(models.DivisionGridMapping.rules))
        .where(
            models.DivisionGridMapping.source_version_id.in_(source_version_ids),
            models.DivisionGridMapping.target_version_id.in_(source_version_ids),
        )
    )
    return list(result.scalars().unique().all())


async def _cleanup_uploaded_keys(s3: S3Client, copied_keys: list[str]) -> None:
    for key in reversed(copied_keys):
        await s3.delete_object(key)


def _select_default_imported_version(
    *,
    source_workspace: models.Workspace,
    source_grids: Sequence[models.DivisionGrid],
    version_id_map: dict[int, int],
) -> int | None:
    source_default_id = source_workspace.default_division_grid_version_id
    if source_default_id is not None and source_default_id in version_id_map:
        return version_id_map[source_default_id]

    if not source_grids:
        return None

    first_grid_versions = sorted(source_grids[0].versions, key=lambda version: version.version)
    published_versions = [version for version in first_grid_versions if version.status == "published"]
    candidate = published_versions[-1] if published_versions else (first_grid_versions[-1] if first_grid_versions else None)
    if candidate is None:
        return None
    return version_id_map.get(candidate.id)


async def import_division_grids(
    session: AsyncSession,
    s3: S3Client,
    *,
    target_workspace: models.Workspace,
    source_workspace: models.Workspace,
    source_grids: Sequence[models.DivisionGrid],
    set_default: bool,
) -> schemas.DivisionGridMarketplaceImportResult:
    copied_keys: list[str] = []
    version_id_map: dict[int, int] = {}
    tier_id_map: dict[int, int] = {}
    imported_grids: list[schemas.DivisionGridMarketplaceImportedGrid] = []
    warnings: list[schemas.DivisionGridMarketplaceImportWarning] = []
    copied_images = 0
    copied_mappings = 0

    try:
        for source_grid in source_grids:
            target_slug = await make_unique_grid_slug(session, target_workspace.id, source_grid.slug)
            target_grid = models.DivisionGrid(
                workspace_id=target_workspace.id,
                slug=target_slug,
                name=source_grid.name,
                description=source_grid.description,
            )
            session.add(target_grid)
            await session.flush()

            grid_versions_count = 0
            grid_tiers_count = 0
            source_versions = sorted(source_grid.versions, key=lambda version: version.version)
            pending_created_from: list[tuple[models.DivisionGridVersion, int | None]] = []

            for source_version in source_versions:
                target_version = models.DivisionGridVersion(
                    grid_id=target_grid.id,
                    version=source_version.version,
                    label=source_version.label,
                    status=source_version.status,
                    created_from_version_id=None,
                    published_at=source_version.published_at,
                )
                session.add(target_version)
                await session.flush()
                version_id_map[source_version.id] = target_version.id
                pending_created_from.append((target_version, source_version.created_from_version_id))
                grid_versions_count += 1

                for source_tier in sorted(source_version.tiers, key=lambda tier: tier.sort_order):
                    copied = await copy_division_icon_asset(
                        s3,
                        source_workspace=source_workspace,
                        target_workspace=target_workspace,
                        source_tier=source_tier,
                        target_grid_slug=target_slug,
                        target_version=source_version.version,
                    )
                    copied_keys.append(copied.key)
                    copied_images += 1

                    target_tier = models.DivisionGridTier(
                        version_id=target_version.id,
                        slug=source_tier.slug,
                        number=source_tier.number,
                        name=source_tier.name,
                        sort_order=source_tier.sort_order,
                        rank_min=source_tier.rank_min,
                        rank_max=source_tier.rank_max,
                        icon_url=copied.public_url,
                    )
                    session.add(target_tier)
                    await session.flush()
                    tier_id_map[source_tier.id] = target_tier.id
                    grid_tiers_count += 1

            for target_version, source_created_from_id in pending_created_from:
                if source_created_from_id is not None:
                    target_version.created_from_version_id = version_id_map.get(source_created_from_id)
            await session.flush()

            imported_grids.append(
                schemas.DivisionGridMarketplaceImportedGrid(
                    source_grid_id=source_grid.id,
                    target_grid_id=target_grid.id,
                    slug=target_grid.slug,
                    name=target_grid.name,
                    versions_count=grid_versions_count,
                    tiers_count=grid_tiers_count,
                )
            )

        source_version_ids = set(version_id_map)
        mappings = await load_mappings_for_versions(session, source_version_ids)
        for source_mapping in mappings:
            target_source_version_id = version_id_map.get(source_mapping.source_version_id)
            target_target_version_id = version_id_map.get(source_mapping.target_version_id)
            if target_source_version_id is None or target_target_version_id is None:
                continue

            target_mapping = models.DivisionGridMapping(
                source_version_id=target_source_version_id,
                target_version_id=target_target_version_id,
                name=source_mapping.name,
                is_complete=source_mapping.is_complete,
            )
            session.add(target_mapping)
            await session.flush()

            for source_rule in source_mapping.rules:
                target_source_tier_id = tier_id_map.get(source_rule.source_tier_id)
                target_target_tier_id = tier_id_map.get(source_rule.target_tier_id)
                if target_source_tier_id is None or target_target_tier_id is None:
                    warnings.append(
                        schemas.DivisionGridMarketplaceImportWarning(
                            message=f"Skipped mapping rule #{source_rule.id}: source or target tier was not imported",
                        )
                    )
                    continue

                session.add(
                    models.DivisionGridMappingRule(
                        mapping_id=target_mapping.id,
                        source_tier_id=target_source_tier_id,
                        target_tier_id=target_target_tier_id,
                        weight=source_rule.weight,
                        is_primary=source_rule.is_primary,
                    )
                )
            copied_mappings += 1
        await session.flush()

        if set_default:
            target_default_version_id = _select_default_imported_version(
                source_workspace=source_workspace,
                source_grids=source_grids,
                version_id_map=version_id_map,
            )
            if target_default_version_id is not None:
                target_workspace.default_division_grid_version_id = target_default_version_id
                await division_grid_cache.invalidate_workspace(target_workspace.id)
            else:
                warnings.append(
                    schemas.DivisionGridMarketplaceImportWarning(
                        message="Imported grids did not contain any version that can be used as workspace default",
                    )
                )

        for version_id in version_id_map.values():
            await division_grid_cache.invalidate_grid_version(version_id)
        for source_mapping in mappings:
            source_version_id = version_id_map.get(source_mapping.source_version_id)
            target_version_id = version_id_map.get(source_mapping.target_version_id)
            if source_version_id is not None and target_version_id is not None:
                await division_grid_cache.invalidate_mapping(source_version_id, target_version_id)

    except Exception:
        await _cleanup_uploaded_keys(s3, copied_keys)
        raise

    return schemas.DivisionGridMarketplaceImportResult(
        created_grids=len(imported_grids),
        created_versions=len(version_id_map),
        created_tiers=len(tier_id_map),
        copied_images=copied_images,
        copied_mappings=copied_mappings,
        imported_grids=imported_grids,
        warnings=warnings,
    )
