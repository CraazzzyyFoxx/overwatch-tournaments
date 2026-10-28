import datetime
import json
import typing
from dataclasses import dataclass, field

import sqlalchemy as sa
from pydantic import BaseModel, BeforeValidator, Field

from shared.core import enums, pagination
from shared.schemas.catalog import CatalogEntityRead, CatalogEntityRef
from shared.schemas.match import MatchRead, NativeFact
from shared.schemas.role import RoleRef
from src import schemas
from src.schemas.division_grid import DivisionGridVersionRead

# Structured GET filters are JSON-encoded query values; RPC callers may supply the object directly.
RoleQuery = typing.Annotated[
    RoleRef | None, BeforeValidator(lambda value: json.loads(value) if isinstance(value, str) else value)
]

__all__ = (
    "UserProfile",
    "UserDraftCard",
    "UserDraftCardCharacter",
    "UserDraftCardRole",
    "UserDraftCardTournament",
    "UserRole",
    "UserRoleSummary",
    "UserGameSummary",
    "UserTournamentWithStats",
    "UserTournament",
    "UserTournamentList",
    "UserTournamentSummary",
    "UserTournamentPlayer",
    "UserEncounterTournament",
    "UserEncounterStageSummary",
    "UserEncounterStageItemSummary",
    "UserEncounterTeamSummary",
    "UserEncounterTeamPlayerRef",
    "MatchReadWithUserStats",
    "UserMatchViewer",
    "EncounterReadWithUserStats",
    "UserMap",
    "UserMapCharacterStats",
    "UserMapHighlight",
    "UserMapsOverall",
    "UserMapsSummary",
    "UserMapsSearchParams",
    "UserMapsSearchQueryParams",
    "UserTournamentStat",
    "LobbyLeaderboardEntry",
    "LobbyLeaderboard",
    "TournamentPlayerStat",
    "TournamentPlayerStatsRow",
    "TournamentPlayerStats",
    "CharacterStat",
    "CharacterWithUserStats",
    "CharacterStatBest",
    "CharacterRecord",
    "UserBestTeammate",
    "UserOpponentStat",
    "UserStageRecord",
    "UserMatchesSummary",
    "UserOverviewRoleDivision",
    "UserOverviewDivisionCount",
    "UserOverviewCharacter",
    "UserOverviewAverages",
    "UserOverviewRow",
    "UserOverviewResponse",
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
    "UserCharacterCompareQueryParams",
    "UserCharacterCompareParams",
    "UserCharacterCompareMetric",
    "UserCharacterCompareResponse",
)


class UserRoleSummary(BaseModel):
    role: RoleRef | None = None
    tournaments: int
    maps_won: int
    maps: int
    #: From the newest tournament of the role that has a rank; ``None`` when no tournament of it is ranked.
    division: int | None


class UserRole(UserRoleSummary):
    """A profile role with the grid its division is a tier of (the crest is drawn on it)."""

    division_grid_version: DivisionGridVersionRead | None = None


class UserGameSummary(BaseModel):
    """One game of a cross-game profile: the player's roles on that game's grid, tournaments and wins in it."""

    discipline: str
    roles: list[UserRoleSummary]
    tournaments_count: int
    tournaments_won: int


class UserTournamentSummary(BaseModel):
    """Tournament card shown in user profile / achievement filter lists.

    Narrow projection of `models.Tournament` — only fields the frontend
    actually consumes in user-scoped pages.
    """

    id: int
    name: str
    #: The tournament's game: a cross-game profile tags every card with it.
    discipline: str
    is_league: bool
    is_finished: bool = False
    status: enums.TournamentStatus | None = None


class UserTournamentPlayer(BaseModel):
    """Player card inside `UserTournament.players` (rendered by TournamentTeamTable).

    Also populated inside `UserEncounterTeamSummary.players` when the
    encounter view needs to identify the viewer's row (via `user_id`).
    """

    id: int
    name: str
    role: RoleRef | None = None
    rank: int | None
    division: int | None
    user_id: int
    is_substitution: bool
    is_newcomer: bool
    is_newcomer_role: bool
    related_player_id: int | None = None
    relative_player: int | None = None
    # Average MVP placement (1 = best) across this player's matches in THIS
    # tournament. Mirrors the dossier "Avg MVP" metric: per match take
    # COALESCE(ImpactRank, Performance). `None` when the player has no such stat
    # rows.
    avg_mvp: float | None = None
    # This player's top characters by playtime in THIS tournament, named and drawn. Empty when none recorded.
    characters: list[CatalogEntityRef] = Field(default_factory=list)


