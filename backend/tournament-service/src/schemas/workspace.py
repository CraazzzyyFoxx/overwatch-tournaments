from pydantic import BaseModel, Field

from src.schemas.base import BaseRead
from src.schemas.division_grid import DivisionGridVersionRead

__all__ = (
    "WorkspaceRead",
    "WorkspaceCreate",
    "WorkspaceUpdate",
    "WorkspaceMemberRead",
    "WorkspaceMemberCreate",
    "WorkspaceMemberUpdate",
)


class WorkspaceRead(BaseRead):
    slug: str
    name: str
    description: str | None
    icon_url: str | None
    is_active: bool
    default_division_grid_version_id: int | None
    default_division_grid_version: DivisionGridVersionRead | None = None


class WorkspaceCreate(BaseModel):
    slug: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$")
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    icon_url: str | None = None
    default_division_grid_version_id: int | None = None


class WorkspaceUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    icon_url: str | None = None
    is_active: bool | None = None
    default_division_grid_version_id: int | None = None


class WorkspaceMemberRead(BaseRead):
    workspace_id: int
    auth_user_id: int
    role: str
    username: str | None = None


class WorkspaceMemberCreate(BaseModel):
    auth_user_id: int
    role: str = Field(default="member", pattern=r"^(owner|admin|member)$")


class WorkspaceMemberUpdate(BaseModel):
    role: str = Field(..., pattern=r"^(owner|admin|member)$")
