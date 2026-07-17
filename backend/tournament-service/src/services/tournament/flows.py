import statistics
import typing
from itertools import groupby

import sqlalchemy as sa
from cashews import cache
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.division_grid import DivisionGrid
from shared.models.identity.auth_user import AuthUser
from shared.services.challonge_refs import ChallongeRef, resolve_stage_challonge, resolve_tournament_challonge
from shared.services.division_grid_normalization import DivisionGridNormalizationError, DivisionGridNormalizer
from shared.services.division_grid_resolution import resolve_tournament_division
from shared.services.tournament_visibility import visible_tournaments_predicate
from src import models, schemas
from src.core import config, enums, errors, pagination
from src.services.registration import service as registration_service
from src.services.team import service as team_service
from src.services.user import flows as user_flows

from . import service


def _entity_requested(entities: list[str], entity: str) -> bool:
    return entity in entities or any(item.startswith(f"{entity}.") for item in entities)


def _loaded_relationship(model: typing.Any, name: str) -> typing.Any | None:
    if name in sa.inspect(model).unloaded:
        return None
    return getattr(model, name)


def _apply_stage_challonge(
    stage_read: schemas.StageSummaryRead,
    stage_id: int,
    stage_challonge_refs: typing.Mapping[int, ChallongeRef] | None,
) -> schemas.StageSummaryRead:
    """Override the KEPT ``challonge_id``/``challonge_slug`` fields with values
    DERIVED from ``challonge_source`` (never the legacy ``stage`` columns)."""
    challonge_id, challonge_slug = (
        stage_challonge_refs.get(stage_id, (None, None)) if stage_challonge_refs is not None else (None, None)
    )
    return stage_read.model_copy(update={"challonge_id": challonge_id, "challonge_slug": challonge_slug})


async def to_pydantic(
    session: AsyncSession,
    tournament: models.Tournament,
    entities: list[str],
    *,
    participants_counts: typing.Mapping[int, int] | None = None,
    registrations_counts: typing.Mapping[int, int] | None = None,
    teams_counts: typing.Mapping[int, int] | None = None,
    challonge_ref: ChallongeRef | None = None,
    stage_challonge_refs: typing.Mapping[int, ChallongeRef] | None = None,
) -> schemas.TournamentRead:
    """
    Converts a `Tournament` model instance to a Pydantic `TournamentRead` schema, optionally including related entities.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.
        tournament: The `Tournament` model instance to convert.
        entities: A list of strings representing the names of related entities to include.
        challonge_ref: Optional prefetched ``(challonge_id, slug)`` DERIVED from
            ``challonge_source`` (see ``shared.services.challonge_refs``). When
            omitted the fields serialize as ``None`` — callers resolve/pass it so
            the serializer never reads the deprecated ``tournament`` columns nor
            issues a per-row query.
        stage_challonge_refs: Optional prefetched ``stage_id -> (challonge_id, slug)``
            map used the same way for nested ``stages``.

    Returns:
        A `TournamentRead` schema instance.
    """
    stages: list[schemas.StageSummaryRead] = []
    participants_count: int | None = None
    registrations_count: int | None = None
    teams_count: int | None = None
    if "stages" in entities:
        stage_models = _loaded_relationship(tournament, "stages") or []
        stages = [
            _apply_stage_challonge(
                schemas.StageSummaryRead.model_validate(stage, from_attributes=True),
                stage.id,
                stage_challonge_refs,
            )
            for stage in sorted(stage_models, key=lambda item: item.order)
        ]
    if "participants_count" in entities:
        if participants_counts is not None:
            participants_count = participants_counts.get(tournament.id, 0)
        else:
            participants_count = await team_service.get_player_count_by_tournament(session, tournament.id)
    if "registrations_count" in entities:
        if registrations_counts is not None:
            registrations_count = registrations_counts.get(tournament.id, 0)
        else:
            registrations_count = await registration_service.get_registration_count_by_tournament(
                session, tournament.id
            )
    if "teams_count" in entities:
        if teams_counts is not None:
            teams_count = teams_counts.get(tournament.id, 0)
        else:
            teams_count = await team_service.get_team_count_by_tournament(session, tournament.id)
    division_grid_version = None
    if _entity_requested(entities, "division_grid_version"):
        division_grid_version_model = _loaded_relationship(tournament, "division_grid_version")
        if division_grid_version_model is not None:
            division_grid_version = schemas.DivisionGridVersionRead.model_validate(
                division_grid_version_model,
                from_attributes=True,
            )
    tournament_challonge_id, tournament_challonge_slug = challonge_ref if challonge_ref is not None else (None, None)
    return schemas.TournamentRead(
        id=tournament.id,
        workspace_id=tournament.workspace_id,
        start_date=tournament.start_date,
        end_date=tournament.end_date,
        number=tournament.number,
        is_league=tournament.is_league,
        is_finished=tournament.is_finished,
        is_hidden=tournament.is_hidden,
        team_formation=tournament.team_formation,
        status=tournament.status,
        name=tournament.name,
        description=tournament.description,
        challonge_id=tournament_challonge_id,
        challonge_slug=tournament_challonge_slug,
        auto_transitions_enabled=tournament.auto_transitions_enabled,
        allow_late_registration=tournament.allow_late_registration,
        phase_schedule=[
            schemas.TournamentPhaseScheduleRead.model_validate(row, from_attributes=True)
            for row in _loaded_relationship(tournament, "phase_schedule") or []
        ],
        win_points=tournament.win_points,
        draw_points=tournament.draw_points,
        loss_points=tournament.loss_points,
        division_grid_version_id=tournament.division_grid_version_id,
        division_grid_version=division_grid_version,
        stages=stages,
        participants_count=participants_count,
        registrations_count=registrations_count,
        teams_count=teams_count,
    )


