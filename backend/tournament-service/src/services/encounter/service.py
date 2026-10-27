import typing
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.orm.strategy_options import _AbstractLoad

from shared import models
from shared.core import enums, errors, pagination, utils
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.repository import (
    EncounterRepository,
    EncounterSavedViewRepository,
)
from shared.repository.stats_queries import match_context
from shared.repository.stats_reads import MatchReadContext, get_match_reads
from shared.services.tournament.visibility import visible_tournament_ids_subquery
from src import schemas
from src.core.query_page import execute_page_with_total
from src.core.workspace import workspace_filter
from src.services.tournament import service as tournament_service


def encounter_entities(in_entities: list[str], child: typing.Any | None = None) -> list[_AbstractLoad]:
    """SQLAlchemy loader options for the encounter relations named in ``in_entities``, nested under ``child``."""
    entities = []
    if "tournament" in in_entities:
        tournament_entity = utils.join_entity(child, models.Encounter.tournament)
        entities.append(tournament_entity)
        entities.extend(
            tournament_service.tournament_entities(utils.prepare_entities(in_entities, "tournament"), tournament_entity)
        )
    # The participations load with EVERY encounter read, not behind an entity
    # token: the seats carry both teams, the score and the places, so
    # ``to_pydantic`` touches them for an entity-less read too, and an unloaded
    # collection there is implicit IO (``MissingGreenlet``). The bracket
    # position lives on ``tournament.bracket_encounter``, fetched by id.
    entities.append(utils.selectin_entity(child, models.Encounter.teams))
    if "matches" in in_entities:
        entities.append(utils.selectin_entity(child, models.Encounter.matches))
        # ``to_pydantic`` fills ``games`` off the SAME switch: a position and its
        # map and mode exist before any parsed log does, and the read carries them.
        # selectin, never joined -- two to-many collections joined onto one
        # encounter multiply each other's rows.
        games = utils.selectin_entity(child, models.Encounter.games)
        entities.append(games.selectinload(models.EncounterGame.map))
        entities.append(games.selectinload(models.EncounterGame.mode))

    return entities


def _match_encounter_options(in_entities: list[str]) -> list[_AbstractLoad]:
    """What the nested ``encounter`` expansion of a match needs loaded; the matches themselves never nest."""
    return encounter_entities(
        [
            entity
            for entity in utils.prepare_entities(in_entities, "encounter")
            if entity != "matches" and not entity.startswith("matches.")
        ]
    )


def join_encounter_entities(query: sa.Select, in_entities: list[str]) -> sa.Select:
    """Join the tables ``in_entities`` filters on (``tournament``) onto an encounter query."""
    if "tournament" in in_entities:
        query = query.join(models.Tournament, models.Encounter.tournament_id == models.Tournament.id)
    return query


#: What ``status`` filters on: a stored status, or one of the two the browse derives (``live``, ``upcoming``).
_STATUS_FILTERS = (*(item.value for item in enums.EncounterStatus), "live", "upcoming")


def _status_predicate(value: str, now: datetime) -> sa.ColumnElement[bool]:
    """The ``status`` filter: a stored status, or ``live``/``upcoming`` read the way the overview counts them."""
    if value == "live":
        return _live_condition(now)
    if value == "upcoming":
        return _upcoming_condition(now)
    try:
        return models.Encounter.status == enums.EncounterStatus(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status. Must be one of: {', '.join(_STATUS_FILTERS)}",
        ) from exc


def _is_final_condition() -> sa.ColumnElement[bool]:
    """In the last positive round of a single or double elimination stage: its final (a double elimination's grand
    final -- the lower bracket's rounds are negative).

    Correlated on ``encounter`` and NULL-free, so the filter, its negation, an aggregate ``FILTER`` and the row's
    ``is_final`` all read the same predicate. Every inner table is aliased: a caller's own join of the same table
    must never be correlated into it.
    """
    position = aliased(models.BracketEncounter)
    sibling = aliased(models.BracketEncounter)
    stage = aliased(models.Stage)
    last_round = sa.select(sa.func.max(sibling.round)).where(sibling.stage_id == position.stage_id).scalar_subquery()
    return sa.exists(
        sa.select(1)
        .select_from(position)
        .join(stage, stage.id == position.stage_id)
        .where(
            position.encounter_id == models.Encounter.id,
            stage.stage_type.in_([enums.StageType.SINGLE_ELIMINATION, enums.StageType.DOUBLE_ELIMINATION]),
            position.round > 0,
            position.round == last_round,
        )
    )


