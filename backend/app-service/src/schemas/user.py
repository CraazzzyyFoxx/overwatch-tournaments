import typing
from dataclasses import dataclass, field

import sqlalchemy as sa
from pydantic import BaseModel, Field

from src import schemas
from src.core import enums, pagination
from src.schemas.base import Score
from src.schemas.division_grid import DivisionGridVersionRead

__all__ = (
    "UserProfile",
    "UserRole",
    "UserTournamentWithStats",
    "UserTournament",
    "UserTournamentSummary",
    "UserTournamentPlayer",
    "UserEncounterTournament",
    "UserEncounterStageSummary",
    "UserEncounterStageItemSummary",
    "UserEncounterTeamSummary",
    "UserEncounterTeamPlayerRef",
    "MatchReadWithUserStats",
    "EncounterReadWithUserStats",
    "UserMap",
    "UserMapHeroStats",
    "UserMapHighlight",
    "UserMapsOverall",
    "UserMapsSummary",
    "UserMapsSearchParams",
    "UserMapsSearchQueryParams",
    "UserTournamentStat",
    "LobbyLeaderboardEntry",
    "LobbyLeaderboard",
    "HeroStat",
    "HeroWithUserStats",
    "HeroStatBest",
    "UserBestTeammate",
    "UserOpponentStat",
    "UserStageRecord",
    "UserMatchesSummary",
    "UserSearch",
    "UserOverviewRoleDivision",
    "UserOverviewHeroMetric",
    "UserOverviewHero",
    "UserOverviewAverages",
    "UserOverviewRow",
    "UserOverviewQueryParams",
    "UserOverviewParams",
    "UserOverviewStats",
    "UserOverviewStatsQueryParams",
    "UserCatalogLetter",
    "UserCatalogEntry",
    "UserCatalogResponse",
    "UserCatalogQueryParams",
    "UserCatalogParams",
    "UserCompareQueryParams",
    "UserCompareParams",
    "UserCompareBaselineMode",
    "UserCompareUser",
    "UserCompareBaselineInfo",
    "UserCompareMetric",
    "UserCompareResponse",
    "UserHeroCompareQueryParams",
    "UserHeroCompareParams",
    "UserHeroCompareMetric",
    "UserHeroCompareResponse",
)

from src.schemas import MapRead


class UserRole(BaseModel):
    role: enums.HeroClass
    tournaments: int
    maps_won: int
    maps: int
    division: int
    division_grid_version: DivisionGridVersionRead | None = None


class UserTournamentSummary(BaseModel):
    """Tournament card shown in user profile / achievement filter lists.

    Narrow projection of `models.Tournament` — only fields the frontend
    actually consumes in user-scoped pages.
    """

    id: int
    number: int | None
    name: str
    is_league: bool
    is_finished: bool = False
    status: enums.TournamentStatus | None = None
    division_grid_version: DivisionGridVersionRead | None = None


class UserTournamentPlayer(BaseModel):
    """Player card inside `UserTournament.players` (rendered by TournamentTeamTable).

    Also populated inside `UserEncounterTeamSummary.players` when the
    encounter view needs to identify the viewer's row (via `user_id`).
    """

    id: int
    name: str
    role: enums.HeroClass | None = None
    sub_role: str | None = None
    rank: int
    division: int
    user_id: int
    is_substitution: bool
    is_newcomer: bool
    is_newcomer_role: bool
    related_player_id: int | None = None
    relative_player: int | None = None
    # Average MVP placement (1 = best) across this player's matches in THIS
    # tournament. Mirrors the dossier "Avg MVP" metric: per match take
    # COALESCE(ImpactRank, Performance); ImpactRank preferred, Performance the
    # legacy fallback. `None` when the player has no such stat rows.
    avg_mvp: float | None = None
    # This player's top heroes by playtime in THIS tournament (same hero-read
    # shape used elsewhere on the response). Empty when none recorded.
    heroes: list[schemas.HeroRead] = Field(default_factory=list)


class UserEncounterTournament(BaseModel):
    """Tournament link inside `EncounterReadWithUserStats.tournament`."""

    id: int
    name: str
    number: int | None = None
    is_league: bool
    is_finished: bool = False
    status: enums.TournamentStatus | None = None


class UserEncounterStageSummary(BaseModel):
    """Stage link inside `EncounterReadWithUserStats.stage`."""

    id: int
    name: str


class UserEncounterStageItemSummary(BaseModel):
    """Stage-item link inside `EncounterReadWithUserStats.stage_item`."""

    id: int
    name: str


