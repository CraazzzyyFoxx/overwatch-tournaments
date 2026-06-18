"""
RBAC (Role-Based Access Control) schemas
"""
from datetime import datetime

from pydantic import BaseModel, Field

__all__ = (
    "AuthUserLinkedPlayerRead",
    "AuthUserListRead",
    "AuthUserDetailRead",
    "AdminSessionRead",
    "AuthUserPlayerLinkAssign",
    "PermissionBase",
    "PermissionCreate",
    "PermissionRead",
    "RoleBase",
    "RoleCreate",
    "RoleUpdate",
    "RoleRead",
    "RoleWithPermissions",
    "UserRoleAssign",
    "UserRoleRemove",
)


# Permission Schemas
class PermissionBase(BaseModel):
    """Base permission schema"""
    name: str = Field(..., description="Unique permission name", max_length=100)
    resource: str = Field(..., description="Resource type (e.g., 'tournament', 'user')", max_length=100)
    action: str = Field(..., description="Action type (e.g., 'create', 'read', 'update', 'delete')", max_length=50)
    description: str | None = Field(None, description="Permission description")


class PermissionCreate(PermissionBase):
    """Schema for creating a permission"""
    pass


class PermissionRead(PermissionBase):
    """Schema for reading a permission"""
    id: int
    created_at: datetime
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


# Role Schemas
class RoleBase(BaseModel):
    """Base role schema"""
    name: str = Field(..., description="Unique role name", max_length=100)
    description: str | None = Field(None, description="Role description")


class RoleCreate(RoleBase):
    """Schema for creating a role"""
    permission_ids: list[int] = Field(default_factory=list, description="List of permission IDs to assign")
    workspace_id: int | None = Field(None, description="Workspace ID for scoped roles. NULL = global role")


class RoleUpdate(BaseModel):
    """Schema for updating a role"""
    name: str | None = Field(None, max_length=100)
    description: str | None = None
    permission_ids: list[int] | None = Field(None, description="List of permission IDs to assign")


class RoleRead(RoleBase):
    """Schema for reading a role"""
    id: int
    is_system: bool
    workspace_id: int | None = None
    created_at: datetime
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class RoleWithPermissions(RoleRead):
    """Schema for role with permissions"""
    permissions: list[PermissionRead] = Field(default_factory=list)

    class Config:
        from_attributes = True


class AuthUserLinkedPlayerRead(BaseModel):
    """Schema for a player account linked to an auth user."""

    player_id: int
    player_name: str
    is_primary: bool
    linked_at: str


class AuthUserListRead(BaseModel):
    """Schema for listing auth users with assigned roles."""

    id: int
    email: str
    username: str
    first_name: str | None = None
    last_name: str | None = None
    avatar_url: str | None = None
    is_active: bool
    is_superuser: bool
    is_verified: bool
    linked_players: list[AuthUserLinkedPlayerRead] = Field(default_factory=list)
    roles: list[RoleRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class AuthUserDetailRead(AuthUserListRead):
    """Schema for auth-user detail view with effective permissions."""

    effective_permissions: list[str] = Field(default_factory=list)


class AdminSessionRead(BaseModel):
    """Schema for superuser session inventory across all auth users."""

    session_id: str
    user_id: int
    email: str | None = None
    username: str | None = None
    status: str
    login_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    user_agent: str | None = None
    ip_address: str | None = None


class AuthUserPlayerLinkAssign(BaseModel):
    """Schema for assigning a player account to an auth user from admin tools."""

    player_id: int = Field(..., gt=0)
    is_primary: bool = True


# User Role Assignment Schemas
class UserRoleAssign(BaseModel):
    """Schema for assigning role to user"""
    user_id: int = Field(..., description="User ID")
    role_id: int = Field(..., description="Role ID")


class UserRoleRemove(BaseModel):
    """Schema for removing role from user"""
    user_id: int = Field(..., description="User ID")
    role_id: int = Field(..., description="Role ID")