def _is_upset_condition() -> sa.ColumnElement[bool]:
    """A completed duel won by the seat whose standing in the same tournament, stage and stage item is numerically
    larger (lower) than the loser's. A seat with no standing there is never an upset either way."""
    position = aliased(models.BracketEncounter)
    seat_one = aliased(models.EncounterTeam)
    seat_two = aliased(models.EncounterTeam)
    first = aliased(models.Standing)
    second = aliased(models.Standing)

    def standing(row: typing.Any, seat: typing.Any) -> sa.ColumnElement[bool]:
        return sa.and_(
            row.tournament_id == position.tournament_id,
            row.team_id == seat.team_id,
            row.stage_id == position.stage_id,
            row.stage_item_id == position.stage_item_id,
        )

    return sa.and_(
        models.Encounter.status == enums.EncounterStatus.COMPLETED,
        models.Encounter.slot_count == 2,
        sa.exists(
            sa.select(1)
            .select_from(position)
            .join(seat_one, sa.and_(seat_one.encounter_id == position.encounter_id, seat_one.slot == 1))
            .join(seat_two, sa.and_(seat_two.encounter_id == position.encounter_id, seat_two.slot == 2))
            .join(first, standing(first, seat_one))
            .join(second, standing(second, seat_two))
            .where(
                position.encounter_id == models.Encounter.id,
                seat_one.active.is_(True),
                seat_two.active.is_(True),
                sa.or_(
                    sa.and_(seat_one.score > seat_two.score, first.position > second.position),
                    sa.and_(seat_two.score > seat_one.score, second.position > first.position),
                ),
            )
        ),
    )


def _my_team_condition(viewer_auth_user_id: int | None) -> sa.ColumnElement[bool]:
    """A live seat holds a team the viewer's linked player is rostered on in that tournament; nothing for an
    anonymous viewer."""
    if viewer_auth_user_id is None:
        return sa.false()
    seat = aliased(models.EncounterTeam)
    player = aliased(models.Player)
    member = aliased(models.WorkspaceMember)
    user = aliased(models.User)
    return sa.exists(
        sa.select(1)
        .select_from(seat)
        .join(player, player.team_id == seat.team_id)
        .join(member, member.id == player.workspace_member_id)
        .join(user, user.id == member.player_id)
        .where(
            seat.encounter_id == models.Encounter.id,
            seat.active.is_(True),
            player.tournament_id == models.Encounter.tournament_id,
            user.auth_user_id == viewer_auth_user_id,
        )
    )


def _search_condition(params: schemas.EncounterSearchParams) -> sa.ColumnElement[bool]:
    """``query`` over ``fields``. ``name`` also reads the reversed "B vs A", either live seat's name and the player
    names of the seats' rosters: a reader searches a team or a player, not the stored title."""
    like = f"%{params.query}%"
    criteria: list[sa.ColumnElement[bool]] = []
    for field in params.fields:
        column = models.Encounter.depth_get_column(field.split("."))
        criteria.append(column.ilike(like))
        if field != "name":
            continue
        reversed_name = sa.func.concat(
            sa.func.split_part(column, " vs ", 2), " vs ", sa.func.split_part(column, " vs ", 1)
        )
        seat = aliased(models.EncounterTeam)
        player = aliased(models.Player)
        member = aliased(models.WorkspaceMember)
        user = aliased(models.User)
        live_seat = sa.and_(seat.encounter_id == models.Encounter.id, seat.active.is_(True))
        criteria += [
            reversed_name.ilike(like),
            sa.exists(sa.select(1).select_from(seat).where(live_seat, seat.name.ilike(like))),
            sa.exists(
                sa.select(1)
                .select_from(seat)
                .join(player, player.team_id == seat.team_id)
                .join(member, member.id == player.workspace_member_id)
                .join(user, user.id == member.player_id)
                .where(live_seat, user.name.ilike(like))
            ),
        ]
    return sa.or_(*criteria)


def _toggle_clauses(
    params: schemas.EncounterSearchParams, viewer_auth_user_id: int | None
) -> dict[str, sa.ColumnElement[bool]]:
    """The quick toggles that are set, by name. Each narrows the browse, and the overview counts each one with the
    others as they are, so they stay separate clauses rather than one ``WHERE``."""
    clauses: dict[str, sa.ColumnElement[bool]] = {}
    if params.has_logs is not None:
        clauses["has_logs"] = models.Encounter.has_logs.is_(params.has_logs)
    if params.is_final is not None:
        clauses["is_final"] = _is_final_condition() if params.is_final else sa.not_(_is_final_condition())
    if params.is_upset is not None:
        clauses["is_upset"] = _is_upset_condition() if params.is_upset else sa.not_(_is_upset_condition())
    if params.scope == "my_team":
        clauses["scope"] = _my_team_condition(viewer_auth_user_id)
    return clauses


def _without_status_and_toggles(params: schemas.EncounterSearchParams) -> schemas.EncounterSearchParams:
    """The filters the overview's counts all share; status and the toggles become per-count ``FILTER`` clauses."""
    return replace(params, status=None, has_logs=None, is_final=None, is_upset=None, scope="all")