class UserEncounterTeamPlayerRef(BaseModel):
    """Player reference inside encounter teams — minimal id+user_id+role.

    Used only by the frontend to identify which side the viewer played on
    (`players.find(p => p.user_id === selfUserId)`). Renders nothing on its
    own — for the full player card see `UserTournamentPlayer`.
    """

    id: int
    user_id: int
    role: enums.HeroClass | None = None
    name: str


class UserEncounterTeamSummary(BaseModel):
    """Team summary inside `EncounterReadWithUserStats.{home,away}_team`."""

    id: int
    name: str
    players: list[UserEncounterTeamPlayerRef] = Field(default_factory=list)


class MatchReadWithUserStats(BaseModel):
    """Match within a user-scoped encounter, with the viewer's performance."""

    id: int
    home_team_id: int | None = None
    away_team_id: int | None = None
    score: Score
    time: float
    log_name: str
    encounter_id: int
    map_id: int
    code: str | None = None
    map: MapRead | None = None
    performance: int | None = None
    impact_rank: int | None = None
    impact_points: float | None = None
    overperformance_score: float | None = None
    overperformance_badge: bool = False
    heroes: list[schemas.HeroRead] = Field(default_factory=list)


class EncounterReadWithUserStats(BaseModel):
    """Encounter rendered on the user encounters page."""

    id: int
    name: str
    home_team_id: int | None = None
    away_team_id: int | None = None
    score: Score
    round: int
    best_of: int = 3
    tournament_id: int
    status: str
    closeness: float | None = None
    has_logs: bool = False
    result_status: str = "none"
    user_team_id: int | None = None  # which side the viewer played on
    tournament: UserEncounterTournament | None = None
    stage: UserEncounterStageSummary | None = None
    stage_item: UserEncounterStageItemSummary | None = None
    home_team: UserEncounterTeamSummary | None = None
    away_team: UserEncounterTeamSummary | None = None
    matches: list[MatchReadWithUserStats] = Field(default_factory=list)


class UserTournament(BaseModel):
    id: int
    number: int | None
    name: str
    is_league: bool
    team_id: int
    team: str
    players: list[UserTournamentPlayer]
    closeness: float
    placement: int | None
    count_teams: int
    won: int
    lost: int
    draw: int
    maps_won: int
    maps_lost: int
    # Nullable because the user may not have a Player record on the team
    # (e.g. teams returned for adjacency aggregates have no resolved role).
    role: enums.HeroClass | None = None
    division: int | None = None
    division_grid_version: DivisionGridVersionRead | None = None
    encounters: list[EncounterReadWithUserStats]


class UserTournamentStat(BaseModel):
    value: float
    rank: int
    total: int


class UserTournamentWithStats(BaseModel):
    id: int
    number: int | None
    name: str
    division: int
    # `division` is resolved against the tournament's own grid (see
    # get_tournament_with_stats). Ship the grid version too so the frontend
    # renders the division icon on that same grid instead of falling back to
    # the workspace default.
    division_grid_version: DivisionGridVersionRead | None = None
    closeness: float
    role: enums.HeroClass
    group_placement: float | None
    playoff_placement: float | None
    maps_won: int
    maps: int
    playtime: float

    stats: dict[enums.LogStatsName | typing.Literal["winrate"], UserTournamentStat]


class LobbyLeaderboardEntry(BaseModel):
    """One player's ranked value for a single stat inside a tournament lobby."""

    rank: int
    player_id: int  # user id (models.User.id)
    name: str
    value: float


class LobbyLeaderboard(BaseModel):
    """Full ranked list of every player in a tournament for one stat.

    Exposes the whole ranked population behind a single user's
    ``UserTournamentWithStats.stats[stat].{rank,total}`` so the frontend can
    render a per-stat "lobby leaderboard" modal.
    """

    stat: enums.LogStatsName
    total_players: int
    entries: list[LobbyLeaderboardEntry]


class UserMapHeroStats(BaseModel):
    hero: schemas.HeroRead
    games: int
    win: int
    loss: int
    draw: int
    win_rate: float
    playtime_seconds: float
    playtime_share_on_map: float


class UserMap(BaseModel):
    map: MapRead
    count: int
    win: int
    loss: int
    draw: int
    win_rate: float
    heroes: list[schemas.HeroPlaytime]
    hero_stats: list[UserMapHeroStats] | None = None


class UserMapHighlight(BaseModel):
    map: MapRead
    count: int
    win: int
    loss: int
    draw: int
    win_rate: float


class UserMapsOverall(BaseModel):
    total_maps: int
    total_games: int
    win: int
    loss: int
    draw: int
    win_rate: float


class UserMapsSummary(BaseModel):
    overall: UserMapsOverall
    most_played: UserMapHighlight | None
    best: UserMapHighlight | None
    worst: UserMapHighlight | None