async def to_pydantic_group(
    session: AsyncSession,
    group: models.TournamentGroup,
    entities: list[str],
) -> schemas.TournamentGroupRead:
    """
    Converts a `TournamentGroup` model instance to a Pydantic `TournamentGroupRead` schema.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.
        group: The `TournamentGroup` model instance to convert.
        entities: A list of strings representing the names of related entities to include.

    Returns:
        A `TournamentGroupRead` schema instance.
    """
    # group.challonge_id/slug is a KEPT column (dbarch04b does NOT drop it — it
    # holds Challonge's per-group match-routing id, which has no challonge_source
    # equivalent). Read it directly; do NOT derive it from challonge_source (the
    # shared bracket is stored as a source_type='stage'/'tournament' row, so a
    # 'group'-scoped lookup would wrongly return NULL for historical tournaments).
    return schemas.TournamentGroupRead(
        id=group.id,
        name=group.name,
        is_groups=group.is_groups,
        challonge_id=group.challonge_id,
        challonge_slug=group.challonge_slug,
        description=group.description,
    )


async def get(session: AsyncSession, id: int, entities: list[str]) -> models.Tournament:
    """
    Retrieves a `Tournament` model instance by its ID, optionally including related entities.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.
        id: The ID of the tournament to retrieve.
        entities: A list of strings representing the names of related entities to include.

    Returns:
        A `Tournament` model instance.

    Raises:
        errors.ApiHTTPException: If the tournament is not found.
    """
    tournament = await service.get(session, id, entities)
    if tournament is None:
        raise errors.ApiHTTPException(
            status_code=404,
            detail=[
                errors.ApiExc(
                    code="tournament_not_found",
                    msg="Tournament with this id not found",
                )
            ],
        )
    return tournament