def _apply_encounter_filters(
    query: sa.Select,
    params: schemas.EncounterSearchParams,
    *,
    workspace_id: int | None = None,
    viewer_auth_user_id: int | None = None,
    joined_tournament: bool = False,
) -> sa.Select:
    # Every list, search and overview here renders a DUEL (two seats, a score).
    # A lobby has its own table read, so it is out unless the caller asks for a
    # wider card by slot count.
    query = query.where(models.Encounter.slot_count == (params.slot_count or 2))

    if params.query:
        query = query.where(_search_condition(params))

    if params.tournament_id:
        query = query.where(models.Encounter.tournament_id == params.tournament_id)
    else:
        # Cross-tournament browse: never surface hidden tournaments.
        # A specific tournament_id is authorized upstream by ensure_tournament_viewable.
        query = query.where(models.Encounter.tournament_id.in_(visible_tournament_ids_subquery(None)))
    if params.discipline is not None:
        query = query.where(models.Encounter.discipline == params.discipline)
    if params.stage_id is not None:
        query = query.where(
            sa.exists()
            .where(models.BracketEncounter.encounter_id == models.Encounter.id)
            .where(models.BracketEncounter.stage_id == params.stage_id)
        )
    if params.stage_item_id is not None:
        query = query.where(
            sa.exists()
            .where(models.BracketEncounter.encounter_id == models.Encounter.id)
            .where(models.BracketEncounter.stage_item_id == params.stage_item_id)
        )
    if params.best_of is not None:
        query = query.where(models.Encounter.best_of == params.best_of)
    if params.status:
        query = query.where(_status_predicate(params.status, datetime.now(UTC)))
    if params.closeness_min is not None:
        query = query.where(models.Encounter.closeness.isnot(None), models.Encounter.closeness >= params.closeness_min)
    if params.closeness_max is not None:
        # ``[min, max)``, closed only at 1: adjacent ranges (the insights' tenths, the closeness select) never both
        # hold a boundary value -- and closeness is the captains' 1..10 rating over 10, so most values ARE one.
        below_max = (
            models.Encounter.closeness < params.closeness_max
            if params.closeness_max < 1
            else models.Encounter.closeness <= params.closeness_max
        )
        query = query.where(models.Encounter.closeness.isnot(None), below_max)
    # EXISTS, never a join: no row fans out, and each composes inside the overview's aggregate FILTERs.
    query = query.where(*_toggle_clauses(params, viewer_auth_user_id).values())

    if workspace_id is not None:
        if not joined_tournament:
            query = query.join(models.Tournament, models.Encounter.tournament_id == models.Tournament.id)
        query = query.where(*workspace_filter(workspace_id))

    return query


def _live_condition(now: datetime) -> sa.ColumnElement[bool]:
    """A series in play: started and not ended, a game position reported, or a pending match past its slot.

    Every branch is NULL-free, so ``NOT`` of it (``_upcoming_condition``) never drops a row. A decided series is
    never live, whatever its hand-set clock says. :func:`encounter_is_live` is this for one loaded row.
    """
    return sa.and_(
        models.Encounter.status != enums.EncounterStatus.COMPLETED,
        sa.or_(
            sa.and_(
                models.Encounter.started_at.isnot(None),
                models.Encounter.ended_at.is_(None),
            ),
            sa.and_(
                models.Encounter.status == enums.EncounterStatus.PENDING,
                models.Encounter.current_game_position.isnot(None),
            ),
            sa.and_(
                models.Encounter.status == enums.EncounterStatus.PENDING,
                models.Encounter.scheduled_at.isnot(None),
                models.Encounter.scheduled_at <= now,
                models.Encounter.ended_at.is_(None),
            ),
        ),
    )


def encounter_is_live(encounter: models.Encounter, now: datetime) -> bool:
    """:func:`_live_condition` for one loaded row -- the two must agree."""
    if encounter.status == enums.EncounterStatus.COMPLETED:
        return False
    if encounter.started_at is not None and encounter.ended_at is None:
        return True
    if encounter.status != enums.EncounterStatus.PENDING:
        return False
    if encounter.current_game_position is not None:
        return True
    return encounter.scheduled_at is not None and encounter.scheduled_at <= now and encounter.ended_at is None


def _upcoming_condition(now: datetime) -> sa.ColumnElement[bool]:
    """Not decided and not in play: every open or pending series, scheduled or not."""
    return sa.and_(
        models.Encounter.status.in_([enums.EncounterStatus.OPEN, enums.EncounterStatus.PENDING]),
        sa.not_(_live_condition(now)),
    )


# A decided series' own clock is trusted only near its tournament's dates: imported history carries the import's
# time in ``confirmed_at`` (a 2019 event "confirmed" in 2025), and a late confirmation lands a day or two after.
_PLAYED_EARLY_GRACE = timedelta(days=1)
_PLAYED_LATE_GRACE = timedelta(days=3)


def _tournament_date(column: sa.Column) -> sa.ScalarSelect:
    return (
        sa.select(column)
        .where(models.Tournament.id == models.Encounter.tournament_id)
        .correlate(models.Encounter)
        .scalar_subquery()
    )


