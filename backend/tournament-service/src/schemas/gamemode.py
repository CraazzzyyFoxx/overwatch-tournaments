from pydantic import BaseModel

from src.schemas import BaseRead

__all__ = (
    "OverfastGamemode",
    "GamemodeRead",
)


class OverfastGamemode(BaseModel):
    key: str
    name: str
    icon: str
    description: str
    screenshot: str


class GamemodeRead(BaseRead):
    slug: str
    name: str
    image_path: str
    description: str | None
