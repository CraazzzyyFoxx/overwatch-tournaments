import typing
from dataclasses import dataclass, field
from datetime import datetime

from pydantic import BaseModel, BeforeValidator, computed_field

from shared.core import enums, pagination
from shared.disciplines import identity_provider as discipline_identity_provider
from shared.schemas.discipline_filter import InstalledDisciplineFilter
from shared.schemas.roster_slots import RosterShapeRead
from shared.services.workspace_scope import ALL_WORKSPACES
from src.schemas.admin.tournament_link import TournamentLinkRead
from src.schemas.base import BaseRead
from src.schemas.division_grid import DivisionGridVersionRead
from src.schemas.flow import TournamentFlowNodeRead
from src.schemas.stage import StageSummaryRead

__all__ = (
    "TournamentRead",
    "TournamentPaginationSortSearchQueryParams",
    "TournamentPaginationSortSearchParams",
    "TournamentFacets",
    "TournamentFacetsQueryParams",
)


def _every_workspace_is_unfiltered(value: typing.Any) -> typing.Any:
    return None if value == ALL_WORKSPACES.value else value


#: ``workspace_id`` filter of the public list reads: an id narrows, while absent
#: and ``all`` (the cross-workspace opt-in the other reads accept) mean every
#: workspace.
WorkspaceFilter = typing.Annotated[int | None, BeforeValidator(_every_workspace_is_unfiltered)]


class TournamentRead(BaseRead):
    workspace_id: int
    discipline: str
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
    is_finished: bool
    is_hidden: bool = False
    # Branding uploaded through the dedicated image subjects, never through
    # `TournamentUpdate`: the cover is the wide page banner, the logo
    # the square mark. Both nullable — a tournament with neither renders the
    # gradient fallback.
    cover_image_url: str | None = None
    logo_url: str | None = None
    team_formation: str = "balancer"
    status: enums.TournamentStatus
    start_date: datetime
    end_date: datetime
    auto_transitions_enabled: bool = True
    discord_broadcasts_enabled: bool = True
    discord_dms_enabled: bool = True
    logs_official: bool = False
    # Seconds participants' POV streams run behind real time; the stream VOD chapter offsets add it.
    pov_stream_delay_s: int = 0

    stages: list[StageSummaryRead] = []
    participants_count: int | None
    registrations_count: int | None = None
    teams_count: int | None = None
    division_grid_version_id: int | None
    division_grid_version: DivisionGridVersionRead | None = None
    # The tournament's draft format rule; None = the snake default. Always
    # exposed: it costs no query.
    draft_format_json: dict[str, typing.Any] | None = None
    # Opt-in entities: TournamentRead is nested in six other schemas that
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
    # Opt-in (`flow_nodes`): the registration, formation, stage and leaderboard nodes with their status and schedule.
    flow_nodes: list[TournamentFlowNodeRead] = []

    @computed_field
    @property
    def identity_provider(self) -> str:
        """The discipline's player identity provider."""
        return discipline_identity_provider(self.discipline)


class TournamentPaginationSortSearchQueryParams(
    pagination.PaginationSortSearchQueryParams[
        typing.Literal["id", "name", "start_date", "end_date", "similarity:name", "participants_count"]
    ]
):
    workspace_id: WorkspaceFilter = None
    #: Any of these statuses (``?status=live&status=playoffs``); absent or empty is every status.
    status: list[enums.TournamentStatus] = []
    #: ``true``: only tournaments with a registration node in ``open`` or ``check_in``; ``false`` is no filter.
    registration_open: bool = False
    discipline: InstalledDisciplineFilter = None


@dataclass
class TournamentPaginationSortSearchParams(pagination.PaginationSortSearchParams):
    workspace_id: int | None = None
    status: list[enums.TournamentStatus] = field(default_factory=list)
    registration_open: bool = False
    discipline: str | None = None

    # ``per_page=-1`` ("every row") stops here, not at the shared 10,000: each row is ~100 us of serialization on
    # the only event loop, and the readers that ask for every row (the header's active list, the admin pickers) want
    # far fewer.
    MAX_UNLIMITED_RESULTS: typing.ClassVar[int] = 500

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

    workspace_id: WorkspaceFilter = None
    status: enums.TournamentStatus | None = None
    discipline: InstalledDisciplineFilter = None
    query: str = ""


class TournamentFacets(BaseModel):
    """Chip counters for the public tournaments page.

    ``total``/``live`` are unconditional platform facts (see
    ``TournamentFlowsService.get_facets``); ``by_status`` ignores its own filter so a selected chip never zeroes its
    siblings.
    """

    total: int
    live: int
    by_status: dict[enums.TournamentStatus, int]
    #: Tournaments with a registration node in ``open`` or ``check_in`` (the "Registration" chip); like ``by_status``
    #: it ignores the status filter.
    registration_open: int
