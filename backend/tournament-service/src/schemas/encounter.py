from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from shared.core import pagination
from shared.schemas.catalog import CatalogEntityRead
from shared.schemas.discipline_filter import InstalledDisciplineFilter
from shared.schemas.match import MatchRead as NativeMatchRead
from shared.schemas.match import NativeMatchStatistics
from src.schemas import (
    BaseRead,
    StageItemSummaryRead,
    StageSummaryRead,
    TeamRead,
    TournamentRead,
)

__all__ = (
    "EncounterCountsRead",
    "EncounterFiltersRead",
    "EncounterGameRead",
    "EncounterGameTeamRead",
    "EncounterHistogramBucketRead",
    "EncounterInsightsRead",
    "EncounterMapMetricRead",
    "EncounterRead",
    "EncounterOverviewRead",
    "EncounterSavedViewCreate",
    "EncounterSavedViewRead",
    "EncounterScoreLineRead",
    "EncounterSlotSourceRead",
    "EncounterStageKindRead",
    "EncounterSummaryRead",
    "EncounterTeamRead",
    "MatchRead",
    "MatchReadWithStats",
    "EncounterSearchParams",
    "EncounterSearchQueryParams",
    "MatchSearchParams",
    "MatchSearchQueryParams",
)


class EncounterTeamRead(BaseModel):
    """One live or historical participation of an encounter (``encounter.team``).

    ``id`` is the participation id every write addresses -- a claim, a report
    and an admin result all name it, never a slot and never a side. ``team_id``
    is the source ``tournament.team`` and goes NULL when that team is deleted;
    ``name`` is the snapshot that outlives it.
    """

    id: int
    slot: int
    team_id: int | None = None
    name: str
    seed: int | None = None
    #: The materialized standing inside the encounter (``wins`` under the
    #: series preset, points under a lobby's formula).
    score: float = 0.0
    placement: int | None = None
    active: bool = True
    #: The source team, expanded only when the ``teams`` entity is requested --
    #: the seat itself already carries the name a reader needs.
    team: TeamRead | None = None


class EncounterGameTeamRead(BaseModel):
    """One participation's accepted numbers and side in one game."""

    encounter_team_id: int
    #: The game's raw score (map rounds); ``None`` for a game that has none.
    score: int | None = None
    placement: int | None = None
    #: The stage's own columns for this participation; an absent key reads 0.
    column_values: dict[str, float] = {}
    #: Discipline side code; ``None`` when the discipline has no sides.
    starting_side: str | None = None
    replay_code: str | None = None


class EncounterSummaryRead(BaseRead):
    name: str
    slot_count: int = 2
    #: How the encounter is scored: ``points`` is a lobby's card (a two-seat one
    #: included), ``wins`` a series. A reader tells the two apart by this, never
    #: by ``slot_count``.
    scoring_preset: Literal["wins", "points"] = "wins"
    round: int
    tournament_id: int
    stage_id: int | None = None
    stage_item_id: int | None = None
    status: str
    result_status: str = "none"
    teams: list[EncounterTeamRead] = []


class EncounterSlotSourceRead(BaseModel):
    """Where an unresolved slot's team comes from: ``source_position`` of
    ``encounter_id`` fills ``slot`` of this encounter.

    The bracket's real advancement edges (``EncounterLink``). A reader labels an
    empty slot from them ("1st of M3") instead of inferring the bracket's shape
    from round numbers, which cannot tell a lower bracket seeded from the group
    stage apart from one fed by the upper bracket's first losers. Both ends are
    places and seats, never winner/loser or home/away.
    """

    encounter_id: int
    #: Place in the source encounter's final standing; 1 is first.
    source_position: int
    #: Seat of this encounter the edge fills, ``1..slot_count``.
    slot: int


class EncounterGameRead(BaseRead):
    """One position of the series and what the tournament DECIDED for it.

    Distinct from ``MatchRead``, which is what a parsed log OBSERVED: a position
    exists (and names its map) long before any log arrives, and a series may
    play the same map twice — only ``position`` tells those two plays apart.
    """

    position: int
    map_id: int | None = None
    map: CatalogEntityRead | None = None
    #: The catalog mode the position is played in; filled from the accepted log when the tournament named none.
    mode_id: int | None = None
    mode: CatalogEntityRead | None = None
    state: str
    result_source: str | None = None
    result_version: int = 0
    confirmed_at: datetime | None = None
    #: One line per participation seated in this game.
    teams: list[EncounterGameTeamRead] = []