@cache(
    ttl=config.settings.tournaments_cache_ttl,
    # Key deliberately contains "tournaments/{id}" so the existing
    # invalidation pattern `*tournaments/{tournament_id}*` (see
    # cache_invalidation.tournament_cache_patterns) purges it on change.
    key="tournaments/{id}:{entities}",
    prefix="fastapi:",
)
async def get_read(session: AsyncSession, id: int, entities: list[str]) -> schemas.TournamentRead:
    """
    Retrieves a `Tournament` model instance by its ID and converts it to a `TournamentRead` schema.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.
        id: The ID of the tournament to retrieve.
        entities: A list of strings representing the names of related entities to include.

    Returns:
        A `TournamentRead` schema instance.
    """
    tournament = await get(session, id, entities)
    challonge_ref = (await resolve_tournament_challonge(session, [tournament.id])).get(tournament.id)
    stage_challonge_refs: typing.Mapping[int, ChallongeRef] | None = None
    if "stages" in entities:
        stage_models = _loaded_relationship(tournament, "stages") or []
        stage_challonge_refs = await resolve_stage_challonge(session, [stage.id for stage in stage_models])
    return await to_pydantic(
        session,
        tournament,
        entities,
        challonge_ref=challonge_ref,
        stage_challonge_refs=stage_challonge_refs,
    )


async def lookup(
    session: AsyncSession,
    *,
    workspace_id: int | None = None,
    is_league: bool | None = None,
    limit: int = 500,
) -> list[schemas.LookupItem]:
    """Lightweight id/name lookup for pickers (rpc.tournament.lookup_tournaments)."""
    query = (
        sa.select(models.Tournament.id, models.Tournament.name)
        # Hidden tournaments never appear in public pickers/lookups (issue #115).
        .where(models.Tournament.is_hidden.is_(False))
        .order_by(models.Tournament.id.desc())
        .limit(limit)
    )
    if workspace_id is not None:
        query = query.where(models.Tournament.workspace_id == workspace_id)
    if is_league is not None:
        query = query.where(models.Tournament.is_league.is_(is_league))
    result = await session.execute(query)
    return [schemas.LookupItem(id=row.id, name=row.name) for row in result.all()]


async def get_stages_read(session: AsyncSession, tournament_id: int) -> list[schemas.StageRead]:
    """Ordered stages (with items/inputs) for a tournament (rpc.tournament.get_stages)."""
    result = await session.execute(
        sa.select(models.Stage)
        .where(models.Stage.tournament_id == tournament_id)
        .options(selectinload(models.Stage.items).selectinload(models.StageItem.inputs))
        .order_by(models.Stage.order)
    )
    stages = list(result.scalars().all())
    stage_challonge_refs = await resolve_stage_challonge(session, [stage.id for stage in stages])
    output: list[schemas.StageRead] = []
    for stage in stages:
        stage_read = schemas.StageRead.model_validate(stage, from_attributes=True)
        challonge_id, challonge_slug = stage_challonge_refs.get(stage.id, (None, None))
        output.append(stage_read.model_copy(update={"challonge_id": challonge_id, "challonge_slug": challonge_slug}))
    return output


async def get_by_number_and_league(
    session: AsyncSession, number: int, is_league: bool, entities: list[str]
) -> models.Tournament:
    """
    Retrieves a `Tournament` model instance by its number and league status, optionally including related entities.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.
        number: The number of the tournament to retrieve.
        is_league: Whether the tournament is a league.
        entities: A list of strings representing the names of related entities to include.

    Returns:
        A `Tournament` model instance.

    Raises:
        errors.ApiHTTPException: If the tournament is not found.
    """
    tournament = await service.get_by_number_and_league(session, number, is_league, entities)
    if tournament is None:
        raise errors.ApiHTTPException(
            status_code=404,
            detail=[
                errors.ApiExc(
                    code="tournament_not_found",
                    msg="Tournament with this number not found",
                )
            ],
        )
    return tournament


