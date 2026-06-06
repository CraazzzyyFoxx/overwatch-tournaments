from pydantic import BaseModel

from src.schemas.base import BaseRead
from src.schemas.stage import StageItemRead, StageRead
from src.schemas.team import TeamRead
from src.schemas.tournament import TournamentRead

__all__ = (
    "StandingTeamData",
    "StandingTeamDataWithBuchholzTB",
    "StandingTeamDataWithRanking",
    "StandingRead",
)


class StandingTeamData(BaseModel):
    id: int
    wins: int
    draws: int
    loses: int
    points: float
    opponents: list[int]
    matches: int


class StandingTeamDataWithBuchholzTB(StandingTeamData):
    buchholz: float
    tb: int


class StandingTeamDataWithRanking(StandingTeamData):
    ranking: int | float


class StandingRead(BaseRead):
    tournament_id: int
    team_id: int
    stage_id: int | None = None
    stage_item_id: int | None = None
    position: int
    overall_position: int
    matches: int
    win: int
    draw: int
    lose: int
    points: float
    buchholz: float | None
    tb: int | None = None
    score_differential: int | None = None
    ranking_context: dict[str, str | int | float | None] | None = None
    tb_metrics: dict[str, int | float | None] | None = None
    source_rule_profile: str | None = None
    tiebreak_order: list[str] | None = None

    team: TeamRead | None
    stage: StageRead | None
    stage_item: StageItemRead | None
    tournament: TournamentRead | None
