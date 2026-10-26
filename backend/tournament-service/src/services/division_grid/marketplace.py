from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from urllib.parse import urlparse
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.clients import S3Client
from shared.core.errors import BaseAPIException as HTTPException
from shared.division_grid import stamp_canonical_numbers
from shared.repository import (
    DivisionGridMappingRepository,
    DivisionGridRepository,
    DivisionGridTierRepository,
    DivisionGridVersionRepository,
    WorkspaceRepository,
)
from shared.services.ontology import assert_discipline_enabled
from src import schemas
from src.services.division_grid.service import DivisionGridService, division_grid_service

__all__ = (
    "MAX_GRID_SLUG_LENGTH",
    "S3_COPY_CONCURRENCY",
    "DivisionImageCopy",
    "DivisionImagePolicy",
    "MarketplaceService",
    "build_marketplace_grid_read",
    "build_source_fingerprint",
    "classify_division_icon_asset",
    "copy_division_icon_asset",
    "copy_division_icon_assets",
    "extract_s3_key_from_public_url",
    "marketplace_service",
    "target_imported_version_state",
)

MAX_GRID_SLUG_LENGTH = 128
S3_COPY_CONCURRENCY = 8

_GRID_OPTIONS = (selectinload(models.DivisionGrid.versions).selectinload(models.DivisionGridVersion.tiers),)
_MAPPING_RULES_OPTIONS = (selectinload(models.DivisionGridMapping.rules),)


@dataclass(frozen=True, slots=True)
class DivisionImagePolicy:
    action: str
    source_key: str | None = None
    warning: str | None = None


@dataclass(slots=True)
class DivisionImageCopy:
    public_url: str
    key: str | None
    warning: str | None = None


def _safe_key_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-") or "item"


def _truncate_slug_base(slug: str, suffix: str) -> str:
    max_base_length = MAX_GRID_SLUG_LENGTH - len(suffix)
    return slug[:max_base_length].rstrip("-") or "grid"


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


def classify_division_icon_asset(
    *,
    public_url: str | None,
    source_workspace_slug: str,
    image_url: str | None,
) -> DivisionImagePolicy:
    source_key = extract_s3_key_from_public_url(public_url, image_url)
    if source_key is None:
        return DivisionImagePolicy(
            action="external",
            warning="External division icon URL was retained instead of copied",
        )

    source_prefix = f"assets/divisions/{source_workspace_slug}/"
    if source_key.startswith(source_prefix):
        return DivisionImagePolicy(action="copy", source_key=source_key)

    global_prefix = "assets/divisions/"
    global_name = source_key.removeprefix(global_prefix)
    if source_key.startswith(global_prefix) and "/" not in global_name:
        return DivisionImagePolicy(action="reuse", source_key=source_key)

    return DivisionImagePolicy(
        action="external",
        warning="Division icon is outside the source workspace asset namespace and was retained",
    )


async def copy_division_icon_asset(
    s3: S3Client,
    *,
    source_workspace: models.Workspace,
    target_workspace: models.Workspace,
    source_tier: models.DivisionGridTier,
    target_grid_slug: str,
    target_version: int,
) -> DivisionImageCopy:
    policy = classify_division_icon_asset(
        public_url=getattr(s3, "_public_url", None),
        source_workspace_slug=source_workspace.slug,
        image_url=source_tier.icon_url,
    )
    if policy.action != "copy" or policy.source_key is None:
        return DivisionImageCopy(
            public_url=source_tier.icon_url,
            key=None,
            warning=policy.warning,
        )

    extension = PurePosixPath(policy.source_key).suffix.lower().lstrip(".") or "bin"
    target_key = (
        f"assets/divisions/{target_workspace.slug}/imports/"
        f"{_safe_key_part(target_grid_slug)}/v{target_version}/"
        f"{_safe_key_part(source_tier.slug)}-{source_tier.id}.{extension}"
    )
    copied = await s3.copy_object(policy.source_key, target_key, public=True)
    if not copied:
        return DivisionImageCopy(
            public_url=source_tier.icon_url,
            key=None,
            warning=f"Division icon for '{source_tier.slug}' could not be copied and the source URL was retained",
        )
    return DivisionImageCopy(public_url=s3.get_public_url(target_key), key=target_key)