async def get_all(
    session: AsyncSession,
    params: schemas.TournamentPaginationSortSearchParams,
    *,
    viewer: AuthUser | None = None,
) -> pagination.Paginated[schemas.TournamentRead]:
    """
    Retrieves a paginated list of `Tournament` model instances and converts them to `TournamentRead` schemas.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.
        params: An instance of `SearchPaginationParams` containing pagination and filtering parameters.

    Returns:
        A `Paginated` instance containing `TournamentRead` schemas.
    """
    results, total = await service.get_all(
        session, params, visibility=visible_tournaments_predicate(viewer)
    )
    tournament_ids = [result.id for result in results]
    participants_counts = (
        await team_service.get_player_count_by_tournament_bulk(session, tournament_ids)
        if "participants_count" in params.entities
        else None
    )
    registrations_counts = (
        await registration_service.get_registration_count_by_tournament_bulk(session, tournament_ids)
        if "registrations_count" in params.entities
        else None
    )
    teams_counts = (
        await team_service.get_team_count_by_tournament_bulk(session, tournament_ids)
        if "teams_count" in params.entities
        else None
    )
    # Batched Challonge-ref derivation (no N+1): one query for every tournament id
    # on the page, plus one for every loaded stage id when stages are requested.
    challonge_refs = await resolve_tournament_challonge(session, tournament_ids)
    stage_challonge_refs: typing.Mapping[int, ChallongeRef] | None = None
    if "stages" in params.entities:
        stage_ids = [stage.id for result in results for stage in (_loaded_relationship(result, "stages") or [])]
        stage_challonge_refs = await resolve_stage_challonge(session, stage_ids)
    return pagination.Paginated(
        results=[
            await to_pydantic(
                session,
                result,
                params.entities,
                participants_counts=participants_counts,
                registrations_counts=registrations_counts,
                teams_counts=teams_counts,
                challonge_ref=challonge_refs.get(result.id),
                stage_challonge_refs=stage_challonge_refs,
            )
            for result in results
        ],
        total=total,
        per_page=params.per_page,
        page=params.page,
    )


@cache(
    ttl=config.settings.tournaments_cache_ttl,
    # No tournament_id in the args, so this key can't participate in the
    # targeted invalidation patterns — staleness is bounded by the short TTL.
    key="tournaments_statistics_history:{workspace_id}",
    prefix="fastapi:",
)
async def get_history_tournaments(
    session: AsyncSession,
    workspace_id: int | None = None,
) -> list[schemas.TournamentStatistics]:
    """
    Retrieves historical statistics for tournaments.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.

    Returns:
        A list of `TournamentStatistics` schemas.
    """
    output: list[schemas.TournamentStatistics] = []
    stats = await service.get_history_tournaments(session, workspace_id=workspace_id)
    for stat in stats:
        if stat[2] is None:
            continue
        output.append(
            schemas.TournamentStatistics(
                id=stat[0].id,
                number=stat[0].number,
                players_count=stat[1],
                avg_sr=round(stat[2], 2),
                avg_closeness=stat[3],
            )
        )
    return output