class UserMapsSearchQueryParams(pagination.PaginationSortSearchQueryParams):
    min_count: int | None = Field(default=None, ge=1)
    gamemode_id: int | None = None
    tournament_id: int | None = None


@dataclass
class UserMapsSearchParams(pagination.PaginationSortSearchParams):
    min_count: int | None = None
    gamemode_id: int | None = None
    tournament_id: int | None = None

    def apply_search(self, query: sa.Select, model: type) -> sa.Select:
        fields = self.fields if self.fields else ["name"]
        return pagination.apply_search(model, query, self.query, fields)


class UserProfile(BaseModel):
    tournaments_count: int
    tournaments_won: int
    maps_total: int
    maps_won: int
    avg_closeness: float | None
    avg_placement: float | None
    avg_playoff_placement: float | None
    avg_group_placement: float | None
    most_played_hero: schemas.HeroRead | None
    heroes_count: int

    roles: list[UserRole]
    tournaments: list[UserTournamentSummary]
    hero_statistics: list[schemas.HeroPlaytime]


class HeroStatBest(BaseModel):
    encounter_id: int
    tournament_name: str
    map_name: str
    map_image_path: str
    value: float
    player_name: str


class HeroStat(BaseModel):
    name: enums.LogStatsName
    overall: float
    best: HeroStatBest
    avg_10: float
    best_all: HeroStatBest | None
    avg_10_all: float


class HeroWithUserStats(BaseModel):
    hero: schemas.HeroRead
    stats: list[HeroStat]


class UserBestTeammate(BaseModel):
    user: schemas.UserRead
    tournaments: int
    maps: int
    winrate: float
    stats: dict[enums.LogStatsName, float | None]


class UserOpponentStat(BaseModel):
    name: str
    wins: int
    losses: int
    draws: int


class UserStageRecord(BaseModel):
    w: int
    l: int  # noqa: E741 — terse {w,l} record mirrored by the Matches-tab sidebar


class UserMatchesSummary(BaseModel):
    """Aggregates for the Matches-tab sidebars, computed over ALL the user's
    encounters (not just the current page): most-fought opponents + per-stage
    win/loss record."""

    opponents: list[UserOpponentStat]
    stages: dict[str, UserStageRecord]


class UserSearch(BaseModel):
    id: int
    name: str


class UserOverviewRoleDivision(BaseModel):
    role: enums.HeroClass
    division: int


class UserOverviewHeroMetric(BaseModel):
    name: enums.LogStatsName
    avg_10: float


class UserOverviewHero(BaseModel):
    hero: schemas.HeroRead
    playtime_seconds: float
    metrics: list[UserOverviewHeroMetric]


class UserOverviewAverages(BaseModel):
    avg_closeness: float | None
    avg_placement: float | None
    avg_playoff_placement: float | None
    avg_group_placement: float | None


class UserOverviewRow(BaseModel):
    id: int
    name: str
    roles: list[UserOverviewRoleDivision]
    top_heroes: list[UserOverviewHero]
    tournaments_count: int
    achievements_count: int
    averages: UserOverviewAverages


class UserOverviewQueryParams(
    pagination.PaginationSortSearchQueryParams[
        typing.Literal[
            "id",
            "name",
            "tournaments_count",
            "achievements_count",
            "avg_placement",
        ]
    ]
):
    role: enums.HeroClass | None = None
    div_min: int | None = Field(default=None, ge=1, le=20)
    div_max: int | None = Field(default=None, ge=1, le=20)


@dataclass
class UserOverviewParams(pagination.PaginationSortSearchParams):
    role: enums.HeroClass | None = None
    div_min: int | None = None
    div_max: int | None = None

    def apply_search(self, query: sa.Select, model: type) -> sa.Select:
        fields = self.fields if self.fields else ["name"]
        return pagination.apply_search(model, query, self.query, fields)


class UserOverviewStats(BaseModel):
    total_players: int
    with_logs_count: int
    with_logs_pct: float
    avg_tournaments_per_player: float
    median_tournaments_per_player: float
    active_last_30d: int
    active_last_30d_pct: float
    tank_count: int
    damage_count: int
    support_count: int
    flex_count: int


class UserOverviewStatsQueryParams(BaseModel):
    role: enums.HeroClass | None = None
    div_min: int | None = Field(default=None, ge=1, le=20)
    div_max: int | None = Field(default=None, ge=1, le=20)
    query: str | None = None


class UserCatalogEntry(BaseModel):
    id: int
    name: str
    roles: list[UserOverviewRoleDivision]
    top_heroes: list[UserOverviewHero]
    tournaments_count: int
    achievements_count: int
    avg_placement: float | None