async def _copy_division_icon_asset_guarded(
    semaphore: asyncio.Semaphore,
    s3: S3Client,
    *,
    source_workspace: models.Workspace,
    target_workspace: models.Workspace,
    source_tier: models.DivisionGridTier,
    target_grid_slug: str,
    target_version: int,
) -> DivisionImageCopy | Exception:
    async with semaphore:
        try:
            return await copy_division_icon_asset(
                s3,
                source_workspace=source_workspace,
                target_workspace=target_workspace,
                source_tier=source_tier,
                target_grid_slug=target_grid_slug,
                target_version=target_version,
            )
        except Exception as exc:
            return exc


async def copy_division_icon_assets(
    s3: S3Client,
    *,
    source_workspace: models.Workspace,
    target_workspace: models.Workspace,
    source_tiers: Sequence[models.DivisionGridTier],
    target_grid_slug: str,
    target_version: int,
) -> list[DivisionImageCopy | Exception]:
    semaphore = asyncio.Semaphore(S3_COPY_CONCURRENCY)
    return list(
        await asyncio.gather(
            *(
                _copy_division_icon_asset_guarded(
                    semaphore,
                    s3,
                    source_workspace=source_workspace,
                    target_workspace=target_workspace,
                    source_tier=source_tier,
                    target_grid_slug=target_grid_slug,
                    target_version=target_version,
                )
                for source_tier in source_tiers
            )
        )
    )


