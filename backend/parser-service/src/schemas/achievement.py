from pydantic import BaseModel

__all__ = (
    "AchievementCalculateRequest",
    "AchievementCalculateResponse",
)


class AchievementCalculateRequest(BaseModel):
    slugs: list[str] | None = None
    ensure_created: bool = True
    workspace_id: int | None = None


class AchievementCalculateResponse(BaseModel):
    tournament_id: int | None
    executed: list[str]
    message: str
