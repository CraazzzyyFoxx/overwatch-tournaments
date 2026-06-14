from pydantic import BaseModel

from src.schemas import BaseRead

__all__ = (
    "UserCSV",
    "UserRead",
    "UserDiscordRead",
    "UserTwitchRead",
    "UserBattleTagRead",
    "UserUpdate",
)


class UserCSV(BaseModel):
    battle_tag: str
    discord: str | None
    twitch: str
    smurfs: list[str]


class UserDiscordRead(BaseRead):
    user_id: int
    name: str


class UserBattleTagRead(BaseRead):
    user_id: int
    name: str
    tag: int
    battle_tag: str


class UserTwitchRead(BaseRead):
    user_id: int
    name: str


class UserRead(BaseRead):
    name: str
    discord: list[UserDiscordRead]
    battle_tag: list[UserBattleTagRead]
    twitch: list[UserTwitchRead]


class UserUpdate(BaseModel):
    name: str