def build_source_fingerprint(
    source_grids: Sequence[models.DivisionGrid],
    mappings: Sequence[models.DivisionGridMapping],
    *,
    source_version_id: int | None = None,
    include_icons: bool = True,
    include_native_rank_mappings: bool = True,
) -> str:
    version_key_by_id: dict[int, tuple[str, int]] = {}
    tier_key_by_id: dict[int, tuple[str, int, str]] = {}
    grids_payload = []
    for grid in sorted(source_grids, key=lambda item: (item.slug, getattr(item, "id", 0) or 0)):
        versions_payload = []
        for version in sorted(grid.versions, key=lambda item: item.version):
            if source_version_id is not None and version.id != source_version_id:
                continue
            version_id = getattr(version, "id", None)
            if version_id is not None:
                version_key_by_id[version_id] = (grid.slug, version.version)
            tiers_payload = []
            for tier in sorted(version.tiers, key=lambda item: item.sort_order):
                tier_id = getattr(tier, "id", None)
                if tier_id is not None:
                    tier_key_by_id[tier_id] = (grid.slug, version.version, tier.slug)
                tiers_payload.append(
                    {
                        "slug": tier.slug,
                        "number": tier.number,
                        "name": tier.name,
                        "sort_order": tier.sort_order,
                        "rank_min": tier.rank_min,
                        "rank_max": tier.rank_max,
                        "icon_url": tier.icon_url,
                        # Hash payload keys: renaming them would re-import every unchanged library grid.
                        "ow_rank_min": tier.native_rank_min,
                        "ow_rank_max": tier.native_rank_max,
                    }
                )
            versions_payload.append(
                {
                    "version": version.version,
                    "label": version.label,
                    "status": version.status,
                    "tiers": tiers_payload,
                }
            )
        grids_payload.append(
            {
                "slug": grid.slug,
                "name": grid.name,
                "description": grid.description,
                "versions": versions_payload,
            }
        )

    mappings_payload = []
    for mapping in mappings:
        mappings_payload.append(
            {
                "source": version_key_by_id.get(mapping.source_version_id),
                "target": version_key_by_id.get(mapping.target_version_id),
                "name": mapping.name,
                "rules": sorted(
                    (
                        {
                            "source": tier_key_by_id.get(rule.source_tier_id),
                            "target": tier_key_by_id.get(rule.target_tier_id),
                            "weight": float(rule.weight),
                            "is_primary": rule.is_primary,
                        }
                        for rule in mapping.rules
                    ),
                    key=lambda item: (str(item["source"]), str(item["target"])),
                ),
            }
        )
    mappings_payload.sort(key=lambda item: (str(item["source"]), str(item["target"])))
    canonical = json.dumps(
        {
            "grids": grids_payload,
            "mappings": mappings_payload,
            "include_icons": include_icons,
            # Hash input of the stored ``source_fingerprint``: the historical key keeps unchanged grids unchanged.
            "include_ow_rank_mappings": include_native_rank_mappings,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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


def _selected_source_versions(
    source_grids: Sequence[models.DivisionGrid],
    source_version_id: int | None,
) -> list[models.DivisionGridVersion]:
    versions = [
        version
        for grid in source_grids
        for version in grid.versions
        if source_version_id is None or version.id == source_version_id
    ]
    if source_version_id is not None and (len(source_grids) != 1 or len(versions) != 1):
        raise HTTPException(status_code=404, detail="Division grid version not found in the selected grid")
    return versions


def target_imported_version_state(
    *,
    mode: str,
    source_status: str,
    source_published_at: datetime | None,
) -> tuple[str, datetime | None]:
    if mode == "copy":
        return "draft", None
    return source_status, source_published_at


async def _cleanup_uploaded_keys(s3: S3Client, copied_keys: list[str]) -> None:
    for key in reversed(copied_keys):
        await s3.delete_object(key)


class MarketplaceService:
    """Cross-workspace division-grid discovery, preflight and import."""

    def __init__(
        self,
        *,
        grid_repo: DivisionGridRepository = DivisionGridRepository(),
        version_repo: DivisionGridVersionRepository = DivisionGridVersionRepository(),
        tier_repo: DivisionGridTierRepository = DivisionGridTierRepository(),
        mapping_repo: DivisionGridMappingRepository = DivisionGridMappingRepository(),
        workspace_repo: WorkspaceRepository = WorkspaceRepository(),
        grid_service: DivisionGridService = division_grid_service,
    ) -> None:
        self.grid_repo = grid_repo
        self.version_repo = version_repo
        self.tier_repo = tier_repo
        self.mapping_repo = mapping_repo
        self.workspace_repo = workspace_repo
        self.grid_service = grid_service

    async def make_unique_grid_slug(self, session: AsyncSession, workspace_id: int, desired_slug: str) -> str:
        base = desired_slug[:MAX_GRID_SLUG_LENGTH].rstrip("-") or "grid"
        candidate = base
        index = 1
        while True:
            if not await self.grid_repo.exists(session, workspace_id=workspace_id, slug=candidate):
                return candidate

            suffix = "-copy" if index == 1 else f"-copy-{index}"
            candidate = f"{_truncate_slug_base(base, suffix)}{suffix}"
            index += 1

    async def list_marketplace_workspaces(
        self,
        session: AsyncSession,
        *,
        target_workspace_id: int,
        user: models.AuthUser,
    ) -> list[schemas.DivisionGridMarketplaceWorkspaceRead]:
        """List other workspaces exposing an importable division grid.

        Cross-tenant by design: the caller already proved ``division_grid.read``
        on ``target_workspace_id`` (the RPC handler checks it), so they may browse
        every OTHER workspace's grids to import from, not only ones they belong
        to. As in ``WorkspaceService.get_all``, ``is_hidden`` only gates
        discoverability: a hidden source workspace stays restricted to its own
        members/superusers instead of the whole platform.
        """
        member_ids = set(user.get_workspace_ids())

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
        if not user.is_superuser:
            query = query.where(sa.or_(models.Workspace.is_hidden.is_(False), models.Workspace.id.in_(member_ids)))

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
        self,
        session: AsyncSession,
        *,
        source_workspace_id: int,
        source_grid_ids: Sequence[int],
    ) -> list[models.DivisionGrid]:
        if not source_grid_ids:
            return []

        result = await session.execute(
            self.grid_repo.select()
            .options(*_GRID_OPTIONS)
            .where(
                models.DivisionGrid.workspace_id == source_workspace_id,
                models.DivisionGrid.id.in_(source_grid_ids),
            )
            .order_by(models.DivisionGrid.id.asc())
        )
        grids_by_id = {grid.id: grid for grid in result.scalars().unique().all()}
        missing_ids = sorted(set(source_grid_ids) - set(grids_by_id))
        if missing_ids:
            raise HTTPException(
                status_code=404,
                detail=f"Division grid(s) not found in source workspace: {missing_ids}",
            )
        return [grids_by_id[grid_id] for grid_id in source_grid_ids]

    async def list_marketplace_grids(
        self,
        session: AsyncSession,
        *,
        source_workspace_id: int,
    ) -> list[schemas.DivisionGridMarketplaceGridRead]:
        result = await session.execute(
            self.grid_repo.select()
            .options(*_GRID_OPTIONS)
            .where(models.DivisionGrid.workspace_id == source_workspace_id)
            .order_by(models.DivisionGrid.name.asc(), models.DivisionGrid.id.asc())
        )
        return [build_marketplace_grid_read(grid) for grid in result.scalars().unique().all()]

    async def load_mappings_for_versions(
        self,
        session: AsyncSession,
        source_version_ids: set[int],
    ) -> list[models.DivisionGridMapping]:
        if not source_version_ids:
            return []

        result = await session.execute(
            self.mapping_repo.select()
            .options(*_MAPPING_RULES_OPTIONS)
            .where(
                models.DivisionGridMapping.source_version_id.in_(source_version_ids),
                models.DivisionGridMapping.target_version_id.in_(source_version_ids),
            )
        )
        return list(result.scalars().unique().all())

    async def preflight_division_grid_import(
        self,
        session: AsyncSession,
        *,
        public_url: str | None,
        target_workspace_id: int,
        source_workspace: models.Workspace,
        source_grids: Sequence[models.DivisionGrid],
        source_version_id: int | None = None,
        include_icons: bool = True,
        include_native_rank_mappings: bool = True,
    ) -> schemas.DivisionGridMarketplacePreflightResult:
        selected_versions = _selected_source_versions(source_grids, source_version_id)
        selected_version_ids = {version.id for version in selected_versions}
        mappings = await self.load_mappings_for_versions(session, selected_version_ids)
        selected_slugs = [grid.slug for grid in source_grids]
        existing_slugs = set(
            (
                await session.scalars(
                    sa.select(models.DivisionGrid.slug).where(
                        models.DivisionGrid.workspace_id == target_workspace_id,
                        models.DivisionGrid.slug.in_(selected_slugs),
                        models.DivisionGrid.archived_at.is_(None),
                    )
                )
            ).all()
        )

        tiers_count = 0
        assets_to_copy = 0
        assets_to_reuse = 0
        external_assets = 0
        warnings: list[schemas.DivisionGridMarketplaceImportWarning] = []
        versions_count = len(selected_versions)
        for grid in source_grids:
            for version in grid.versions:
                if version.id not in selected_version_ids:
                    continue
                tiers_count += len(version.tiers)
                if not include_icons:
                    continue
                for tier in version.tiers:
                    policy = classify_division_icon_asset(
                        public_url=public_url,
                        source_workspace_slug=source_workspace.slug,
                        image_url=tier.icon_url,
                    )
                    if policy.action == "copy":
                        assets_to_copy += 1
                    elif policy.action == "reuse":
                        assets_to_reuse += 1
                    else:
                        external_assets += 1
                        warnings.append(
                            schemas.DivisionGridMarketplaceImportWarning(
                                grid_slug=grid.slug,
                                message=f"{tier.slug}: {policy.warning}",
                            )
                        )
        return schemas.DivisionGridMarketplacePreflightResult(
            source_workspace_id=source_workspace.id,
            grids_count=len(source_grids),
            versions_count=versions_count,
            tiers_count=tiers_count,
            mappings_count=len(mappings),
            assets_to_copy=assets_to_copy,
            assets_to_reuse=assets_to_reuse,
            external_assets=external_assets,
            conflicts=sorted(existing_slugs),
            warnings=warnings,
            source_fingerprint=build_source_fingerprint(
                source_grids,
                mappings,
                source_version_id=source_version_id,
                include_icons=include_icons,
                include_native_rank_mappings=include_native_rank_mappings,
            ),
        )

    async def _load_current_imported_grids(
        self,
        session: AsyncSession,
        *,
        target_workspace_id: int,
        source_workspace_id: int,
        source_grid_ids: Sequence[int],
    ) -> dict[int, models.DivisionGrid]:
        result = await session.execute(
            self.grid_repo.select()
            .options(*_GRID_OPTIONS)
            .where(
                models.DivisionGrid.workspace_id == target_workspace_id,
                models.DivisionGrid.source_workspace_id == source_workspace_id,
                models.DivisionGrid.source_grid_id.in_(source_grid_ids),
                models.DivisionGrid.archived_at.is_(None),
            )
            .order_by(models.DivisionGrid.imported_at.desc(), models.DivisionGrid.id.desc())
        )
        imported: dict[int, models.DivisionGrid] = {}
        for grid in result.scalars().unique().all():
            if grid.source_grid_id is not None:
                imported.setdefault(grid.source_grid_id, grid)
        return imported

    async def import_division_grids(
        self,
        session: AsyncSession,
        s3: S3Client,
        *,
        target_workspace: models.Workspace,
        source_workspace: models.Workspace,
        source_grids: Sequence[models.DivisionGrid],
        mode: str = "library",
        expected_source_fingerprint: str | None = None,
        source_version_id: int | None = None,
        include_icons: bool = True,
        include_native_rank_mappings: bool = True,
    ) -> schemas.DivisionGridMarketplaceImportResult:
        # Validate the whole batch before copying or archiving any grid.
        for source_grid in source_grids:
            assert_discipline_enabled(target_workspace, source_grid.discipline)
        copied_keys: list[str] = []
        version_id_map: dict[int, int] = {}
        tier_id_map: dict[int, int] = {}
        imported_grids: list[schemas.DivisionGridMarketplaceImportedGrid] = []
        warnings: list[schemas.DivisionGridMarketplaceImportWarning] = []
        copied_mappings = 0
        created_grids = 0
        created_versions = 0
        created_tiers = 0
        reused_source_version_ids: set[int] = set()
        selected_versions = _selected_source_versions(source_grids, source_version_id)
        source_version_ids = {version.id for version in selected_versions}
        mappings = await self.load_mappings_for_versions(session, source_version_ids)
        source_fingerprint = build_source_fingerprint(
            source_grids,
            mappings,
            source_version_id=source_version_id,
            include_icons=include_icons,
            include_native_rank_mappings=include_native_rank_mappings,
        )
        source_fingerprints: dict[int, str] = {}
        for source_grid in source_grids:
            grid_version_ids = {
                version.id
                for version in source_grid.versions
                if source_version_id is None or version.id == source_version_id
            }
            grid_mappings = [
                mapping
                for mapping in mappings
                if mapping.source_version_id in grid_version_ids or mapping.target_version_id in grid_version_ids
            ]
            source_fingerprints[source_grid.id] = build_source_fingerprint(
                [source_grid],
                grid_mappings,
                source_version_id=source_version_id,
                include_icons=include_icons,
                include_native_rank_mappings=include_native_rank_mappings,
            )
        if expected_source_fingerprint is not None and source_fingerprint != expected_source_fingerprint:
            raise HTTPException(
                status_code=409,
                detail="Source division grids changed after preflight; review the import again",
            )
        source_grid_ids = [grid.id for grid in source_grids]
        current_imports = (
            await self._load_current_imported_grids(
                session,
                target_workspace_id=target_workspace.id,
                source_workspace_id=source_workspace.id,
                source_grid_ids=source_grid_ids,
            )
            if mode != "copy"
            else {}
        )
        unchanged_imports = {
            source_id: grid
            for source_id, grid in current_imports.items()
            if grid.source_fingerprint == source_fingerprints[source_id]
        }
        if len(unchanged_imports) == len(source_grids):
            return schemas.DivisionGridMarketplaceImportResult(
                created_grids=0,
                created_versions=0,
                created_tiers=0,
                copied_images=0,
                copied_mappings=0,
                imported_grids=[
                    schemas.DivisionGridMarketplaceImportedGrid(
                        source_grid_id=source_grid.id,
                        target_grid_id=unchanged_imports[source_grid.id].id,
                        slug=unchanged_imports[source_grid.id].slug,
                        name=unchanged_imports[source_grid.id].name,
                        versions_count=len(unchanged_imports[source_grid.id].versions),
                        tiers_count=sum(len(version.tiers) for version in unchanged_imports[source_grid.id].versions),
                    )
                    for source_grid in source_grids
                ],
                warnings=[
                    schemas.DivisionGridMarketplaceImportWarning(
                        grid_slug=source_grid.slug,
                        message="Unchanged imported grid was reused",
                    )
                    for source_grid in source_grids
                ],
            )

        try:
            # The icon copies are S3 round trips: all of them run before the workspace lock, none while holding it.
            # Their keys carry this import's own token, so a failed import never deletes objects another one uses.
            key_token = uuid4().hex[:8]
            icons: dict[int, list[DivisionImageCopy]] = {}
            for source_grid in source_grids:
                if source_grid.id in unchanged_imports:
                    continue
                for source_version in source_grid.versions:
                    if source_version_id is not None and source_version.id != source_version_id:
                        continue
                    source_tiers = sorted(source_version.tiers, key=lambda tier: tier.sort_order)
                    if not include_icons:
                        icons[source_version.id] = [
                            DivisionImageCopy(public_url=tier.icon_url, key=None) for tier in source_tiers
                        ]
                        continue
                    copied_icons = await copy_division_icon_assets(
                        s3,
                        source_workspace=source_workspace,
                        target_workspace=target_workspace,
                        source_tiers=source_tiers,
                        target_grid_slug=f"{source_grid.slug}-{key_token}",
                        target_version=source_version.version,
                    )
                    copied_keys.extend(
                        copied.key
                        for copied in copied_icons
                        if isinstance(copied, DivisionImageCopy) and copied.key is not None
                    )
                    copy_error = next((copied for copied in copied_icons if isinstance(copied, Exception)), None)
                    if copy_error is not None:
                        raise copy_error
                    icons[source_version.id] = [
                        copied for copied in copied_icons if isinstance(copied, DivisionImageCopy)
                    ]

            # Serializes concurrent imports into the same workspace. FOR NO KEY UPDATE: rows referencing the
            # workspace (tournaments, grids) still insert meanwhile.
            await self.workspace_repo.lock_by_id(session, target_workspace.id)
            if mode != "copy":
                locked_imports = await self._load_current_imported_grids(
                    session,
                    target_workspace_id=target_workspace.id,
                    source_workspace_id=source_workspace.id,
                    source_grid_ids=source_grid_ids,
                )
                if {source_id: grid.id for source_id, grid in locked_imports.items()} != {
                    source_id: grid.id for source_id, grid in current_imports.items()
                }:
                    raise HTTPException(
                        status_code=409,
                        detail="Another import changed this workspace's imported grids; review the import again",
                    )
            if mode == "sync":
                archived_at = datetime.now(UTC)
                for source_grid in source_grids:
                    previous = current_imports.get(source_grid.id)
                    if previous is not None and previous.source_fingerprint != source_fingerprints[source_grid.id]:
                        previous.archived_at = archived_at

            for source_grid in source_grids:
                if source_grid.id in unchanged_imports:
                    reused = unchanged_imports[source_grid.id]
                    reused_versions = {version.version: version for version in reused.versions}
                    for source_version in source_grid.versions:
                        if source_version_id is not None and source_version.id != source_version_id:
                            continue
                        target_version = reused_versions.get(source_version.version)
                        if target_version is None:
                            raise HTTPException(
                                status_code=409,
                                detail="Imported grid provenance does not match its source versions",
                            )
                        version_id_map[source_version.id] = target_version.id
                        reused_source_version_ids.add(source_version.id)
                        target_tiers = {tier.slug: tier for tier in target_version.tiers}
                        for source_tier in source_version.tiers:
                            target_tier = target_tiers.get(source_tier.slug)
                            if target_tier is None:
                                raise HTTPException(
                                    status_code=409,
                                    detail="Imported grid provenance does not match its source tiers",
                                )
                            tier_id_map[source_tier.id] = target_tier.id
                    imported_grids.append(
                        schemas.DivisionGridMarketplaceImportedGrid(
                            source_grid_id=source_grid.id,
                            target_grid_id=reused.id,
                            slug=reused.slug,
                            name=reused.name,
                            versions_count=len(reused.versions),
                            tiers_count=sum(len(version.tiers) for version in reused.versions),
                        )
                    )
                    warnings.append(
                        schemas.DivisionGridMarketplaceImportWarning(
                            grid_slug=source_grid.slug,
                            message="Unchanged imported grid was reused",
                        )
                    )
                    continue

                target_slug = await self.make_unique_grid_slug(session, target_workspace.id, source_grid.slug)
                target_grid = await self.grid_repo.create(
                    session,
                    models.DivisionGrid(
                        workspace_id=target_workspace.id,
                        discipline=source_grid.discipline,
                        slug=target_slug,
                        name=source_grid.name,
                        description=source_grid.description,
                        source_workspace_id=source_workspace.id,
                        source_grid_id=source_grid.id,
                        source_key=(
                            f"workspace:{source_workspace.id}:grid:{source_grid.id}" if mode == "sync" else None
                        ),
                        source_fingerprint=source_fingerprints[source_grid.id],
                        imported_at=datetime.now(UTC),
                    ),
                )
                created_grids += 1

                grid_versions_count = 0
                grid_tiers_count = 0
                source_versions = sorted(
                    (
                        version
                        for version in source_grid.versions
                        if source_version_id is None or version.id == source_version_id
                    ),
                    key=lambda version: version.version,
                )
                pending_created_from: list[tuple[models.DivisionGridVersion, int | None]] = []

                for source_version in source_versions:
                    target_status, target_published_at = target_imported_version_state(
                        mode=mode,
                        source_status=source_version.status,
                        source_published_at=source_version.published_at,
                    )
                    target_version = await self.version_repo.create(
                        session,
                        models.DivisionGridVersion(
                            grid_id=target_grid.id,
                            version=source_version.version,
                            label=source_version.label,
                            status=target_status,
                            created_from_version_id=None,
                            published_at=target_published_at,
                        ),
                    )
                    version_id_map[source_version.id] = target_version.id
                    pending_created_from.append((target_version, source_version.created_from_version_id))
                    grid_versions_count += 1
                    created_versions += 1

                    source_tiers = sorted(source_version.tiers, key=lambda tier: tier.sort_order)
                    pending_tiers: list[tuple[models.DivisionGridTier, int]] = []
                    for source_tier, copied in zip(source_tiers, icons[source_version.id], strict=True):
                        if copied.warning is not None:
                            warnings.append(
                                schemas.DivisionGridMarketplaceImportWarning(
                                    grid_slug=source_grid.slug,
                                    message=f"{source_tier.slug}: {copied.warning}",
                                )
                            )

                        pending_tiers.append(
                            (
                                models.DivisionGridTier(
                                    version_id=target_version.id,
                                    slug=source_tier.slug,
                                    number=source_tier.number,
                                    name=source_tier.name,
                                    sort_order=source_tier.sort_order,
                                    rank_min=source_tier.rank_min,
                                    rank_max=source_tier.rank_max,
                                    icon_url=copied.public_url,
                                    native_rank_min=source_tier.native_rank_min
                                    if include_native_rank_mappings
                                    else None,
                                    native_rank_max=source_tier.native_rank_max
                                    if include_native_rank_mappings
                                    else None,
                                ),
                                source_tier.id,
                            )
                        )

                    stamp_canonical_numbers([tier for tier, _ in pending_tiers], target_grid.discipline)
                    # One INSERT batch per version instead of a flush per tier.
                    await self.tier_repo.create_many(session, [tier for tier, _ in pending_tiers])
                    for target_tier, source_tier_id in pending_tiers:
                        tier_id_map[source_tier_id] = target_tier.id
                    grid_tiers_count += len(pending_tiers)
                    created_tiers += len(pending_tiers)

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

            for source_mapping in mappings:
                if (
                    source_mapping.source_version_id in reused_source_version_ids
                    and source_mapping.target_version_id in reused_source_version_ids
                ):
                    continue
                target_source_version_id = version_id_map.get(source_mapping.source_version_id)
                target_target_version_id = version_id_map.get(source_mapping.target_version_id)
                if target_source_version_id is None or target_target_version_id is None:
                    continue

                target_rules: list[schemas.DivisionGridMappingRuleWrite] = []
                for source_rule in source_mapping.rules:
                    target_source_tier_id = tier_id_map.get(source_rule.source_tier_id)
                    target_target_tier_id = tier_id_map.get(source_rule.target_tier_id)
                    if target_source_tier_id is None or target_target_tier_id is None:
                        warnings.append(
                            schemas.DivisionGridMarketplaceImportWarning(
                                message=(
                                    f"Skipped mapping rule #{source_rule.id}: source or target tier was not imported"
                                ),
                            )
                        )
                        continue
                    target_rules.append(
                        schemas.DivisionGridMappingRuleWrite(
                            source_tier_id=target_source_tier_id,
                            target_tier_id=target_target_tier_id,
                            weight=source_rule.weight,
                            is_primary=source_rule.is_primary,
                        )
                    )
                await self.grid_service.upsert_mapping(
                    session,
                    source_version_id=target_source_version_id,
                    target_version_id=target_target_version_id,
                    data=schemas.DivisionGridMappingWrite(
                        name=source_mapping.name,
                        rules=target_rules,
                    ),
                )
                copied_mappings += 1
            await session.flush()

        except Exception:
            await _cleanup_uploaded_keys(s3, copied_keys)
            raise

        return schemas.DivisionGridMarketplaceImportResult(
            created_grids=created_grids,
            created_versions=created_versions,
            created_tiers=created_tiers,
            copied_images=len(copied_keys),
            copied_mappings=copied_mappings,
            imported_grids=imported_grids,
            warnings=warnings,
        )


marketplace_service = MarketplaceService()
