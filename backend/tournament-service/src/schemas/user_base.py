from pydantic import BaseModel

from src.schemas import BaseRead

__all__ = (
    "UserCSV",
    "UserRead",
    "SocialAccountRead",
    "UserUpdate",
)


class UserCSV(BaseModel):
    battle_tag: str
    discord: str | None
    twitch: str
    smurfs: list[str]


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
    social_accounts: list[SocialAccountRead] = []


class UserUpdate(BaseModel):
    name: str