class UserEncounterTournament(BaseModel):
    """Tournament link inside `EncounterReadWithUserStats.tournament`."""

    id: int
    name: str
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
    """Roster member inside an encounter seat — minimal id+user_id+role.

    Used only by the frontend to identify which seat the viewer played in
    (`players.find(p => p.user_id === selfUserId)`). Renders nothing on its
    own — for the full player card see `UserTournamentPlayer`. ``id`` is the
    roster snapshot row, not a tournament player.
    """

    id: int
    user_id: int
    role: RoleRef | None = None
    name: str


class UserEncounterTeamSummary(BaseModel):
    """One live seat inside `EncounterReadWithUserStats.teams`.

    ``id`` is the participation (``encounter.team``), ``team_id`` the source
    tournament team -- ``None`` once that team is deleted; ``name`` is the
    snapshot the encounter was played under, and ``players`` its roster snapshot.
    """

    id: int
    slot: int
    team_id: int | None = None
    name: str
    score: float = 0.0
    placement: int | None = None
    players: list[UserEncounterTeamPlayerRef] = Field(default_factory=list)


class UserMatchViewer(BaseModel):
    """The viewer's own seat and whole-match totals in one match."""

    encounter_team_id: int
    workspace_member_id: int
    #: Observed segment-0 facts with NULL entity, by stat code; an absent key is missing, never zero.
    facts: dict[str, float]
    #: Characters the viewer played, in catalog order.
    characters: list[CatalogEntityRead] = Field(default_factory=list)


class MatchReadWithUserStats(MatchRead):
    """Match within a user-scoped encounter: the native header, the viewer's totals and the members' ranked totals.

    A discipline's renderer derives its per-match badges from ``viewer.facts`` against ``member_totals``; no derived
    value rides on the wire. ``member_totals`` carries every observed member's segment-0, NULL-entity facts of the
    game's ``DisciplineSpec.member_total_stats`` only (empty for a game that ranks none). ``viewer`` is ``None`` for a
    match the viewer's seat was a participant of without being observed.
    """

    #: Always expanded with its catalog ``parent``; the match's own mode is ``mode``.
    map: CatalogEntityRead
    viewer: UserMatchViewer | None = None
    member_totals: list[NativeFact] = Field(default_factory=list)


class EncounterReadWithUserStats(BaseModel):
    """Encounter rendered on the user encounters page."""

    id: int
    name: str
    slot_count: int = 2
    round: int
    best_of: int = 3
    tournament_id: int
    #: The encounter's game: a cross-game list (spec §6.6) marks each row with it.
    discipline: str
    status: str
    closeness: float | None = None
    has_logs: bool = False
    result_status: str = "none"
    user_team_id: int | None = None  # the source team the viewer played for
    tournament: UserEncounterTournament | None = None
    stage: UserEncounterStageSummary | None = None
    stage_item: UserEncounterStageItemSummary | None = None
    #: The live seats in slot order; a retired participation is history.
    teams: list[UserEncounterTeamSummary] = Field(default_factory=list)
    matches: list[MatchReadWithUserStats] = Field(default_factory=list)


class UserTournament(BaseModel):
    id: int
    name: str
    workspace_id: int
    discipline: str
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
    role: RoleRef | None = None
    division: int | None = None
    #: The id of the grid version ``division`` and the roster divisions are tiers of; the version itself is in
    #: ``UserTournamentList.division_grid_versions``.
    division_grid_version_id: int | None = None


class UserTournamentList(BaseModel):
    """A player's tournament history, plus each grid version its rows refer to, once (ordered by id)."""

    results: list[UserTournament]
    division_grid_versions: list[DivisionGridVersionRead]


class UserTournamentStat(BaseModel):
    value: float
    rank: int
    total: int


class UserTournamentWithStats(BaseModel):
    id: int
    name: str
    #: The tournament's owner workspace and game: the role and division are drawn in that scope.
    workspace_id: int
    discipline: str
    division: int | None
    # `division` is resolved against the tournament's own grid (see
    # get_tournament_with_stats). Ship the grid version too so the frontend
    # renders the division icon on that same grid instead of falling back to
    # the workspace default.
    division_grid_version: DivisionGridVersionRead | None = None
    closeness: float
    role: RoleRef | None = None
    group_placement: float | None
    playoff_placement: float | None
    maps_won: int
    maps: int
    playtime: float

    #: By stat code (the tournament's game declares them) plus ``"winrate"``.
    stats: dict[str, UserTournamentStat]


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

    stat: str
    total_players: int
    entries: list[LobbyLeaderboardEntry]