def played_at_expr() -> sa.ColumnElement[datetime | None]:
    """When a decided series was played, or NULL when nothing trustworthy says.

    The first of: the hand-set end, the last parsed map, the result confirmation, the hand-set start -- kept only
    inside the tournament's ``[start - 1 day, end + 3 days]`` (each bound only when set). Readers fall back to the
    tournament's dates.
    """
    starts = _tournament_date(models.Tournament.start_date)
    ends = _tournament_date(models.Tournament.end_date)
    last_map = (
        sa.select(sa.func.max(models.StatsMatch.played_at))
        .where(models.StatsMatch.encounter_id == models.Encounter.id)
        .correlate(models.Encounter)
        .scalar_subquery()
    )
    raw = sa.func.coalesce(
        models.Encounter.ended_at, last_map, models.Encounter.confirmed_at, models.Encounter.started_at
    )
    return sa.case(
        (
            sa.and_(
                models.Encounter.status == enums.EncounterStatus.COMPLETED,
                raw.isnot(None),
                sa.or_(starts.is_(None), raw >= starts - _PLAYED_EARLY_GRACE),
                sa.or_(ends.is_(None), raw <= ends + _PLAYED_LATE_GRACE),
            ),
            raw,
        ),
        else_=sa.null(),
    )


def _played_at_sort_key() -> sa.ColumnElement[datetime | None]:
    """The ``played_at`` order: when it was played, else when it is due, else its tournament's dates."""
    return sa.func.coalesce(
        played_at_expr(),
        models.Encounter.scheduled_at,
        _tournament_date(models.Tournament.end_date),
        _tournament_date(models.Tournament.start_date),
        models.Encounter.created_at,
    )


#: The browse's sort keys (``EncounterSearchQueryParams.sort``), each a column of the row.
_SORT_COLUMNS: dict[str, typing.Any] = {
    "id": models.Encounter.id,
    "name": models.Encounter.name,
    "best_of": models.Encounter.best_of,
    "status": models.Encounter.status,
    "scheduled_at": models.Encounter.scheduled_at,
    "closeness": models.Encounter.closeness,
    "has_logs": models.Encounter.has_logs,
    "discipline": models.Encounter.discipline,
}


def _encounter_order(params: schemas.EncounterSearchParams) -> list[sa.UnaryExpression]:
    """``params.sort`` with NULLs last either way, then the id in the same direction: a page never reshuffles."""
    if params.sort == "played_at":
        key = _played_at_sort_key()
    elif params.sort in _SORT_COLUMNS:
        key = _SORT_COLUMNS[params.sort]
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid sort: {params.sort}")
    descending = params.order in (pagination.SortOrder.DESC, "desc")
    return [
        (key.desc() if descending else key.asc()).nulls_last(),
        models.Encounter.id.desc() if descending else models.Encounter.id.asc(),
    ]


#: What a strip encounter (the overview's live cards, the insights' closest) is read with.
STRIP_ENTITIES = ["tournament", "stage", "stage_item", "teams"]
_STRIP = 4
_HOT_MAPS = 6
#: The window of the overview's ``recent_completed``, by play date.
_RECENT = timedelta(days=7)
#: Saved views one viewer keeps per workspace.
SAVED_VIEW_LIMIT = 20


def _saved_view_exists(name: str) -> errors.ApiHTTPException:
    return errors.ApiHTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=[errors.ApiExc(code="saved_view_exists", msg=f"A saved view named {name!r} already exists")],
    )


