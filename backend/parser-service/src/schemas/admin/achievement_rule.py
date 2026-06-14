"""Pydantic schemas for the achievement rule engine admin API."""

from __future__ import annotations

import typing
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, Field

from src.core import pagination

__all__ = (
    "AchievementRuleRead",
    "AchievementRuleCreate",
    "AchievementRuleUpdate",
    "AchievementRulePortable",
    "AchievementRuleExportWorkspace",
    "AchievementRuleExportEnvelope",
    "AchievementRuleImportResult",
    "AchievementImportWarning",
    "AchievementLibraryWorkspaceRead",
    "AchievementLibraryRuleRead",
    "AchievementLibraryImportRequest",
    "AchievementRuleListParams",
    "AchievementRuleListQueryParams",
    "ConditionTreeValidateRequest",
    "ConditionTreeValidateResponse",
    "EvaluationRunRead",
    "SeedResultRead",
    "HardResetResultRead",
    "EvaluateRequest",
    "OverrideCreate",
    "OverrideRead",
    "ConditionTypeInfo",
)


class AchievementRuleRead(BaseModel):
    id: int
    workspace_id: int
    slug: str
    name: str
    description_ru: str
    description_en: str
    image_url: str | None
    hero_id: int | None
    category: str
    scope: str
    grain: str
    condition_tree: dict
    depends_on: list[str]
    enabled: bool
    rule_version: int
    min_tournament_id: int | None
    created_at: datetime
    updated_at: datetime | None


class AchievementRuleCreate(BaseModel):
    slug: str
    name: str
    description_ru: str
    description_en: str
    image_url: str | None = None
    hero_id: int | None = None
    category: str
    scope: str
    grain: str
    condition_tree: dict
    depends_on: list[str] = Field(default_factory=list)
    enabled: bool = True
    rule_version: int = 1
    min_tournament_id: int | None = None


class AchievementRuleUpdate(BaseModel):
    slug: str | None = None
    name: str | None = None
    description_ru: str | None = None
    description_en: str | None = None
    image_url: str | None = None
    hero_id: int | None = None
    category: str | None = None
    scope: str | None = None
    grain: str | None = None
    condition_tree: dict | None = None
    depends_on: list[str] | None = None
    enabled: bool | None = None
    rule_version: int | None = None
    min_tournament_id: int | None = None


class AchievementRulePortable(BaseModel):
    slug: str
    name: str
    description_ru: str
    description_en: str
    image_url: str | None = None
    hero_id: int | None = None
    category: str
    scope: str
    grain: str
    condition_tree: dict
    depends_on: list[str] = Field(default_factory=list)
    enabled: bool = True
    rule_version: int = 1
    min_tournament_id: int | None = None


class AchievementRuleExportWorkspace(BaseModel):
    id: int
    slug: str
    name: str


class AchievementRuleExportEnvelope(BaseModel):
    schema_version: int = 1
    exported_at: datetime
    source_workspace: AchievementRuleExportWorkspace | None = None
    rules: list[AchievementRulePortable]


class AchievementImportWarning(BaseModel):
    slug: str
    message: str


class AchievementRuleImportResult(BaseModel):
    created: int
    updated: int
    warnings: list[AchievementImportWarning] = Field(default_factory=list)


class AchievementLibraryWorkspaceRead(BaseModel):
    id: int
    slug: str
    name: str
    rules_count: int


class AchievementLibraryRuleRead(BaseModel):
    slug: str
    name: str
    category: str
    enabled: bool
    image_url: str | None = None


class AchievementLibraryImportRequest(BaseModel):
    source_workspace_id: int
    slugs: list[str] = Field(default_factory=list, min_length=1)


class AchievementRuleListQueryParams(
    pagination.PaginationSortQueryParams[
        typing.Literal["id", "name", "slug", "category", "created_at"]
    ]
):
    per_page: int = Field(default=50, ge=-1, le=500)
    sort: typing.Literal["id", "name", "slug", "category", "created_at"] = "id"
    search: str | None = None
    category: str | None = None
    enabled: bool | None = None


@dataclass
class AchievementRuleListParams(pagination.PaginationSortParams):
    per_page: int = 50
    search: str | None = None
    category: str | None = None
    enabled: bool | None = None


class ConditionTreeValidateRequest(BaseModel):
    condition_tree: dict


class ConditionTreeValidateResponse(BaseModel):
    valid: bool
    errors: list[str]
    inferred_grain: str | None = None


class EvaluationRunRead(BaseModel):
    id: str
    workspace_id: int
    trigger: str
    tournament_id: int | None
    rules_evaluated: int
    results_created: int
    results_removed: int
    started_at: datetime
    finished_at: datetime | None
    status: str
    error_message: str | None


class SeedResultRead(BaseModel):
    seeded: int
    removed: int = 0


class HardResetResultRead(BaseModel):
    seeded: int
    removed: int
    cleared_results: int
    run: EvaluationRunRead


class EvaluateRequest(BaseModel):
    tournament_id: int | None = None
    rule_ids: list[int] | None = None


class OverrideCreate(BaseModel):
    achievement_rule_id: int
    user_id: int
    tournament_id: int | None = None
    match_id: int | None = None
    action: str  # "grant" or "revoke"
    reason: str


class OverrideRead(BaseModel):
    id: int
    achievement_rule_id: int
    user_id: int
    tournament_id: int | None
    match_id: int | None
    action: str
    reason: str
    granted_by: int
    created_at: datetime


class ConditionTypeInfo(BaseModel):
    name: str
    grain: str
    description: str
    required_params: list[str]
    optional_params: list[str]