async def get_avg_divisions_tournaments(
    session: AsyncSession,
    workspace_id: int | None = None,
    *,
    normalizer: DivisionGridNormalizer | None = None,
    fallback_grid: DivisionGrid,
) -> list[schemas.DivisionStatistics]:
    """
    Retrieves average division statistics for tournaments, normalizing each
    tournament's player ranks through the tournament's own division_grid_version
    before averaging.

    When a normalizer is provided, divisions are converted to the target grid so
    values are comparable across tournaments that used different grid versions.
    Falls back to fallback_grid for tournaments that have no grid version set.
    """
    # Values are (division_number, players_count) pairs: the service layer
    # aggregates players to a per-(tournament, role, rank) histogram, so the
    # average is weighted by the count instead of iterating every player row.
    raw_rank_cache: dict[int, dict[enums.HeroClass, list[tuple[float, int]]]] = {}
    tournament_numbers: dict[int, int] = {}

    rows = await service.get_avg_div_tournaments(session, workspace_id=workspace_id)
    for tournament, role, rank, players_count in rows:
        if tournament.id not in raw_rank_cache:
            raw_rank_cache[tournament.id] = {}
            tournament_numbers[tournament.id] = tournament.number

        source_version_id: int | None = tournament.division_grid_version_id

        if normalizer is not None and source_version_id is not None:
            try:
                div_number = normalizer.normalize_division_number(source_version_id, rank)
            except DivisionGridNormalizationError:
                # Mapping incomplete — use tournament's own grid without normalizing
                source_grid = normalizer.source_grids_by_version_id.get(source_version_id, fallback_grid)
                div_number = source_grid.resolve_division_number(rank)
        elif normalizer is not None:
            # Tournament has no grid; use the normalizer's target grid
            div_number = normalizer.target_grid.resolve_division_number(rank)
        else:
            # No normalizer — use fallback (workspace/global default) grid
            div_number = fallback_grid.resolve_division_number(rank)

        raw_rank_cache[tournament.id].setdefault(role, []).append((float(div_number), int(players_count)))

    def avg_or_none(values: list[tuple[float, int]] | None) -> float | None:
        if not values:
            return None
        total_players = sum(count for _, count in values)
        if not total_players:
            return None
        return round(sum(division * count for division, count in values) / total_players, 2)

    output: list[schemas.DivisionStatistics] = []
    for tournament_id, roles in raw_rank_cache.items():
        output.append(
            schemas.DivisionStatistics(
                id=tournament_id,
                number=tournament_numbers[tournament_id],
                tank_avg_div=avg_or_none(roles.get(enums.HeroClass.tank)),
                damage_avg_div=avg_or_none(roles.get(enums.HeroClass.damage)),
                support_avg_div=avg_or_none(roles.get(enums.HeroClass.support)),
            )
        )

    return output


async def get_tournaments_overall(session: AsyncSession, workspace_id: int | None = None) -> schemas.OverallStatistics:
    """
    Retrieves overall statistics for tournaments, including counts of tournaments, teams, players, and champions.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.

    Returns:
        An `OverallStatistics` schema instance.
    """
    tournaments, teams, players, champions = await service.get_tournaments_overall(session, workspace_id=workspace_id)
    return schemas.OverallStatistics(
        tournaments=tournaments,
        teams=teams,
        players=players,
        champions=champions,
    )


async def get_owal_standings(
    session: AsyncSession,
    season: str | None = None,
    workspace_id: int | None = None,
    *,
    grid: DivisionGrid,
) -> schemas.OwalStandings:
    """
    Retrieves OWAL (Overwatch Anak League) standings.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.

    Returns:
        An `OwalStandings` schema instance.
    """
    seasons = await service.get_owal_seasons(session, workspace_id=workspace_id)
    if not seasons:
        raise errors.ApiHTTPException(
            status_code=404,
            detail=[
                errors.ApiExc(
                    code="owal_seasons_not_found",
                    msg="OWAL seasons not found",
                )
            ],
        )

    return await get_owal_standings_by_season(
        session,
        season or seasons[0],
        workspace_id=workspace_id,
        grid=grid,
    )


