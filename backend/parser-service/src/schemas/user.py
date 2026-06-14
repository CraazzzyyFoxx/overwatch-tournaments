from pydantic import BaseModel

from src.schemas import BaseRead

__all__ = (
    "UserCSV",
    "UserRead",
    "UserDiscordRead",
    "UserTwitchRead",
    "UserBattleTagRead",
    "UserUpdate",
    "UserDasha",
)


class UserCSV(BaseModel):
    battle_tag: str
    discord: str | None
    twitch: str | None
    smurfs: list[str]


class UserDasha(BaseModel):
    id: int
    battle_tag: str
    nickname: str
    twitch: str
    discord: str | None

    twitches: list[str]
    discords: list[str]
    battle_tags: list[str]


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
    avatar_url: str | None = None
    discord: list[UserDiscordRead]
    battle_tag: list[UserBattleTagRead]
    twitch: list[UserTwitchRead]


class UserUpdate(BaseModel):
    name: str
