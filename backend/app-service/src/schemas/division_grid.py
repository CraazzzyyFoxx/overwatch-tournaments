from datetime import datetime

from pydantic import BaseModel, Field

from src.schemas.base import BaseRead

__all__ = (
    "DivisionGridTierRead",
    "DivisionGridTierWrite",
    "DivisionGridVersionRead",
    "DivisionGridRead",
    "DivisionGridCreate",
    "DivisionGridVersionCreate",
    "DivisionGridVersionUpdate",
    "DivisionGridMappingRuleRead",
    "DivisionGridMappingRuleWrite",
    "DivisionGridMappingRead",
    "DivisionGridMappingWrite",
    "DivisionGridMarketplaceWorkspaceRead",
    "DivisionGridMarketplaceVersionRead",
    "DivisionGridMarketplaceGridRead",
    "DivisionGridMarketplaceImportRequest",
    "DivisionGridMarketplaceImportedGrid",
    "DivisionGridMarketplaceImportWarning",
    "DivisionGridMarketplaceImportResult",
)


class DivisionGridTierRead(BaseRead):
    version_id: int
    slug: str
    number: int
    name: str
    sort_order: int
    rank_min: int
    rank_max: int | None
    icon_url: str


class DivisionGridVersionRead(BaseRead):
    grid_id: int
    version: int
    label: str
    status: str
    created_from_version_id: int | None
    published_at: datetime | None
    tiers: list[DivisionGridTierRead] = Field(default_factory=list)


class DivisionGridRead(BaseRead):
    workspace_id: int | None
    slug: str
    name: str
    description: str | None
    versions: list[DivisionGridVersionRead] = Field(default_factory=list)


class DivisionGridCreate(BaseModel):
    slug: str = Field(..., min_length=1, max_length=128)
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None


class DivisionGridVersionCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=255)
    tiers: list["DivisionGridTierWrite"] = Field(..., min_length=1)


class DivisionGridVersionUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=255)
    tiers: list["DivisionGridTierWrite"] | None = None


class DivisionGridTierWrite(BaseModel):
    slug: str = Field(..., min_length=1, max_length=128)
    number: int
    name: str = Field(..., min_length=1, max_length=255)
    sort_order: int
    rank_min: int
    rank_max: int | None
    icon_url: str = Field(..., min_length=1, max_length=2048)


class DivisionGridMappingRuleRead(BaseRead):
    mapping_id: int
    source_tier_id: int
    target_tier_id: int
    weight: float
    is_primary: bool


class DivisionGridMappingRuleWrite(BaseModel):
    source_tier_id: int
    target_tier_id: int
    weight: float = Field(..., gt=0)
    is_primary: bool = False


class DivisionGridMappingRead(BaseRead):
    source_version_id: int
    target_version_id: int
    name: str
    is_complete: bool
    rules: list[DivisionGridMappingRuleRead] = Field(default_factory=list)


class DivisionGridMappingWrite(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    rules: list[DivisionGridMappingRuleWrite] = Field(default_factory=list)


class DivisionGridMarketplaceWorkspaceRead(BaseModel):
    id: int
    slug: str
    name: str
    grids_count: int
    versions_count: int


class DivisionGridMarketplaceVersionRead(BaseModel):
    id: int
    version: int
    label: str
    status: str
    tiers_count: int
    preview_icon_urls: list[str] = Field(default_factory=list)


class DivisionGridMarketplaceGridRead(BaseModel):
    id: int
    slug: str
    name: str
    description: str | None
    versions_count: int
    tiers_count: int
    preview_icon_urls: list[str] = Field(default_factory=list)
    versions: list[DivisionGridMarketplaceVersionRead] = Field(default_factory=list)


class DivisionGridMarketplaceImportRequest(BaseModel):
    source_workspace_id: int
    source_grid_ids: list[int] = Field(..., min_length=1)
    set_default: bool = False


class DivisionGridMarketplaceImportedGrid(BaseModel):
    source_grid_id: int
    target_grid_id: int
    slug: str
    name: str
    versions_count: int
    tiers_count: int


class DivisionGridMarketplaceImportWarning(BaseModel):
    grid_slug: str | None = None
    message: str


class DivisionGridMarketplaceImportResult(BaseModel):
    created_grids: int
    created_versions: int
    created_tiers: int
    copied_images: int
    copied_mappings: int
    imported_grids: list[DivisionGridMarketplaceImportedGrid] = Field(default_factory=list)
    warnings: list[DivisionGridMarketplaceImportWarning] = Field(default_factory=list)


DivisionGridVersionCreate.model_rebuild()
DivisionGridVersionUpdate.model_rebuild()
