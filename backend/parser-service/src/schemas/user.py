from pydantic import BaseModel

from src.schemas import BaseRead

__all__ = (
    "UserCSV",
    "UserRead",
    "SocialAccountRead",
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


class SocialAccountRead(BaseRead):
    """Unified player social identity (battlenet/discord/twitch/boosty/vk/youtube/…)."""

    user_id: int
    provider: str
    username: str
    url: str | None = None
    is_verified: bool = False
    is_primary: bool = False


class UserRead(BaseRead):
    name: str
    avatar_url: str | None = None
    social_accounts: list[SocialAccountRead] = []


class UserUpdate(BaseModel):
    name: str
