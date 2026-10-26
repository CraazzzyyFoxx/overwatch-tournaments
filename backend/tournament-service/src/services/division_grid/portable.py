from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.errors import BaseAPIException as HTTPException
from shared.division_grid import stamp_canonical_numbers
from shared.repository import (
    DivisionGridRepository,
    DivisionGridTierRepository,
    DivisionGridVersionRepository,
    WorkspaceRepository,
)
from shared.services.ontology import assert_discipline_enabled
from src import schemas
from src.services.division_grid.marketplace import MarketplaceService, marketplace_service
from src.services.division_grid.service import DivisionGridService, _validate_version_payload, division_grid_service

__all__ = ("PortableService", "build_portable_document", "portable_service")


def build_portable_document(
    grid: models.DivisionGrid,
    mappings: Sequence[models.DivisionGridMapping],
) -> schemas.DivisionGridPortableDocument:
    version_number_by_id = {version.id: version.version for version in grid.versions}
    tier_slug_by_id = {tier.id: tier.slug for version in grid.versions for tier in version.tiers}
    versions = [
        schemas.DivisionGridPortableVersion(
            version=version.version,
            label=version.label,
            status=version.status,
            tiers=[
                schemas.DivisionGridTierWrite(
                    slug=tier.slug,
                    number=tier.number,
                    name=tier.name,
                    sort_order=tier.sort_order,
                    rank_min=tier.rank_min,
                    rank_max=tier.rank_max,
                    icon_url=tier.icon_url,
                    native_rank_min=tier.native_rank_min,
                    native_rank_max=tier.native_rank_max,
                )
                for tier in sorted(version.tiers, key=lambda item: item.sort_order)
            ],
        )
        for version in sorted(grid.versions, key=lambda item: item.version)
    ]
    portable_mappings = []
    for mapping in mappings:
        source_version = version_number_by_id.get(mapping.source_version_id)
        target_version = version_number_by_id.get(mapping.target_version_id)
        if source_version is None or target_version is None:
            continue
        rules = []
        for rule in mapping.rules:
            source_slug = tier_slug_by_id.get(rule.source_tier_id)
            target_slug = tier_slug_by_id.get(rule.target_tier_id)
            if source_slug is None or target_slug is None:
                continue
            rules.append(
                schemas.DivisionGridPortableMappingRule(
                    source_tier_slug=source_slug,
                    target_tier_slug=target_slug,
                    weight=rule.weight,
                    is_primary=rule.is_primary,
                )
            )
        portable_mappings.append(
            schemas.DivisionGridPortableMapping(
                source_version=source_version,
                target_version=target_version,
                name=mapping.name,
                rules=rules,
            )
        )

    return schemas.DivisionGridPortableDocument(
        discipline=grid.discipline,
        slug=grid.slug,
        name=grid.name,
        description=grid.description,
        versions=versions,
        mappings=portable_mappings,
    )