class EncounterRead(BaseRead):
    #: Owner context (the tournament's or mix's workspace and discipline): lets a
    #: reader scope metadata and catalog reads without a second owner fetch.
    workspace_id: int
    discipline: str
    name: str
    slot_count: int = 2
    scoring_preset: Literal["wins", "points"] = "wins"
    round: int
    best_of: int = 3
    #: ``None`` for a mix's round: its owner is the mix, not a tournament.
    tournament_id: int | None = None
    stage_id: int | None = None
    stage_item_id: int | None = None
    challonge_id: int | None
    closeness: float | None
    has_logs: bool
    status: str
    result_status: str = "none"
    #: Which writer decided the standing (``games``/``series_claim``/``admin``/
    #: ``import``); ``None`` while no official result exists, where readers show
    #: the running total of the confirmed games.
    result_source: str | None = None
    #: Bumped by every result write; a claim or report names the version it was
    #: made against so a correction in between makes it stale, not a winner.
    result_version: int = 0
    sources: list[EncounterSlotSourceRead] = []
    scheduled_at: datetime | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    current_map_index: int | None = None
    confirmed_at: datetime | None = None
    #: When a decided series was played (``service.played_at_expr``); ``None`` when nothing trustworthy says, where
    #: readers show the tournament's dates. Imported history's confirmation time is not a play time.
    played_at: datetime | None = None
    #: The server's one reading of "in play" (``service._live_condition``); readers never re-derive it from the clocks.
    is_live: bool = False
    #: The last positive round of an elimination stage (``service._is_final_condition``) -- the same predicate as the
    #: browse's ``is_final`` filter. Set on the browse, the detail and the overview/insights strips; a match's nested
    #: encounter leaves it ``False``, like ``played_at``.
    is_final: bool = False

    stage: StageSummaryRead | None
    stage_item: StageItemSummaryRead | None
    tournament: TournamentRead | None
    #: The live seats only; retired participations are history.
    teams: list[EncounterTeamRead] = []
    matches: list[MatchRead]
    games: list[EncounterGameRead] = []


class MatchRead(NativeMatchRead):
    """What a parsed log OBSERVED, with its participants; ``encounter`` is expanded by ``entities=encounter``."""

    encounter: EncounterRead | None = None


class MatchReadWithStats(MatchRead):
    """The match page's document: the header plus every member, segment and fact at every grain."""

    statistics: NativeMatchStatistics


class EncounterFiltersRead(BaseModel):
    """A saved view's whole filter state; applying one replaces the page's filters."""

    query: str = ""
    #: Game-bound: a reader browsing every game drops it, like the page's own tournament filter.
    tournament_id: int | None = None
    stage_id: int | None = None
    stage_item_id: int | None = None
    best_of: int | None = None
    status: str | None = None
    has_logs: bool | None = None
    is_final: bool | None = None
    is_upset: bool | None = None
    closeness_min: float | None = None
    closeness_max: float | None = None
    scope: Literal["all", "my_team"] = "all"
    #: The page's own order, not a column: ``date`` (played, newest first) or ``closeness``.
    sort: Literal["date", "closeness"] = "date"

    @model_validator(mode="before")
    @classmethod
    def _retired_upcoming_sort(cls, data: Any) -> Any:
        # The retired «Ближайшие» order is the «Предстоят» segment now (it always orders by schedule); a view saved
        # under it must still read, the way an old ``?sort=upcoming`` URL does.
        if isinstance(data, dict) and data.get("sort") == "upcoming":
            return {**data, "sort": "date", "status": data.get("status") or "upcoming"}
        return data


class EncounterSavedViewCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    filters: EncounterFiltersRead


class EncounterSavedViewRead(BaseRead):
    name: str
    filters: EncounterFiltersRead
    sort_order: int
    workspace_id: int


class EncounterCountsRead(BaseModel):
    """The toolbar's numbers under the current filters.

    The segments (``all``/``live``/``upcoming``/``completed``) ignore the status filter and apply every active
    toggle; each toggle (``finals``/``upsets``/``with_logs``/``my_team``) applies every other filter, the status
    included, with itself forced on. ``my_team`` is 0 for an anonymous viewer.
    """

    all: int
    live: int
    upcoming: int
    completed: int
    finals: int
    upsets: int
    with_logs: int
    my_team: int


class EncounterOverviewRead(BaseModel):
    """``GET /encounters/overview``: the cheap summary; asked with no filters it is the platform's own numbers."""

    counts: EncounterCountsRead
    #: Completed and with logs, the status filter ignored.
    completed_with_logs: int
    #: Completed with a play date in the last 7 days, the status filter ignored.
    recent_completed: int
    #: Up to 4 series in play, the status filter ignored.
    live: list[EncounterRead]


