from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import sqlalchemy as sa
from pydantic import BaseModel, Field

from src.core import db, pagination
from src.schemas import (
    BaseRead,
    MapRead,
    Score,
    StageItemSummaryRead,
    StageSummaryRead,
    TeamRead,
    TeamWithMatchStats,
    TournamentRead,
)

__all__ = (
    "EncounterFeaturedRead",
    "EncounterFiltersRead",
    "EncounterHistogramBucketRead",
    "EncounterKpiRead",
    "EncounterMapMetricRead",
    "EncounterRead",
    "EncounterOverviewRead",
    "EncounterPulseRead",
    "EncounterSavedViewCreate",
    "EncounterSavedViewRead",
    "EncounterScoreHeatmapCellRead",
    "EncounterSummaryRead",
    "EncounterSideBalanceRead",
    "EncounterStageSplitRead",
    "MatchRead",
    "MatchReadWithStats",
    "EncounterSearchParams",
    "EncounterSearchQueryParams",
    "MatchSearchParams",
    "MatchSearchQueryParams",
)


class EncounterSummaryRead(BaseRead):
    name: str
    home_team_id: int | None = None
    away_team_id: int | None = None
    score: Score
    round: int
    tournament_id: int
    stage_id: int | None = None
    stage_item_id: int | None = None
    status: str
    result_status: str = "none"


class EncounterRead(BaseRead):
    name: str
    home_team_id: int | None = None
    away_team_id: int | None = None
    score: Score
    round: int
    best_of: int = 3
    tournament_id: int
    stage_id: int | None = None
    stage_item_id: int | None = None
    challonge_id: int | None
    closeness: float | None
    has_logs: bool
    status: str
    result_status: str = "none"
    scheduled_at: datetime | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    current_map_index: int | None = None
    submitted_by_id: int | None = None
    submitted_at: datetime | None = None
    confirmed_by_id: int | None = None
    confirmed_at: datetime | None = None

    stage: StageSummaryRead | None
    stage_item: StageItemSummaryRead | None
    tournament: TournamentRead | None
    home_team: TeamRead | None
    away_team: TeamRead | None
    matches: list["MatchRead"]


class MatchRead(BaseRead):
    home_team_id: int | None = None
    away_team_id: int | None = None
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


class MatchReadWithStats(MatchRead):
    rounds: int
    home_team: TeamWithMatchStats
    away_team: TeamWithMatchStats


class EncounterFiltersRead(BaseModel):
    query: str = ""
    stage_id: int | None = None
    stage_item_id: int | None = None
    best_of: int | None = None
    status: str | None = None
    has_logs: bool | None = None
    closeness_min: float | None = None
    closeness_max: float | None = None
    scope: Literal["all", "my_team"] = "all"
    sort: str = "date"


class EncounterSavedViewCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    filters: EncounterFiltersRead


class EncounterSavedViewRead(BaseRead):
    name: str
    filters: EncounterFiltersRead
    sort_order: int
    workspace_id: int


class EncounterKpiRead(BaseModel):
    total_encounters: int
    recent_count: int
    with_logs_count: int
    with_logs_pct: float
    avg_closeness: float | None
    live_now_count: int
    upcoming_count: int


class EncounterHistogramBucketRead(BaseModel):
    label: str
    start: float
    end: float
    count: int


class EncounterScoreHeatmapCellRead(BaseModel):
    home: int
    away: int
    count: int


class EncounterStageSplitRead(BaseModel):
    name: str
    count: int
    pct: float


class EncounterMapMetricRead(BaseModel):
    name: str
    count: int


class EncounterPulseRead(BaseModel):
    avg_series_seconds: float | None
    completed_series_count: int
    sweep_rate: float
    sweep_count: int
    went_distance_count: int
    reverse_sweep_rate: float
    most_decisive_map: str | None


class EncounterSideBalanceRead(BaseModel):
    home_wins: int
    away_wins: int
    home_win_pct: float
    away_win_pct: float


class EncounterFeaturedRead(BaseModel):
    closest: list[EncounterRead]
    upcoming: list[EncounterRead]
    live: list[EncounterRead]


class EncounterOverviewRead(BaseModel):
    kpis: EncounterKpiRead
    preset_counts: dict[str, int]
    closeness_histogram: list[EncounterHistogramBucketRead]
    score_heatmap: list[EncounterScoreHeatmapCellRead]
    stage_split: list[EncounterStageSplitRead]
    featured: EncounterFeaturedRead
    hot_maps: list[EncounterMapMetricRead]
    pulse: EncounterPulseRead
    side_balance: EncounterSideBalanceRead


@dataclass
class EncounterSearchParams(pagination.PaginationSortSearchParams):
    tournament_id: int | None = None
    stage_id: int | None = None
    stage_item_id: int | None = None
    best_of: int | None = None
    status: str | None = None
    has_logs: bool | None = None
    closeness_min: float | None = None
    closeness_max: float | None = None
    scope: Literal["all", "my_team"] = "all"

    def apply_search(self, query: sa.Select, model: type[db.Base]) -> sa.Select:
        criteria = []
        search_query = f"%{self.query}%"
        for field in self.fields:
            column = model.depth_get_column(field.split("."))
            criteria.append(column.ilike(search_query))
            if field == "name":
                reverted_name = sa.func.concat(
                    (sa.func.split_part(column, " vs ", 2)),
                    " vs ",
                    (sa.func.split_part(column, " vs ", 1)),
                )
                criteria.append(reverted_name.ilike(f"%{self.query}%"))
        return query.where(sa.or_(*criteria))


class EncounterSearchQueryParams(pagination.PaginationSortSearchQueryParams):
    tournament_id: int | None = None
    stage_id: int | None = None
    stage_item_id: int | None = None
    best_of: int | None = None
    status: str | None = None
    has_logs: bool | None = None
    closeness_min: float | None = Field(default=None, ge=0.0, le=1.0)
    closeness_max: float | None = Field(default=None, ge=0.0, le=1.0)
    scope: Literal["all", "my_team"] = "all"


@dataclass
class MatchSearchParams(pagination.PaginationSortSearchParams):
    tournament_id: int | None = None
    home_team_id: int | None = None
    away_team_id: int | None = None

    def apply_search(self, query: sa.Select, model: type[db.Base]) -> sa.Select:
        criteria = []
        search_query = f"%{self.query}%"
        for field in self.fields:
            column = model.depth_get_column(field.split("."))
            criteria.append(column.ilike(search_query))
            if field == "log_name":
                criteria.append(sa.func.split_part(column, ".", 1).ilike(search_query))
        return query.where(sa.or_(*criteria))


class MatchSearchQueryParams(pagination.PaginationSortSearchQueryParams):
    tournament_id: int | None = None
    home_team_id: int | None = None
    away_team_id: int | None = None