class EncounterService:
    """Encounter/match reads: the public browse, the overview board and the
    per-match statistics the match page is built from.

    Almost every read here is analytical — multi-join, filtered, paginated, or a
    grouped aggregate — so it is built from a repository ``select()`` inside this
    class rather than hidden behind a CRUD repository method
    (``backend/docs/repository-boundaries.md``).
    """

    def __init__(
        self,
        *,
        encounter_repo: EncounterRepository = EncounterRepository(),
        saved_view_repo: EncounterSavedViewRepository = EncounterSavedViewRepository(),
    ) -> None:
        self.encounter_repo = encounter_repo
        self.saved_view_repo = saved_view_repo

    async def get_match(
        self,
        session: AsyncSession,
        id: int,
        entities: list[str],
        workspace_id: int | None = None,
    ) -> MatchReadContext | None:
        """A match of any discipline, scoped to the workspace when given; its own discipline governs every read."""
        query = sa.select(models.StatsMatch.id).where(models.StatsMatch.id == id)
        if workspace_id is not None:
            query = query.where(models.StatsMatch.workspace_id == workspace_id)
        if await session.scalar(query) is None:
            return None
        return (
            await get_match_reads(session, match_ids=[id], encounter_options=_match_encounter_options(entities))
        ).get(id)

    async def get_encounter(self, session: AsyncSession, id: int, entities: list[str]) -> models.Encounter | None:
        """The encounter with ``entities`` loaded, or ``None``."""
        return await self.encounter_repo.get(session, id, options=encounter_entities(entities))

    async def get_all_encounters(
        self,
        session: AsyncSession,
        params: schemas.EncounterSearchParams,
        workspace_id: int | None = None,
        viewer_auth_user_id: int | None = None,
    ) -> tuple[typing.Sequence[models.Encounter], int]:
        """One page of encounters matching ``params``, and the total count."""
        # Analytical: entity-driven joins + the shared filter builder + a DISTINCT count,
        # paired so the page and its total always share one predicate set.
        query = self.encounter_repo.select().options(*encounter_entities(params.entities))
        total_query = sa.select(sa.func.count(sa.distinct(models.Encounter.id)))
        query = join_encounter_entities(query, params.entities)
        total_query = join_encounter_entities(total_query, params.entities)

        query = _apply_encounter_filters(
            query,
            params,
            workspace_id=workspace_id,
            viewer_auth_user_id=viewer_auth_user_id,
            joined_tournament="tournament" in params.entities,
        )
        total_query = _apply_encounter_filters(
            total_query,
            params,
            workspace_id=workspace_id,
            viewer_auth_user_id=viewer_auth_user_id,
            joined_tournament="tournament" in params.entities,
        )

        query = params.apply_pagination(query.order_by(*_encounter_order(params)))

        return await execute_page_with_total(
            session,
            query,
            total_query,
            pk=models.Encounter.id,
            page=params.page,
            only_count=params.only_count,
        )

    async def played_at_by_encounter(
        self, session: AsyncSession, encounter_ids: typing.Sequence[int]
    ) -> dict[int, datetime | None]:
        """:func:`played_at_expr` of each encounter, in one statement."""
        if not encounter_ids:
            return {}
        rows = await session.execute(
            sa.select(models.Encounter.id, played_at_expr()).where(models.Encounter.id.in_(encounter_ids))
        )
        return dict(rows.tuples().all())

    async def is_final_by_encounter(
        self, session: AsyncSession, encounter_ids: typing.Sequence[int]
    ) -> dict[int, bool]:
        """:func:`_is_final_condition` of each encounter, in one statement."""
        if not encounter_ids:
            return {}
        rows = await session.execute(
            sa.select(models.Encounter.id, _is_final_condition()).where(models.Encounter.id.in_(encounter_ids))
        )
        return dict(rows.tuples().all())

    async def get_saved_views(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        auth_user_id: int,
    ) -> typing.Sequence[models.EncounterSavedView]:
        return await self.saved_view_repo.list_for_user(session, workspace_id=workspace_id, auth_user_id=auth_user_id)

    async def create_saved_view(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        auth_user_id: int,
        name: str,
        filters: dict,
    ) -> models.EncounterSavedView:
        """A new view of the caller's: 409 ``saved_view_exists`` when the name is taken, ``saved_view_limit`` once
        the caller already keeps ``SAVED_VIEW_LIMIT`` in the workspace."""
        # Analytical: the owner's name clash, view count and next sort slot in one aggregate projection.
        owned = (
            await session.execute(
                sa.select(
                    sa.func.count().filter(models.EncounterSavedView.name == name).label("taken"),
                    sa.func.count().label("count"),
                    (sa.func.coalesce(sa.func.max(models.EncounterSavedView.sort_order), -1) + 1).label("next"),
                ).where(
                    models.EncounterSavedView.workspace_id == workspace_id,
                    models.EncounterSavedView.auth_user_id == auth_user_id,
                )
            )
        ).one()
        if owned.taken:
            raise _saved_view_exists(name)
        # ponytail: a count-then-insert cap; two saves racing at the limit can both land. A per-owner lock if it
        # ever matters -- the cap guards against runaway clients, it is not an invariant.
        if owned.count >= SAVED_VIEW_LIMIT:
            raise errors.ApiHTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=[
                    errors.ApiExc(
                        code="saved_view_limit",
                        msg=f"At most {SAVED_VIEW_LIMIT} saved views per workspace; delete one first",
                    )
                ],
            )
        saved_view = models.EncounterSavedView(
            workspace_id=workspace_id,
            auth_user_id=auth_user_id,
            name=name,
            filters_json=filters,
            sort_order=int(owned.next),
        )
        try:
            await self.saved_view_repo.create(session, saved_view)
            await session.commit()
        except IntegrityError as exc:
            # A concurrent save of the same name won ``uq_encounter_saved_view_workspace_user_name``.
            await session.rollback()
            raise _saved_view_exists(name) from exc
        await session.refresh(saved_view)
        return saved_view

    async def delete_saved_view(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        auth_user_id: int,
        saved_view_id: int,
    ) -> None:
        saved_view = await self.saved_view_repo.get_owned(
            session,
            saved_view_id=saved_view_id,
            workspace_id=workspace_id,
            auth_user_id=auth_user_id,
        )
        if saved_view is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved view not found")
        await self.saved_view_repo.delete(session, saved_view)
        await session.commit()

    async def get_overview_data(
        self,
        session: AsyncSession,
        params: schemas.EncounterSearchParams,
        *,
        workspace_id: int | None = None,
        viewer_auth_user_id: int | None = None,
    ) -> dict[str, typing.Any]:
        """The overview's ``counts`` (``EncounterCountsRead``'s keys), ``completed_with_logs``, ``recent_completed``
        and its live strip (``live``): one aggregate statement and one strip read, whatever the filters."""
        now = datetime.now(UTC)
        status_filter = _status_predicate(params.status, now) if params.status else sa.true()
        toggles = _toggle_clauses(params, viewer_auth_user_id)

        def toggled(but: str | None = None) -> sa.ColumnElement[bool]:
            return sa.and_(sa.true(), *(clause for name, clause in toggles.items() if name != but))

        every = toggled()
        completed = models.Encounter.status == enums.EncounterStatus.COMPLETED
        has_logs = models.Encounter.has_logs.is_(True)
        # The filters every count shares are the WHERE; the status and the toggles are per-count FILTERs, so the
        # search runs once for all of them. A segment ignores the status and keeps the toggles; a toggle keeps the
        # status and the other toggles, and forces itself on.
        counts = (
            await session.execute(
                _apply_encounter_filters(
                    sa.select(
                        sa.func.count().filter(every).label("all"),
                        sa.func.count().filter(every, _live_condition(now)).label("live"),
                        sa.func.count().filter(every, _upcoming_condition(now)).label("upcoming"),
                        sa.func.count().filter(every, completed).label("completed"),
                        sa.func.count()
                        .filter(status_filter, toggled("is_final"), _is_final_condition())
                        .label("finals"),
                        sa.func.count()
                        .filter(status_filter, toggled("is_upset"), _is_upset_condition())
                        .label("upsets"),
                        sa.func.count().filter(status_filter, toggled("has_logs"), has_logs).label("with_logs"),
                        sa.func.count()
                        .filter(status_filter, toggled("scope"), _my_team_condition(viewer_auth_user_id))
                        .label("my_team"),
                        sa.func.count().filter(every, completed, has_logs).label("completed_with_logs"),
                        # The play date last: its correlated reads only run for a completed row.
                        sa.func.count()
                        .filter(every, completed, played_at_expr() >= now - _RECENT)
                        .label("recent_completed"),
                    ).select_from(models.Encounter),
                    _without_status_and_toggles(params),
                    workspace_id=workspace_id,
                    viewer_auth_user_id=viewer_auth_user_id,
                )
            )
        ).one()
        live = (
            (
                await session.execute(
                    _apply_encounter_filters(
                        self.encounter_repo.select().options(*encounter_entities(STRIP_ENTITIES)),
                        replace(params, status="live"),
                        workspace_id=workspace_id,
                        viewer_auth_user_id=viewer_auth_user_id,
                    )
                    .order_by(models.Encounter.started_at.desc().nulls_last(), models.Encounter.id.desc())
                    .limit(_STRIP)
                )
            )
            .unique()
            .scalars()
            .all()
        )
        totals = counts._asdict()
        return {
            "counts": {name: totals[name] for name in schemas.EncounterCountsRead.model_fields},
            "completed_with_logs": totals["completed_with_logs"],
            "recent_completed": totals["recent_completed"],
            "live": live,
        }

    async def get_my_team_count(
        self,
        session: AsyncSession,
        params: schemas.EncounterSearchParams,
        *,
        workspace_id: int | None = None,
        viewer_auth_user_id: int,
    ) -> int:
        """The overview's ``my_team`` count alone -- the one count that depends on the viewer whatever the scope --
        so the rest of the overview can be cached without one. The same clauses as its ``FILTER`` there."""
        toggles = _toggle_clauses(params, viewer_auth_user_id)
        toggles.pop("scope", None)
        query = _apply_encounter_filters(
            sa.select(sa.func.count()).select_from(models.Encounter),
            _without_status_and_toggles(params),
            workspace_id=workspace_id,
        ).where(
            _status_predicate(params.status, datetime.now(UTC)) if params.status else sa.true(),
            *toggles.values(),
            _my_team_condition(viewer_auth_user_id),
        )
        return int(await session.scalar(query) or 0)

    async def get_insights_data(
        self,
        session: AsyncSession,
        params: schemas.EncounterSearchParams,
        *,
        workspace_id: int | None = None,
        viewer_auth_user_id: int | None = None,
    ) -> dict[str, typing.Any]:
        """The analytics of the completed encounters ``params`` match (its status is forced to ``completed``): one
        aggregate, the score lines, the maps and the closest strip -- four statements whatever the filters."""
        params = replace(params, status=enums.EncounterStatus.COMPLETED.value)

        def scoped(query: sa.Select) -> sa.Select:
            return _apply_encounter_filters(
                query, params, workspace_id=workspace_id, viewer_auth_user_id=viewer_auth_user_id
            )

        encounter = models.Encounter
        # The seat metrics read SEATS -- slot 1 against slot 2 -- so only a duel has them; a lobby has no two sides.
        duel = encounter.slot_count == 2
        seat_one = aliased(models.EncounterTeam)
        seat_two = aliased(models.EncounterTeam)
        position = aliased(models.BracketEncounter)
        stage = aliased(models.Stage)

        def seat(alias: typing.Any, slot: int) -> sa.ColumnElement[bool]:
            return sa.and_(alias.encounter_id == encounter.id, alias.slot == slot, alias.active.is_(True))

        # Sweeps and series that went the distance only mean something past one map: every decided Bo1 is both.
        # ``multi_map`` is their base, so a reader's rate is ``sweeps / multi_map``.
        series = sa.and_(duel, encounter.best_of > 1, seat_one.score.isnot(None), seat_two.score.isnot(None))

        series_seconds = (
            sa.select(sa.func.sum(models.StatsMatch.duration_s))
            .where(
                models.StatsMatch.encounter_id == encounter.id,
                models.StatsMatch.workspace_id == encounter.workspace_id,
                models.StatsMatch.discipline == encounter.discipline,
            )
            .correlate(encounter)
            .scalar_subquery()
        )
        # ``[start, end)`` tenths, the last closed at 1: the bounds ``closeness_min`` reads, so a bucket's click
        # filters the list to what it counted.
        buckets = [
            sa.and_(encounter.closeness >= index / 10, encounter.closeness < (index + 1) / 10)
            if index < 9
            else encounter.closeness >= index / 10
            for index in range(10)
        ]
        kinds = {
            # An FFA league's items are groups too.
            "groups": stage.stage_type.in_([enums.StageType.ROUND_ROBIN, enums.StageType.FFA_LEAGUE]),
            "playoffs": stage.stage_type.in_([enums.StageType.SINGLE_ELIMINATION, enums.StageType.DOUBLE_ELIMINATION]),
            "swiss": stage.stage_type == enums.StageType.SWISS,
            "unassigned": stage.id.is_(None),
        }
        totals = (
            await session.execute(
                scoped(
                    sa.select(
                        sa.func.count().label("completed"),
                        sa.func.avg(encounter.closeness).label("avg_closeness"),
                        # A series with no parsed log sums to NULL, which avg() skips.
                        sa.func.avg(series_seconds).label("avg_series_seconds"),
                        sa.func.count().filter(series).label("multi_map"),
                        sa.func.count()
                        .filter(
                            series, sa.or_(seat_one.score == 0, seat_two.score == 0), seat_one.score != seat_two.score
                        )
                        .label("sweeps"),
                        sa.func.count()
                        .filter(series, seat_one.score + seat_two.score == encounter.best_of)
                        .label("went_distance"),
                        *(
                            sa.func.count().filter(bucket).label(f"bucket_{index}")
                            for index, bucket in enumerate(buckets)
                        ),
                        *(sa.func.count().filter(clause).label(f"kind_{kind}") for kind, clause in kinds.items()),
                    )
                    .select_from(encounter)
                    .outerjoin(seat_one, seat(seat_one, 1))
                    .outerjoin(seat_two, seat(seat_two, 2))
                    .outerjoin(position, position.encounter_id == encounter.id)
                    .outerjoin(stage, stage.id == position.stage_id)
                )
            )
        ).one()

        winner = sa.cast(sa.func.greatest(seat_one.score, seat_two.score), sa.Integer).label("winner")
        loser = sa.cast(sa.func.least(seat_one.score, seat_two.score), sa.Integer).label("loser")
        score_lines = await session.execute(
            scoped(
                sa.select(winner, loser, sa.func.count())
                .select_from(encounter)
                .join(seat_one, seat(seat_one, 1))
                .join(seat_two, seat(seat_two, 2))
                .where(duel)
            )
            .group_by(winner, loser)
            .order_by(sa.func.count().desc(), winner.desc(), loser.asc())
        )
        hot_maps = await session.execute(
            scoped(
                sa.select(models.CatalogEntity.name, sa.func.count(models.StatsMatch.id))
                .select_from(models.StatsMatch)
                .join(
                    encounter,
                    sa.and_(
                        encounter.id == models.StatsMatch.encounter_id,
                        encounter.workspace_id == models.StatsMatch.workspace_id,
                        encounter.discipline == models.StatsMatch.discipline,
                    ),
                )
                .join(
                    models.CatalogEntity,
                    sa.and_(
                        models.StatsMatch.map_entity_id == models.CatalogEntity.id,
                        models.CatalogEntity.discipline == models.StatsMatch.discipline,
                        models.CatalogEntity.kind == "map",
                    ),
                )
            )
            .group_by(models.CatalogEntity.name)
            .order_by(sa.func.count(models.StatsMatch.id).desc(), models.CatalogEntity.name)
            .limit(_HOT_MAPS)
        )
        closest = (
            (
                await session.execute(
                    scoped(
                        self.encounter_repo.select()
                        .options(*encounter_entities(STRIP_ENTITIES))
                        .where(encounter.closeness.isnot(None))
                    )
                    .order_by(
                        encounter.closeness.desc(),
                        encounter.updated_at.desc().nulls_last(),
                        encounter.id.desc(),
                    )
                    .limit(_STRIP)
                )
            )
            .unique()
            .scalars()
            .all()
        )

        stage_kinds = [(kind, int(getattr(totals, f"kind_{kind}"))) for kind in kinds]
        return {
            "completed": int(totals.completed),
            "avg_closeness": None if totals.avg_closeness is None else float(totals.avg_closeness),
            "avg_series_seconds": None if totals.avg_series_seconds is None else float(totals.avg_series_seconds),
            "multi_map": int(totals.multi_map),
            "sweeps": int(totals.sweeps),
            "went_distance": int(totals.went_distance),
            "closeness_histogram": [
                (index / 10, (index + 1) / 10, int(getattr(totals, f"bucket_{index}"))) for index in range(10)
            ],
            # Most common first; ``sorted`` is stable, so a tie keeps the kinds' own order.
            "stage_kinds": sorted(
                ((kind, count) for kind, count in stage_kinds if count), key=lambda item: item[1], reverse=True
            ),
            "score_lines": [tuple(row) for row in score_lines.tuples()],
            "hot_maps": [tuple(row) for row in hot_maps.tuples()],
            "closest": closest,
        }

    async def get_all_matches(
        self,
        session: AsyncSession,
        params: schemas.MatchSearchParams,
        workspace_id: int | None = None,
    ) -> tuple[typing.Sequence[MatchReadContext], int]:
        d = match_context()
        mt, seat = models.StatsMatchTeam, models.EncounterTeam
        query = (
            sa.select(d.c.id)
            .select_from(d)
            .join(models.Encounter, models.Encounter.id == d.c.encounter_id)
            .join(
                models.Tournament,
                sa.and_(
                    models.Tournament.id == d.c.tournament_id,
                    models.Tournament.workspace_id == d.c.workspace_id,
                    models.Tournament.discipline == d.c.discipline,
                ),
            )
            .join(
                models.CatalogEntity,
                sa.and_(
                    models.CatalogEntity.id == d.c.map_entity_id,
                    models.CatalogEntity.discipline == d.c.discipline,
                    models.CatalogEntity.kind == "map",
                ),
            )
            .outerjoin(
                models.IngestJob,
                sa.and_(
                    models.IngestJob.id == d.c.ingest_job_id,
                    models.IngestJob.workspace_id == d.c.workspace_id,
                    models.IngestJob.discipline == d.c.discipline,
                ),
            )
        )
        if params.tournament_id:
            query = query.where(d.c.tournament_id == params.tournament_id)
        else:
            query = query.where(d.c.tournament_id.in_(visible_tournament_ids_subquery(None)))
        if workspace_id is not None:
            query = query.where(d.c.workspace_id == workspace_id)

        def participants(*criteria: sa.ColumnElement[bool]) -> sa.ColumnElement[bool]:
            """Some participant of the match, whichever seat it held, satisfies ``criteria``."""
            return sa.exists(
                sa.select(1)
                .select_from(mt)
                .join(seat, sa.and_(seat.id == mt.encounter_team_id, seat.encounter_id == mt.encounter_id))
                .where(mt.match_id == d.c.id, *criteria)
            )

        if params.tournament_team_id:
            query = query.where(participants(seat.team_id == params.tournament_team_id))
        columns = {
            "id": d.c.id,
            "created_at": d.c.created_at,
            "updated_at": d.c.updated_at,
            "played_at": d.c.played_at,
            "duration_s": d.c.duration_s,
            "map_index": d.c.position,
            "map_id": d.c.map_entity_id,
            "encounter_id": d.c.encounter_id,
            "log_name": models.IngestJob.filename,
            "map.name": models.CatalogEntity.name,
            "encounter.name": models.Encounter.name,
            "map.id": d.c.map_entity_id,
            "map.slug": models.CatalogEntity.slug,
            "encounter.id": d.c.encounter_id,
            "encounter.tournament_id": d.c.tournament_id,
        }
        if params.query:
            like = f"%{params.query}%"
            criteria = []
            for field in params.fields:
                if field == "participants.name":
                    criteria.append(participants(seat.name.ilike(like)))
                    continue
                if field not in columns:
                    raise HTTPException(status_code=400, detail=f"Invalid match search field: {field}")
                column = columns[field]
                criteria.append(column.ilike(like))
                if field == "log_name":
                    criteria.append(sa.func.split_part(column, ".", 1).ilike(like))
            if criteria:
                query = query.where(sa.or_(*criteria))
        total = int(await session.scalar(sa.select(sa.func.count()).select_from(query.distinct().subquery())) or 0)
        if params.only_count:
            return [], total
        field = params.sort.removeprefix("similarity:")
        if field not in columns:
            raise HTTPException(status_code=400, detail=f"Invalid match sort field: {field}")
        order_column = columns[field]
        if params.sort.startswith("similarity:"):
            order_column = sa.func.word_similarity(order_column, params.query)
        descending = params.order == "desc" or getattr(params.order, "value", None) == "desc"
        order = order_column.desc() if descending else order_column.asc()
        # The id breaks ties, so a page boundary never depends on physical row order.
        query = query.order_by(order.nullslast() if field == "map_index" else order, d.c.id)
        query = params.apply_pagination(query)
        ids = list((await session.scalars(query)).all())
        reads = await self.get_match_bulk(session, ids, params.entities)
        return reads, total

    async def get_match_bulk(
        self,
        session: AsyncSession,
        matches_id: list[int],
        entities: list[str],
    ) -> list[MatchReadContext]:
        """The requested matches in the requested order; an id that is not a readable match is skipped."""
        reads = await get_match_reads(
            session, match_ids=matches_id, encounter_options=_match_encounter_options(entities)
        )
        return [reads[id] for id in matches_id if id in reads]


encounter_service = EncounterService()
