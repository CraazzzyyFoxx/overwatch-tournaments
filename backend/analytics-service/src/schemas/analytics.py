from datetime import datetime

from pydantic import BaseModel


__all__ = ("AnalyticsMatch",)


class AnalyticsMatch(BaseModel):
    tournament_id: int
    home_team_id: int
    home_team_name: str
    away_team_id: int
    away_team_name: str
    home_players: list[str]
    away_players: list[str]
    home_score: int
    away_score: int
    time: datetime