class EncounterHistogramBucketRead(BaseModel):
    #: ``[start, end)``; the last bucket closes at 1.
    start: float
    end: float
    count: int


class EncounterScoreLineRead(BaseModel):
    """One final score of a completed duel, the winner's side first; ``winner == loser`` is a draw."""

    winner: int
    loser: int
    count: int


class EncounterStageKindRead(BaseModel):
    #: ``groups``: round robin (and an FFA league); ``playoffs``: single/double elimination; ``unassigned``: no stage.
    kind: Literal["groups", "playoffs", "swiss", "unassigned"]
    count: int


class EncounterMapMetricRead(BaseModel):
    name: str
    count: int


class EncounterInsightsRead(BaseModel):
    """``GET /encounters/insights``: the analytics of the completed encounters under the browse's filters (the status
    filter is forced to ``completed``). Rates are fractions, 0..1."""

    completed: int
    avg_closeness: float | None
    #: Ten buckets of 0.1 closeness.
    closeness_histogram: list[EncounterHistogramBucketRead]
    #: Completed duels by final score, most common first.
    score_lines: list[EncounterScoreLineRead]
    #: Most common first; a kind with no encounter is left out.
    stage_kinds: list[EncounterStageKindRead]
    #: The 6 most played maps of the parsed logs.
    hot_maps: list[EncounterMapMetricRead]
    #: The 4 closest completed encounters.
    closest: list[EncounterRead]
    #: Mean summed map duration of a series with parsed logs.
    avg_series_seconds: float | None
    #: Completed duels of more than one map (``best_of > 1``): the base of ``sweeps`` and ``went_distance``.
    multi_map: int
    #: Multi-map duels won without dropping a map.
    sweeps: int
    #: Multi-map duels whose scores add up to their ``best_of``.
    went_distance: int


@dataclass
class EncounterSearchParams(pagination.PaginationSortSearchParams):
    tournament_id: int | None = None
    stage_id: int | None = None
    stage_item_id: int | None = None
    best_of: int | None = None
    status: str | None = None
    has_logs: bool | None = None
    is_final: bool | None = None
    is_upset: bool | None = None
    closeness_min: float | None = None
    closeness_max: float | None = None
    scope: Literal["all", "my_team"] = "all"
    #: ``None`` reads as 2: every existing list, search and overview is a list
    #: of duels, and a lobby's table is drawn by the FFA read instead.
    slot_count: int | None = None
    #: One game's encounters (every aggregate and the live/upcoming strips included); ``None`` is every game.
    discipline: str | None = None


#: The browse's sort keys. ``played_at`` orders by when a series was played (else when it is due, else its
#: tournament's dates); every key sorts NULLs last and ties by id.
EncounterSortKey = Literal[
    "id", "name", "best_of", "status", "scheduled_at", "closeness", "has_logs", "discipline", "played_at"
]


class EncounterSearchQueryParams(pagination.PaginationSortSearchQueryParams):
    tournament_id: int | None = None
    stage_id: int | None = None
    stage_item_id: int | None = None
    best_of: int | None = None
    sort: EncounterSortKey = "id"
    #: A stored status (``completed``/``pending``/``open``) or a derived one: ``live``, ``upcoming`` (open or pending,
    #: not live).
    status: str | None = None
    has_logs: bool | None = None
    #: In (``true``) or out of (``false``) the last positive round of an elimination stage.
    is_final: bool | None = None
    #: A completed duel won by the seat standing lower in its stage item, or every other encounter (``false``).
    is_upset: bool | None = None
    #: ``[closeness_min, closeness_max)``; a ``closeness_max`` of 1 closes the range.
    closeness_min: float | None = Field(default=None, ge=0.0, le=1.0)
    closeness_max: float | None = Field(default=None, ge=0.0, le=1.0)
    scope: Literal["all", "my_team"] = "all"
    #: ``None`` reads as 2: every existing list, search and overview is a list
    #: of duels, and a lobby's table is drawn by the FFA read instead.
    slot_count: int | None = None
    discipline: InstalledDisciplineFilter = None


@dataclass
class MatchSearchParams(pagination.PaginationSortSearchParams):
    tournament_id: int | None = None
    #: Matches this source team took part in, whichever seat it held.
    tournament_team_id: int | None = None


class MatchSearchQueryParams(pagination.PaginationSortSearchQueryParams):
    tournament_id: int | None = None
    tournament_team_id: int | None = None


# EncounterRead.matches forward-references MatchRead, defined below it; see the
# note at the tail of schemas/team.py for why the lazy rebuild is not enough.
EncounterRead.model_rebuild()
MatchRead.model_rebuild()
MatchReadWithStats.model_rebuild()