class TournamentPlayerStat(BaseModel):
    """One player's tournament average of one stat and its rank in the lobby (lower is better)."""

    value: float
    rank: int


class TournamentPlayerStatsRow(BaseModel):
    player_id: int  # user id (models.User.id), as in ``LobbyLeaderboardEntry``
    #: By stat code; only the stats the player has data for.
    stats: dict[str, TournamentPlayerStat]


class TournamentPlayerStats(BaseModel):
    """Every player's ``LobbyLeaderboard`` value and rank for the tournament page's stats, in one read."""

    #: The largest ranked population across the stats (the ``total`` a rank is read against).
    total_players: int
    players: list[TournamentPlayerStatsRow]


class UserMapCharacterStats(BaseModel):
    character: CatalogEntityRead
    games: int
    win: int
    loss: int
    draw: int
    win_rate: float
    playtime_seconds: float
    playtime_share_on_map: float


class UserMap(BaseModel):
    map: CatalogEntityRead
    count: int
    win: int
    loss: int
    draw: int
    win_rate: float
    characters: list[schemas.CharacterPlaytime]
    character_stats: list[UserMapCharacterStats] | None = None


class UserMapHighlight(BaseModel):
    map: CatalogEntityRead
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
    mode_id: int | None = None
    tournament_id: int | None = None


@dataclass
class UserMapsSearchParams(pagination.PaginationSortSearchParams):
    min_count: int | None = None
    mode_id: int | None = None
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
    most_played_character: CatalogEntityRead | None
    characters_count: int

    roles: list[UserRole]
    tournaments: list[UserTournamentSummary]
    #: Without a game: one summary per game played, most tournaments first (ties: installed order). Empty with one.
    games: list[UserGameSummary] = Field(default_factory=list)
    character_statistics: list[schemas.CharacterPlaytime]


class UserDraftCardRole(BaseModel):
    """One role's map record on the draft-room player card."""

    role: RoleRef | None = None
    maps: int
    maps_won: int


class UserDraftCardCharacter(BaseModel):
    """One of the player's signature characters on the draft-room player card."""

    character: CatalogEntityRead
    maps: int
    maps_won: int


class UserDraftCardTournament(BaseModel):
    """One recent tournament row on the draft-room player card."""

    id: int
    name: str
    date: datetime.date | None = None
    role: RoleRef | None = None
    #: The player's raw rank on that tournament's roster (never a resolved
    #: division — the draft room resolves it against the tournament's own grid).
    rank: int | None = None
    placement: int | None = None
    teams_count: int


class UserDraftCard(BaseModel):
    """Career summary rendered on the draft room's player island.

    Leagues are excluded throughout (no placement, no bracket) so every number
    on the card counts the same set of events. A player with no history is a
    valid card of zeros and empty lists, never a 404.
    """

    tournaments: int
    tournaments_won: int
    maps: int
    maps_won: int
    maps_lost: int
    #: Maps the player finished first on the lobby's MVP placement
    #: (``COALESCE(ImpactRank, Performance) == 1``); ``None`` only if that
    #: placement can never be computed.
    mvp_maps: int | None = None
    best_placement: int | None = None
    avg_placement: float | None = None
    roles: list[UserDraftCardRole] = Field(default_factory=list)
    #: Every character played, most-played first: the table shows the top five, the
    #: role tiles look up the characters the player declared.
    characters: list[UserDraftCardCharacter] = Field(default_factory=list)
    #: Newest first, at most 5.
    recent_tournaments: list[UserDraftCardTournament] = Field(default_factory=list)


class CharacterStatBest(BaseModel):
    encounter_id: int
    tournament_name: str
    map_name: str
    map_image_path: str
    value: float
    player_name: str


class CharacterStat(BaseModel):
    #: A stat code the discipline declares.
    name: str
    overall: float
    best: CharacterStatBest
    avg_10: float
    best_all: CharacterStatBest | None
    avg_10_all: float


class CharacterRecord(BaseModel):
    """The player's career-best game on a character in the stat its class is judged by."""

    stat: str
    value: float
    encounter_id: int
    map_name: str
    tournament_name: str


class CharacterWithUserStats(BaseModel):
    character: CatalogEntityRead
    stats: list[CharacterStat]
    #: Scored games on the character in the read's scope (HeroTimePlayed > 60 s); a draw is a game, not a win.
    games: int = 0
    win: int = 0
    loss: int = 0
    draw: int = 0
    #: Every player's ``win / games`` on the character across the discipline (not scoped, like ``avg_10_all``).
    win_rate_all: float | None = None
    record: CharacterRecord | None = None


