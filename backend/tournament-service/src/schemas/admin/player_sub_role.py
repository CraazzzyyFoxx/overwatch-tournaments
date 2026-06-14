from pydantic import BaseModel

from src.schemas import BaseRead

__all__ = (
    "PlayerSubRoleCreate",
    "PlayerSubRoleRead",
    "PlayerSubRoleUpdate",
)


class PlayerSubRoleRead(BaseRead):
    workspace_id: int
    role: str
    slug: str
    label: str
    description: str | None
    sort_order: int
    is_active: bool


class PlayerSubRoleCreate(BaseModel):
    workspace_id: int
    role: str
    label: str
    slug: str | None = None
    description: str | None = None
    sort_order: int = 0
    is_active: bool = True


class PlayerSubRoleUpdate(BaseModel):
    role: str | None = None
    label: str | None = None
    slug: str | None = None
    description: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None
