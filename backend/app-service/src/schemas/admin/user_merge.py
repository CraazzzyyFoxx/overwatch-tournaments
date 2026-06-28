from __future__ import annotations

import typing

from pydantic import BaseModel, Field

__all__ = (
    "UserMergePreviewRequest",
    "UserMergeFieldPolicy",
    "UserMergeIdentitySelection",
    "UserMergeExecuteRequest",
    "UserMergeIdentityOption",
    "UserMergeUserSummary",
    "UserMergeConflictSummary",
    "UserMergeFieldOptions",
    "UserMergePreviewResponse",
    "UserMergeIdentityResult",
    "UserMergeExecuteResponse",
)

MergeFieldChoice = typing.Literal["source", "target"]


class UserMergePreviewRequest(BaseModel):
    source_user_id: int = Field(ge=1)
    target_user_id: int = Field(ge=1)


class UserMergeFieldPolicy(BaseModel):
    name: MergeFieldChoice = "target"
    avatar_url: MergeFieldChoice = "target"


class UserMergeIdentitySelection(BaseModel):
    # social_account ids on the source profile to move to the target (others are
    # dropped with the deleted source). Replaces the legacy per-provider id lists.
    social_account_ids: list[int] = Field(default_factory=list)


class UserMergeExecuteRequest(UserMergePreviewRequest):
    preview_fingerprint: str = Field(min_length=1)
    field_policy: UserMergeFieldPolicy
    identity_selection: UserMergeIdentitySelection


class UserMergeIdentityOption(BaseModel):
    id: int
    provider: str
    value: str
    duplicate_on_target: bool = False


class UserMergeUserSummary(BaseModel):
    id: int
    name: str
    avatar_url: str | None = None
    social_accounts: list[UserMergeIdentityOption]
    auth_links: int = 0


class UserMergeConflictSummary(BaseModel):
    has_auth_conflict: bool = False
    summary: str | None = None


class UserMergeFieldOptions(BaseModel):
    name: dict[MergeFieldChoice, str | None]
    avatar_url: dict[MergeFieldChoice, str | None]


class UserMergePreviewResponse(BaseModel):
    source: UserMergeUserSummary
    target: UserMergeUserSummary
    conflicts: UserMergeConflictSummary
    affected_counts: dict[str, int]
    field_options: UserMergeFieldOptions
    preview_fingerprint: str


class UserMergeIdentityResult(BaseModel):
    moved: list[int]
    deduped: list[int]


class UserMergeExecuteResponse(BaseModel):
    deleted_source_user_id: int
    surviving_target_user_id: int
    affected_counts: dict[str, int]
    identity_results: UserMergeIdentityResult
    audit_id: int