class UserBestTeammate(BaseModel):
    user: schemas.UserRead
    tournaments: int
    maps: int
    winrate: float
    stats: dict[str, float | None]


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


class UserOverviewRoleDivision(BaseModel):
    role: RoleRef | None = None
    # The workspace grid's tier number in a scoped read; in the all-workspaces
    # read the canonical number on the game's native ladder (None for a game
    # without one).
    division: int | None
    # Which stored grid ``division`` is a number on (scoped reads; it ships once
    # per response in ``division_grids``). None in the all-workspaces read: the
    # native ladder is in-code.
    division_grid_version_id: int | None = None


class UserOverviewCharacter(BaseModel):
    character: CatalogEntityRead
    playtime_seconds: float


class UserOverviewAverages(BaseModel):
    avg_closeness: float | None
    avg_placement: float | None
    avg_playoff_placement: float | None
    avg_group_placement: float | None


class UserOverviewRow(BaseModel):
    id: int
    name: str
    avatar_url: str | None = None
    #: The games the player played (installed order), in both modes; a row's mark narrows the scope to one.
    disciplines: list[str] = Field(default_factory=list)
    #: Game-bound: empty in the cross-game read (no ``discipline``).
    roles: list[UserOverviewRoleDivision]
    top_characters: list[UserOverviewCharacter]
    tournaments_count: int
    achievements_count: int
    maps_won: int
    maps_lost: int
    encounters_played: int
    best_placement: int | None
    #: ISO date of the latest tournament the user played in, scoped like the
    #: other aggregates. ``None`` when they never played one.
    last_active_at: str | None
    averages: UserOverviewAverages


class UserOverviewResponse(pagination.Paginated[UserOverviewRow]):
    """Overview page plus every stored division grid its rows' divisions refer to (none in the all-workspaces read)."""

    division_grids: list[DivisionGridVersionRead] = Field(default_factory=list)


#: A division chip value: a tier number of the read's grid (all-workspaces: of the game's native ladder), which a
#: native ladder numbers past 20. Repeated param: ``?divisions=3&divisions=5``.
DivisionNumber = typing.Annotated[int, Field(ge=1)]


class UserOverviewQueryParams(
    pagination.PaginationSortSearchQueryParams[
        typing.Literal[
            "id",
            "name",
            "tournaments_count",
            "achievements_count",
            "avg_placement",
            "winrate",
            "best_placement",
        ]
    ]
):
    role: RoleQuery = None
    divisions: list[DivisionNumber] = Field(default_factory=list)
    has_logs: bool = False
    #: ``sort=winrate`` only: users under this many encounters are ordered after
    #: everyone else, in both directions.
    min_encounters: int = Field(default=20, ge=0)


@dataclass
class UserOverviewParams(pagination.PaginationSortSearchParams):
    role: RoleRef | None = None
    has_role_filter: bool = False
    divisions: list[int] = field(default_factory=list)
    has_logs: bool = False
    min_encounters: int = 20

    @classmethod
    def from_query_params(cls, query_params: UserOverviewQueryParams) -> UserOverviewParams:
        params = super().from_query_params(query_params)
        params.role = query_params.role
        params.has_role_filter = "role" in query_params.model_fields_set
        return params

    def apply_search(self, query: sa.Select, model: type) -> sa.Select:
        fields = self.fields if self.fields else ["name"]
        return pagination.apply_search(model, query, self.query, fields)


class UserOverviewDivisionCount(BaseModel):
    division: int
    count: int


class UserOverviewStats(BaseModel):
    total_players: int
    with_logs_count: int
    with_logs_pct: float
    avg_tournaments_per_player: float
    median_tournaments_per_player: float
    active_last_30d: int
    active_last_30d_pct: float
    #: Distinct players per top-level role code of the game's rated dimension (only codes somebody played); empty without a game.
    role_counts: dict[str, int] = Field(default_factory=dict)
    flex_count: int
    #: Players with no rated-role assignment, unlike ``flex_count`` which also counts multi-role players.
    flex_declared_count: int
    #: Per-division chip counts, computed without the division filter itself (all-workspaces: native-ladder numbers).
    division_counts: list[UserOverviewDivisionCount] = Field(default_factory=list)


