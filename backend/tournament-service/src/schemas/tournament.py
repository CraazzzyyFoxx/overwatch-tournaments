import typing
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel

from src.core import enums, pagination
from src.schemas import UserRead
from src.schemas.admin.tournament_link import TournamentLinkRead
from src.schemas.base import BaseRead
from src.schemas.division_grid import DivisionGridVersionRead
from src.schemas.roster_shape import RosterShapeRead
from src.schemas.stage import StageSummaryRead

__all__ = (
    "TournamentRead",
    "TournamentPhaseScheduleRead",
    "OwalStanding",
    "OwalStandingDay",
    "OwalStandings",
    "TournamentPaginationSortSearchQueryParams",
    "TournamentPaginationSortSearchParams",
    "TournamentFacets",
    "TournamentFacetsQueryParams",
    "LeaguePlayerStack",
)


class TournamentPhaseScheduleRead(BaseModel):
    """One phase-schedule row: when phase ``status`` starts (and its action window ends)."""

    status: enums.TournamentStatus
    starts_at: datetime
    ends_at: datetime | None = None


class TournamentRead(BaseRead):
    workspace_id: int
    name: str
    # Public-URL identity (`/tournaments/{slug}`); see Tournament.slug.
    slug: str
    description: str | None
    # Organizer-published regulations, Markdown. Opt-in like the entities below
    # and for a different reason: it costs no query, but a multi-page document
    # in every nested TournamentRead would multiply itself across an encounter
    # list. `None` therefore means "not requested" OR "none published" -- ask
    # for the `rules` entity to tell the two apart.
    rules: str | None = None
    challonge_id: int | None
    challonge_slug: str | None
    is_league: bool
    is_finished: bool
    is_hidden: bool = False
    # Branding uploaded through the dedicated image subjects, never through
    # `TournamentUpdate` (issue #95): the cover is the wide page banner, the logo
    # the square mark. Both nullable — a tournament with neither renders the
    # gradient fallback.
    cover_image_url: str | None = None
    logo_url: str | None = None
    team_formation: str = "balancer"
    status: enums.TournamentStatus
    start_date: datetime
    end_date: datetime
    auto_transitions_enabled: bool = True
    allow_late_registration: bool = False
    discord_broadcasts_enabled: bool = True
    discord_dms_enabled: bool = True
    phase_schedule: list[TournamentPhaseScheduleRead] = []
    win_points: float = 1.0
    draw_points: float = 0.5
    loss_points: float = 0.0

    stages: list[StageSummaryRead] = []
    participants_count: int | None
    registrations_count: int | None = None
    teams_count: int | None = None
    division_grid_version_id: int | None
    division_grid_version: DivisionGridVersionRead | None = None
    roster_slots_json: dict[str, int] | None = None
    # Opt-in entities (D16): TournamentRead is nested in six other schemas that
    # are built from ORM rows without a session, so neither of these can be
    # required -- filling them unconditionally would cost a query per nested row.
    roster_shape: RosterShapeRead | None = None
    # `True` while a draft session is in flight, i.e. while the write-path guard
    # would reject a roster-shape change. Lets the admin form disable the editor
    # up front instead of surfacing the block as a 400 on save.
    roster_locked_by_draft: bool | None = None
    #: The other half of the same lock: a registering team's members hold slots
    #: assigned from the current shape. Opt-in with `roster_shape`, like the flag
    #: above, and for the same reason — it costs a query.
    roster_locked_by_teams: bool | None = None
    # Opt-in too, and for the same reason: the rows live in their own table, so
    # filling them unconditionally would cost a query per nested TournamentRead.
    links: list[TournamentLinkRead] = []


class OwalStandingDay(BaseModel):
    team: str
    role: enums.HeroClass
    division: int
    points: float
    wins: int
    draws: int
    losses: int
    win_rate: float


class OwalStanding(BaseModel):
    user: UserRead
    role: enums.HeroClass
    division: int
    days: dict[int, OwalStandingDay]
    count_days: int
    place: int
    best_3_days: float
    avg_points: float
    wins: int
    draws: int
    losses: int
    win_rate: float


class OwalStandings(BaseModel):
    days: list[TournamentRead]
    standings: list[OwalStanding]


class TournamentPaginationSortSearchQueryParams(
    pagination.PaginationSortSearchQueryParams[
        typing.Literal["id", "name", "start_date", "end_date", "similarity:name", "participants_count"]
    ]
):
    is_league: bool | None = None
    workspace_id: int | None = None
    status: enums.TournamentStatus | None = None


@dataclass
class TournamentPaginationSortSearchParams(pagination.PaginationSortSearchParams):
    is_league: bool | None = None
    workspace_id: int | None = None
    status: enums.TournamentStatus | None = None

    @classmethod
    def from_query_params(cls, query_params: pagination.PaginationQueryParams):
        """Same as the base, except ``fields`` is the SERVER's decision.

        ``PaginationSortSearchParams.apply_search`` (shared/core/pagination.py)
        feeds each entry of ``fields`` straight into
        ``model.depth_get_column(...)`` and ILIKEs it, and 400s when ``query`` is
        given without any. A client-supplied list is therefore both an arbitrary
        column read through ILIKE and a 500 on the first typo, while an empty one
        turns every public search into an error page. Tournament search means
        searching the name, so the name is what the server searches.
        """
        data = query_params.model_dump()
        data["fields"] = ["name"]
        return cls(**data)


class TournamentFacetsQueryParams(BaseModel):
    """Query model for ``rpc.tournament.tournaments_facets``.

    The same filter axes ``TournamentPaginationSortSearchQueryParams`` carries,
    minus pagination and sorting: counting a facet consumes no page.
    """

    workspace_id: int | None = None
    status: enums.TournamentStatus | None = None
    is_league: bool | None = None
    query: str = ""


class TournamentFacets(BaseModel):
    """Chip counters for the public tournaments page.

    ``total``/``live`` are unconditional platform facts (see
    ``TournamentFlowsService.get_facets``); ``by_status`` and ``league``/
    ``standard`` each ignore their own filter so a selected chip never zeroes its
    siblings.
    """

    total: int
    live: int
    by_status: dict[enums.TournamentStatus, int]
    league: int
    standard: int


class LeaguePlayerStack(BaseModel):
    user_1: UserRead
    user_2: UserRead
    games: int
    avg_position: float
