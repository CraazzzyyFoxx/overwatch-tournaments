from src.schemas.base import BaseRead, Score
from src.schemas.map import MapRead
from src.schemas.stage import StageItemRead, StageRead
from src.schemas.team import TeamRead
from src.schemas.tournament import TournamentRead

__all__ = ("EncounterRead", "MatchRead")


class EncounterRead(BaseRead):
    name: str
    home_team_id: int
    away_team_id: int
    score: Score
    round: int
    tournament_id: int
    stage_id: int | None = None
    stage_item_id: int | None = None
    challonge_id: int | None
    status: str
    closeness: float | None
    has_logs: bool
    result_status: str = "none"
    submitted_by_id: int | None = None
    confirmed_by_id: int | None = None

    stage: StageRead | None
    stage_item: StageItemRead | None
    tournament: TournamentRead | None
    home_team: TeamRead | None
    away_team: TeamRead | None
    matches: list["MatchRead"]


class MatchRead(BaseRead):
    home_team_id: int
    away_team_id: int
    score: Score
    time: float
    log_name: str

    encounter_id: int
    map_id: int
    code: str | None = None

    home_team: TeamRead | None
    away_team: TeamRead | None
    encounter: EncounterRead | None
    map: MapRead | None
