from pydantic import BaseModel, Field

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
    # Display visibility (populated only when the visibilities relationship is
    # loaded — e.g. the admin profile dialog). ``visible_global`` = shown on the
    # public profile; ``visible_workspace_ids`` = workspaces it is shown in.
    visible_global: bool = True
    visible_workspace_ids: list[int] = Field(default_factory=list)


class UserRead(BaseRead):
    name: str
    avatar_url: str | None = None
    social_accounts: list[SocialAccountRead] = []


class UserUpdate(BaseModel):
    name: str