class UserCatalogLetter(BaseModel):
    letter: str
    count: int
    users: list[UserCatalogEntry]


class UserCatalogResponse(BaseModel):
    letters: list[UserCatalogLetter]
    total: int
    available_letters: list[str]


class UserCatalogQueryParams(BaseModel):
    role: enums.HeroClass | None = None
    div_min: int | None = Field(default=None, ge=1, le=20)
    div_max: int | None = Field(default=None, ge=1, le=20)
    query: str | None = None
    letter: str | None = Field(default=None, min_length=1, max_length=2)
    per_letter: int = Field(default=12, ge=1, le=50)
    max_letters: int = Field(default=27, ge=1, le=40)


@dataclass
class UserCatalogParams:
    role: enums.HeroClass | None = None
    div_min: int | None = None
    div_max: int | None = None
    query: str | None = None
    letter: str | None = None
    per_letter: int = 12
    max_letters: int = 27

    @classmethod
    def from_query_params(cls, query_params: UserCatalogQueryParams) -> "UserCatalogParams":
        data = query_params.model_dump()
        if data.get("letter"):
            data["letter"] = data["letter"].upper()
        return cls(**data)


UserCompareBaselineMode = typing.Literal["target_user", "global", "cohort"]


class UserCompareUser(BaseModel):
    id: int
    name: str


class UserCompareBaselineInfo(BaseModel):
    mode: UserCompareBaselineMode
    sample_size: int
    target_user: UserCompareUser | None
    role: enums.HeroClass | None
    div_min: int | None
    div_max: int | None


class UserCompareMetric(BaseModel):
    key: str
    label: str
    subject_value: float | int | None
    baseline_value: float | int | None
    delta: float | None
    delta_percent: float | None
    better_worse: typing.Literal["better", "worse", "equal"] | None
    higher_is_better: bool
    subject_rank: int | None
    subject_percentile: float | None


class UserCompareResponse(BaseModel):
    subject: UserCompareUser
    baseline: UserCompareBaselineInfo
    metrics: list[UserCompareMetric]


class UserCompareQueryParams(BaseModel):
    baseline: UserCompareBaselineMode = "global"
    target_user_id: int | None = Field(default=None, ge=1)
    role: enums.HeroClass | None = None
    div_min: int | None = Field(default=None, ge=1, le=20)
    div_max: int | None = Field(default=None, ge=1, le=20)
    tournament_id: int | None = Field(default=None, ge=1)


@dataclass
class UserCompareParams:
    baseline: UserCompareBaselineMode = "global"
    target_user_id: int | None = None
    role: enums.HeroClass | None = None
    div_min: int | None = None
    div_max: int | None = None
    tournament_id: int | None = None

    @classmethod
    def from_query_params(cls, query_params: UserCompareQueryParams):
        return cls(**query_params.model_dump())


class UserHeroCompareMetric(BaseModel):
    stat: enums.LogStatsName
    left_value: float
    right_value: float
    delta: float
    delta_percent: float | None
    better_worse: typing.Literal["better", "worse", "equal"] | None
    higher_is_better: bool


class UserHeroCompareResponse(BaseModel):
    subject: UserCompareUser
    target: UserCompareUser | None
    baseline: UserCompareBaselineInfo
    subject_hero: schemas.HeroRead | None
    target_hero: schemas.HeroRead | None
    map: schemas.MapRead | None
    left_playtime_seconds: float
    right_playtime_seconds: float
    metrics: list[UserHeroCompareMetric]


class UserHeroCompareQueryParams(BaseModel):
    baseline: UserCompareBaselineMode = "global"
    target_user_id: int | None = Field(default=None, ge=1)
    left_hero_id: int | None = Field(default=None, ge=1)
    right_hero_id: int | None = Field(default=None, ge=1)
    map_id: int | None = Field(default=None, ge=1)
    role: enums.HeroClass | None = None
    div_min: int | None = Field(default=None, ge=1, le=20)
    div_max: int | None = Field(default=None, ge=1, le=20)
    tournament_id: int | None = Field(default=None, ge=1)
    stats: list[enums.LogStatsName] | None = None


@dataclass
class UserHeroCompareParams:
    baseline: UserCompareBaselineMode = "global"
    target_user_id: int | None = None
    left_hero_id: int | None = None
    right_hero_id: int | None = None
    map_id: int | None = None
    role: enums.HeroClass | None = None
    div_min: int | None = None
    div_max: int | None = None
    tournament_id: int | None = None
    stats: list[enums.LogStatsName] = field(default_factory=list)

    @classmethod
    def from_query_params(cls, query_params: UserHeroCompareQueryParams):
        payload = query_params.model_dump()
        payload["stats"] = payload.get("stats") or []
        return cls(**payload)
