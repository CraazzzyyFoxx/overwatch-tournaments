from pydantic import BaseModel

from .base import BaseRead

__all__ = ("AchievementRead", "UserAchievementRead", "AchievementEarned")

from src.schemas import HeroRead, MatchRead, TournamentRead, UserRead


class AchievementRead(BaseRead):
    name: str
    slug: str
    description_ru: str
    description_en: str
    image_url: str | None
    hero_id: int | None
    rarity: float

    category: str | None = None
    scope: str | None = None
    condition_tree: dict | None = None

    hero: HeroRead | None
    count: int | None


class UserAchievementRead(AchievementRead):
    count: int
    tournaments_ids: list[int]
    tournaments: list[TournamentRead]
    matches_ids: list[int]
    matches: list[MatchRead]


class AchievementEarned(BaseModel):
    user: UserRead
    count: int
    last_tournament: TournamentRead | None
    last_match: MatchRead | None
