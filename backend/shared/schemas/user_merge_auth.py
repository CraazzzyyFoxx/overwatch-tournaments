from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class AuthMergeOAuthDestination(BaseModel):
    connection_id: int = Field(ge=1)
    auth_user_id: int = Field(ge=1)


class AuthMergeMembershipAction(BaseModel):
    workspace_id: int = Field(ge=1)
    action: Literal["transfer", "merge"]

class AuthMergePolicy(BaseModel):
    surviving_auth_user_id: int = Field(ge=1)
    other_account_action: Literal["keep", "delete"] = "keep"
    oauth_destinations: list[AuthMergeOAuthDestination] = Field(default_factory=list)
    conflict_choices: dict[str, Literal["source", "target"]] = Field(default_factory=dict)
    membership_actions: list[AuthMergeMembershipAction] = Field(default_factory=list)


class AuthMergeRole(BaseModel):
    id: int
    name: str
    workspace_id: int | None = None


class AuthMergeDeny(BaseModel):
    permission_id: int
    workspace_id: int | None = None
    resource: str
    action: str
    reason: str | None = None


class AuthMergeAccount(BaseModel):
    id: int
    username: str
    email: str
    has_password: bool
    is_active: bool
    is_superuser: bool
    roles: list[AuthMergeRole] = Field(default_factory=list)
    denies: list[AuthMergeDeny] = Field(default_factory=list)


class AuthMergeOAuthConnection(BaseModel):
    id: int
    provider: str
    provider_user_id: str
    username: str
    auth_user_id: int


class AuthMergeDataConflict(BaseModel):
    key: str
    resource: str
    label: str
    source_value: Any
    target_value: Any


class AuthMergeMembership(BaseModel):
    workspace_id: int
    auth_user_id: int
    role_names: list[str]
    can_merge: bool

class AuthMergePreview(BaseModel):
    accounts: list[AuthMergeAccount]
    oauth_connections: list[AuthMergeOAuthConnection]
    policy: AuthMergePolicy
    resource_counts: dict[str, int] = Field(default_factory=dict)
    data_conflicts: list[AuthMergeDataConflict] = Field(default_factory=list)
    permission_changes: bool = False
    memberships: list[AuthMergeMembership] = Field(default_factory=list)
    state_fingerprint: str


class AuthMergeResult(BaseModel):
    surviving_auth_user_id: int
    deleted_auth_user_id: int | None = None
    moved_oauth_connection_ids: list[int] = Field(default_factory=list)
    transferred_counts: dict[str, int] = Field(default_factory=dict)
    revoked_session_ids: list[str] = Field(default_factory=list, exclude=True)
    affected_auth_user_ids: list[int] = Field(default_factory=list, exclude=True)


class AuthMergeFinalizationRequest(BaseModel):
    auth_user_ids: list[Annotated[int, Field(ge=1)]] = Field(min_length=1, max_length=2)
    session_ids: list[UUID] = Field(default_factory=list)