async def get_owal_standings_by_season(
    session: AsyncSession,
    season: str,
    workspace_id: int | None = None,
    *,
    grid: DivisionGrid,
) -> schemas.OwalStandings:
    standings_output: list[schemas.OwalStanding] = []
    cache: dict[int, dict[enums.HeroClass, dict[int, schemas.OwalStandingDay]]] = {}
    user_cache: dict[int, models.User] = {}
    user_pydantic_cache: dict[int, schemas.UserRead] = {}

    standings = await service.get_owal_standings(session, season, workspace_id=workspace_id)
    days_tournament = await service.get_owal_days(session, season, workspace_id=workspace_id)
    for user, team, tournament, player in standings:
        cache.setdefault(user.id, {})
        cache[user.id].setdefault(player.role, {})
        user_cache.setdefault(user.id, user)
        standing = team.standings[0]

        cache[user.id][player.role][tournament.id] = schemas.OwalStandingDay(
            team=team.name,
            role=player.role,
            division=resolve_tournament_division(
                player.rank,
                tournament_grid=grid,
            ),
            points=standing.win + standing.draw * 0.5 + standing.buchholz * 0.01,
            wins=standing.win,
            draws=standing.draw,
            losses=standing.lose,
            win_rate=round(
                (standing.win * 2 + standing.draw) / ((standing.win + standing.draw + standing.lose) * 2),
                2,
            ),
        )

    for user_id, days_dict_roles in cache.items():
        for role, days_dict in days_dict_roles.items():
            user = user_cache[user_id]
            if user_id not in user_pydantic_cache:
                user_pydantic_cache[user_id] = await user_flows.to_pydantic(session, user, [])
            days = days_dict.values()
            avg_win_rate = sum(day.win_rate for day in days) / len(days)
            last_day = days_dict[max(days_dict.keys())]
            standings_output.append(
                schemas.OwalStanding(
                    user=user_pydantic_cache[user_id],
                    role=role,
                    division=last_day.division,
                    days=days_dict,
                    count_days=len(days),
                    place=0,
                    best_3_days=sum(day.points for day in sorted(days, key=lambda x: x.points, reverse=True)[:3]),
                    avg_points=sum(day.points for day in days) / len(days),
                    wins=sum(day.wins for day in days),
                    draws=sum(day.draws for day in days),
                    losses=sum(day.losses for day in days),
                    win_rate=round(avg_win_rate, 2),
                )
            )

    standings_output.sort(key=lambda x: x.best_3_days, reverse=True)
    rank = 1
    for _key, group in groupby(standings_output, key=lambda x: x.best_3_days):
        group_list = list(group)
        for standing in group_list:
            standing.place = rank
        rank += len(group_list)

    return schemas.OwalStandings(
        days=[await to_pydantic(session, day, []) for day in days_tournament],
        standings=standings_output,
    )


async def get_owal_seasons(session: AsyncSession, workspace_id: int | None = None) -> list[str]:
    return await service.get_owal_seasons(session, workspace_id=workspace_id)


async def get_league_player_stacks(
    session: AsyncSession,
    season: str,
    workspace_id: int | None = None,
) -> list[schemas.LeaguePlayerStack]:
    stacks, team_tournament_players, standings_dict = await service.get_league_player_stacks(
        session,
        season,
        workspace_id=workspace_id,
    )

    user_pydantic_cache: dict[int, schemas.UserRead] = {}

    async def get_user_read(user: models.User) -> schemas.UserRead:
        if user.id not in user_pydantic_cache:
            user_pydantic_cache[user.id] = await user_flows.to_pydantic(session, user, [])
        return user_pydantic_cache[user.id]

    stack_results = []
    for (player1_id, player2_id), team_tournaments in stacks.items():
        positions = []
        for team_id, tournament_id in team_tournaments:
            standing = standings_dict.get((team_id, tournament_id))
            if standing and standing.overall_position:
                positions.append(standing.overall_position)

        if positions and len(team_tournaments) > 1:
            avg_position = statistics.mean(positions)
            games_together = len(team_tournaments)

            player1, player2 = None, None
            for players in team_tournament_players.values():
                for p in players:
                    # Player.user_id was dropped in the contract step (iwrefac07); the
                    # identity anchor is workspace_member.player_id instead.
                    if p.workspace_member.player_id == player1_id:
                        player1 = p
                    elif p.workspace_member.player_id == player2_id:
                        player2 = p
                    if player1 and player2:
                        break
                if player1 and player2:
                    break

            if player1 is None or player2 is None:
                continue

            player1_value = typing.cast(models.Player, player1)
            player2_value = typing.cast(models.Player, player2)

            stack_results.append(
                schemas.LeaguePlayerStack(
                    user_1=await get_user_read(player1_value.workspace_member.player),
                    user_2=await get_user_read(player2_value.workspace_member.player),
                    games=games_together,
                    avg_position=round(avg_position, 2),
                )
            )

    stack_results.sort(key=lambda x: x.avg_position)

    return stack_results
