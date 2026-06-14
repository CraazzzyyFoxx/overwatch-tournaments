from pydantic import BaseModel

from src.schemas import BaseRead, GamemodeRead

__all__ = (
    "OverfastMap",
    "MapRead",
)


class OverfastMap(BaseModel):
    name: str
    screenshot: str
    gamemodes: list[str]
    location: str
    country_code: str | None


class MapRead(BaseRead):
    gamemode_id: int
    name: str
    image_path: str

    gamemode: GamemodeRead | None