def _document_fingerprint(document: schemas.DivisionGridPortableDocument) -> str:
    canonical = document.model_dump_json(exclude_none=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class PortableService:
    """Import/export of a whole division grid as a self-describing document."""

    def __init__(
        self,
        *,
        grid_repo: DivisionGridRepository = DivisionGridRepository(),
        version_repo: DivisionGridVersionRepository = DivisionGridVersionRepository(),
        tier_repo: DivisionGridTierRepository = DivisionGridTierRepository(),
        workspace_repo: WorkspaceRepository = WorkspaceRepository(),
        grid_service: DivisionGridService = division_grid_service,
        marketplace: MarketplaceService = marketplace_service,
    ) -> None:
        self.grid_repo = grid_repo
        self.version_repo = version_repo
        self.tier_repo = tier_repo
        self.workspace_repo = workspace_repo
        self.grid_service = grid_service
        self.marketplace = marketplace

    async def export_portable_document(
        self,
        session: AsyncSession,
        *,
        grid_id: int,
    ) -> schemas.DivisionGridPortableDocument:
        grid = await self.grid_service.get_grid_by_id(session, grid_id)
        version_ids = {version.id for version in grid.versions}
        mappings = await self.marketplace.load_mappings_for_versions(session, version_ids)
        return build_portable_document(grid, mappings)

    async def import_portable_document(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        request: schemas.DivisionGridPortableImportRequest,
    ) -> models.DivisionGrid:
        document = request.document
        workspace = await self.workspace_repo.get(session, workspace_id)
        if workspace is None:
            raise HTTPException(status_code=404, detail="Workspace not found")
        assert_discipline_enabled(workspace, document.discipline)
        version_numbers = [version.version for version in document.versions]
        if len(version_numbers) != len(set(version_numbers)):
            raise HTTPException(status_code=400, detail="Portable grid contains duplicate version numbers")
        for version in document.versions:
            _validate_version_payload(version.tiers)

        fingerprint = _document_fingerprint(document)
        source_key = f"portable:{document.slug}"
        # Serializes concurrent portable imports into the same workspace.
        await self.workspace_repo.lock_by_id(session, workspace_id)
        provenance_filter = (
            models.DivisionGrid.source_key == source_key
            if request.mode == "sync"
            else sa.and_(
                models.DivisionGrid.source_workspace_id.is_(None),
                models.DivisionGrid.source_grid_id.is_(None),
            )
        )
        existing = await session.scalar(
            self.grid_repo.select()
            .where(
                models.DivisionGrid.workspace_id == workspace_id,
                models.DivisionGrid.discipline == document.discipline,
                provenance_filter,
                models.DivisionGrid.source_fingerprint == fingerprint,
                models.DivisionGrid.archived_at.is_(None),
            )
            .order_by(models.DivisionGrid.id.desc())
            .limit(1)
        )
        if request.mode != "copy" and existing is not None:
            return await self.grid_service.get_grid_by_id(session, existing.id)

        if request.mode == "sync":
            current = await session.scalar(
                self.grid_repo.select()
                .where(
                    models.DivisionGrid.workspace_id == workspace_id,
                    models.DivisionGrid.discipline == document.discipline,
                    models.DivisionGrid.source_key == source_key,
                    models.DivisionGrid.archived_at.is_(None),
                )
                .order_by(models.DivisionGrid.id.desc())
                .limit(1)
            )
            if current is not None:
                current.archived_at = datetime.now(UTC)

        target_slug = await self.marketplace.make_unique_grid_slug(session, workspace_id, document.slug)
        grid = await self.grid_repo.create(
            session,
            models.DivisionGrid(
                workspace_id=workspace_id,
                discipline=document.discipline,
                slug=target_slug,
                name=document.name,
                description=document.description,
                source_key=source_key if request.mode == "sync" else None,
                source_fingerprint=fingerprint,
                imported_at=datetime.now(UTC),
            ),
        )

        versions_by_number: dict[int, models.DivisionGridVersion] = {}
        tiers_by_version_and_slug: dict[tuple[int, str], models.DivisionGridTier] = {}
        for portable_version in sorted(document.versions, key=lambda item: item.version):
            version = await self.version_repo.create(
                session,
                models.DivisionGridVersion(
                    grid_id=grid.id,
                    version=portable_version.version,
                    label=portable_version.label,
                    status=portable_version.status,
                    published_at=datetime.now(UTC) if portable_version.status == "published" else None,
                ),
            )
            versions_by_number[portable_version.version] = version
            pending_tiers = [
                (
                    portable_tier.slug,
                    models.DivisionGridTier(
                        version_id=version.id,
                        slug=portable_tier.slug,
                        number=portable_tier.number,
                        name=portable_tier.name,
                        sort_order=portable_tier.sort_order,
                        rank_min=portable_tier.rank_min,
                        rank_max=portable_tier.rank_max,
                        icon_url=portable_tier.icon_url,
                        native_rank_min=portable_tier.native_rank_min,
                        native_rank_max=portable_tier.native_rank_max,
                    ),
                )
                for portable_tier in sorted(portable_version.tiers, key=lambda item: item.sort_order)
            ]
            stamp_canonical_numbers([tier for _, tier in pending_tiers], document.discipline)
            # One INSERT batch per version instead of a flush per tier.
            await self.tier_repo.create_many(session, [tier for _, tier in pending_tiers])
            for slug, tier in pending_tiers:
                tiers_by_version_and_slug[(portable_version.version, slug)] = tier

        for portable_mapping in document.mappings:
            source_version = versions_by_number.get(portable_mapping.source_version)
            target_version = versions_by_number.get(portable_mapping.target_version)
            if source_version is None or target_version is None:
                raise HTTPException(status_code=400, detail="Portable mapping references an unknown version")

            rules: list[schemas.DivisionGridMappingRuleWrite] = []
            for portable_rule in portable_mapping.rules:
                source_tier = tiers_by_version_and_slug.get(
                    (portable_mapping.source_version, portable_rule.source_tier_slug)
                )
                target_tier = tiers_by_version_and_slug.get(
                    (portable_mapping.target_version, portable_rule.target_tier_slug)
                )
                if source_tier is None or target_tier is None:
                    raise HTTPException(status_code=400, detail="Portable mapping references an unknown tier slug")
                rules.append(
                    schemas.DivisionGridMappingRuleWrite(
                        source_tier_id=source_tier.id,
                        target_tier_id=target_tier.id,
                        weight=portable_rule.weight,
                        is_primary=portable_rule.is_primary,
                    )
                )
            await self.grid_service.upsert_mapping(
                session,
                source_version_id=source_version.id,
                target_version_id=target_version.id,
                data=schemas.DivisionGridMappingWrite(name=portable_mapping.name, rules=rules),
            )
        await session.flush()
        return await self.grid_service.get_grid_by_id(session, grid.id)


portable_service = PortableService()