class UserOverviewStatsQueryParams(BaseModel):
    role: RoleQuery = None
    divisions: list[DivisionNumber] = Field(default_factory=list)
    has_logs: bool = False
    query: str | None = None


class UserCatalogEntry(BaseModel):
    id: int
    name: str
    avatar_url: str | None = None
    #: The games the player played (installed order), in both modes; a row's mark narrows the scope to one.
    disciplines: list[str] = Field(default_factory=list)
    #: Game-bound: empty in the cross-game read (no ``discipline``).
    roles: list[UserOverviewRoleDivision]
    top_characters: list[UserOverviewCharacter]
    tournaments_count: int
    achievements_count: int
    maps_won: int
    maps_lost: int
    encounters_played: int
    best_placement: int | None
    last_active_at: str | None
    avg_placement: float | None


class UserCatalogLetter(BaseModel):
    letter: str
    count: int
    users: list[UserCatalogEntry]


class UserCatalogResponse(BaseModel):
    letters: list[UserCatalogLetter]
    total: int
    available_letters: list[str]
    division_grids: list[DivisionGridVersionRead] = Field(default_factory=list)


class UserCatalogQueryParams(BaseModel):
    role: RoleQuery = None
    divisions: list[DivisionNumber] = Field(default_factory=list)
    has_logs: bool = False
    query: str | None = None
    letter: str | None = Field(default=None, min_length=1, max_length=2)
    per_letter: int = Field(default=12, ge=1, le=50)
    max_letters: int = Field(default=27, ge=1, le=40)


@dataclass
class UserCatalogParams:
    role: RoleRef | None = None
    has_role_filter: bool = False
    divisions: list[int] = field(default_factory=list)
    has_logs: bool = False
    query: str | None = None
    letter: str | None = None
    per_letter: int = 12
    max_letters: int = 27

    @classmethod
    def from_query_params(cls, query_params: UserCatalogQueryParams) -> UserCatalogParams:
        data = query_params.model_dump()
        data["role"] = query_params.role
        data["has_role_filter"] = "role" in query_params.model_fields_set
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
    role: RoleRef | None = None
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
    role: RoleQuery = None
    div_min: int | None = Field(default=None, ge=1)
    div_max: int | None = Field(default=None, ge=1)
    tournament_id: int | None = Field(default=None, ge=1)


@dataclass
class UserCompareParams:
    baseline: UserCompareBaselineMode = "global"
    target_user_id: int | None = None
    role: RoleRef | None = None
    div_min: int | None = None
    div_max: int | None = None
    tournament_id: int | None = None

    @classmethod
    def from_query_params(cls, query_params: UserCompareQueryParams):
        return cls(**(query_params.model_dump() | {"role": query_params.role}))


class UserCharacterCompareMetric(BaseModel):
    stat: str
    left_value: float
    right_value: float
    delta: float
    delta_percent: float | None
    better_worse: typing.Literal["better", "worse", "equal"] | None
    higher_is_better: bool


class UserCharacterCompareResponse(BaseModel):
    subject: UserCompareUser
    target: UserCompareUser | None
    baseline: UserCompareBaselineInfo
    subject_character: CatalogEntityRead | None
    target_character: CatalogEntityRead | None
    map: CatalogEntityRead | None
    left_playtime_seconds: float
    right_playtime_seconds: float
    metrics: list[UserCharacterCompareMetric]


class UserCharacterCompareQueryParams(BaseModel):
    baseline: UserCompareBaselineMode = "global"
    target_user_id: int | None = Field(default=None, ge=1)
    left_entity_id: int | None = Field(default=None, ge=1)
    right_entity_id: int | None = Field(default=None, ge=1)
    map_id: int | None = Field(default=None, ge=1)
    role: RoleQuery = None
    div_min: int | None = Field(default=None, ge=1)
    div_max: int | None = Field(default=None, ge=1)
    tournament_id: int | None = Field(default=None, ge=1)
    stats: list[str] | None = None


@dataclass
class UserCharacterCompareParams:
    baseline: UserCompareBaselineMode = "global"
    target_user_id: int | None = None
    left_entity_id: int | None = None
    right_entity_id: int | None = None
    map_id: int | None = None
    role: RoleRef | None = None
    div_min: int | None = None
    div_max: int | None = None
    tournament_id: int | None = None
    stats: list[str] = field(default_factory=list)

    @classmethod
    def from_query_params(cls, query_params: UserCharacterCompareQueryParams):
        payload = query_params.model_dump()
        payload["role"] = query_params.role
        payload["stats"] = payload.get("stats") or []
        return cls(**payload)
