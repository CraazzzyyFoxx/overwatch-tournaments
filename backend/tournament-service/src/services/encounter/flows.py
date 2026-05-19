from shared.services.stage_refs import resolve_stage_refs_from_group
from sqlalchemy.ext.asyncio import AsyncSession

from src import models, schemas
from src.core import enums, errors, pagination, utils
from src.services.map import flows as map_flows
from src.services.team import flows as team_flows
from src.services.tournament import flows as tournament_flows
from src.services.user import flows as user_flows

from . import service


async def to_pydantic(session: AsyncSession, encounter: models.Encounter, entities: list[str]) -> schemas.EncounterRead:
    """
    Converts an Encounter model instance to a Pydantic schema (EncounterRead), including related entities.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        encounter (models.Encounter): The Encounter model instance to convert.
        entities (list[str]): A list of related entities to include (e.g., ["tournament", "teams"]).

    Returns:
        schemas.EncounterRead: The Pydantic schema representing the encounter.
    """
    stage: schemas.StageSummaryRead | None = None
    stage_item: schemas.StageItemSummaryRead | None = None
    tournament: schemas.TournamentRead | None = None
    home_team: schemas.TeamRead | None = None
    away_team: schemas.TeamRead | None = None
    matches_read: list[schemas.MatchRead] = []

    # Self-heal для legacy-encounters: если stage_id/stage_item_id NULL, но есть
    # tournament_group_id — резолвим из TournamentGroup.stage_id. Страхует
    # публичную сетку от ситуаций, когда backfill-миграция ещё не применена.
    # ВАЖНО: используем локальные значения, НЕ мутируем encounter (не хочется
    # приводить к implicit write-back в session).
    effective_stage_id = encounter.stage_id
    effective_stage_item_id = encounter.stage_item_id
    if effective_stage_id is None and encounter.tournament_group_id is not None:
        refs = await resolve_stage_refs_from_group(
            session,
            tournament_id=encounter.tournament_id,
            tournament_group_id=encounter.tournament_group_id,
        )
        effective_stage_id = refs.stage_id
        effective_stage_item_id = refs.stage_item_id

    if "stage" in entities and encounter.stage is not None:
        stage = schemas.StageSummaryRead.model_validate(encounter.stage, from_attributes=True)
    if "stage_item" in entities and encounter.stage_item is not None:
        stage_item = schemas.StageItemSummaryRead.model_validate(encounter.stage_item, from_attributes=True)
    if "tournament" in entities:
        tournament = await tournament_flows.to_pydantic(
            session,
            encounter.tournament,
            utils.prepare_entities(entities, "tournament"),
        )
    if "teams" in entities or "home_team" in entities:
        teams_entities = (
            utils.prepare_entities(entities, "teams")
            if "teams" in entities
            else utils.prepare_entities(entities, "home_team")
        )
        if encounter.home_team is not None:
            home_team = await team_flows.to_pydantic(session, encounter.home_team, teams_entities)
    if "teams" in entities or "away_team" in entities:
        teams_entities = (
            utils.prepare_entities(entities, "teams")
            if "teams" in entities
            else utils.prepare_entities(entities, "away_team")
        )
        if encounter.away_team is not None:
            away_team = await team_flows.to_pydantic(session, encounter.away_team, teams_entities)
    if "matches" in entities:
        matches_read = [
            await to_pydantic_match(session, match, utils.prepare_entities(entities, "matches"))
            for match in encounter.matches
        ]

    encounter_dict = encounter.to_dict()
    # Override with resolved refs, because schema source of truth for public API
    # is the effective (stage_id, stage_item_id) pair even if DB still has NULL.
    encounter_dict["stage_id"] = effective_stage_id
    encounter_dict["stage_item_id"] = effective_stage_item_id

    return schemas.EncounterRead(
        **encounter_dict,
        score=schemas.Score(home=encounter.home_score, away=encounter.away_score),
        stage=stage,
        stage_item=stage_item,
        tournament=tournament,
        home_team=home_team,
        away_team=away_team,
        matches=matches_read,
    )


def to_summary(encounter: models.Encounter) -> schemas.EncounterSummaryRead:
    return schemas.EncounterSummaryRead(
        **encounter.to_dict(),
        score=schemas.Score(home=encounter.home_score, away=encounter.away_score),
    )


async def to_pydantic_match(session: AsyncSession, match: models.Match, entities: list[str]) -> schemas.MatchRead:
    """
    Converts a Match model instance to a Pydantic schema (MatchRead), including related entities.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        match (models.Match): The Match model instance to convert.
        entities (list[str]): A list of related entities to include (e.g., ["teams", "map"]).

    Returns:
        schemas.MatchRead: The Pydantic schema representing the match.
    """
    home_team: schemas.TeamRead | None = None
    away_team: schemas.TeamRead | None = None
    encounter: schemas.EncounterRead | None = None
    map_read: schemas.MapRead | None = None

    if "teams" in entities or "home_team" in entities:
        teams_entities = (
            utils.prepare_entities(entities, "teams")
            if "teams" in entities
            else utils.prepare_entities(entities, "home_team")
        )
        if match.home_team is not None:
            home_team = await team_flows.to_pydantic(session, match.home_team, teams_entities)
    if "teams" in entities or "away_team" in entities:
        teams_entities = (
            utils.prepare_entities(entities, "teams")
            if "teams" in entities
            else utils.prepare_entities(entities, "away_team")
        )
        if match.away_team is not None:
            away_team = await team_flows.to_pydantic(session, match.away_team, teams_entities)
    if "encounter" in entities:
        encounter = await to_pydantic(session, match.encounter, utils.prepare_entities(entities, "encounter"))
    if "map" in entities:
        map_read = await map_flows.to_pydantic(session, match.map, utils.prepare_entities(entities, "map"))

    return schemas.MatchRead(
        **match.to_dict(),
        score=schemas.Score(home=match.home_score, away=match.away_score),
        home_team=home_team,
        away_team=away_team,
        encounter=encounter,
        map=map_read,
    )


async def get_encounter(session: AsyncSession, encounter_id: int, entities: list[str]) -> schemas.EncounterRead:
    """
    Retrieves an encounter by its ID and converts it to a Pydantic schema.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        encounter_id (int): The ID of the encounter to retrieve.
        entities (list[str]): A list of related entities to include (e.g., ["tournament", "teams"]).

    Returns:
        schemas.EncounterRead: The Pydantic schema representing the encounter.

    Raises:
        errors.ApiHTTPException: If the encounter is not found.
    """
    encounter = await service.get_encounter(session, encounter_id, entities)
    if not encounter:
        raise errors.ApiHTTPException(
            status_code=404,
            detail=[errors.ApiExc(code="not_found", msg=f"Encounter with id {encounter_id} not found")],
        )
    return await to_pydantic(session, encounter, entities)


async def get_all_encounters(
    session: AsyncSession,
    params: schemas.EncounterSearchParams,
    workspace_id: int | None = None,
    viewer_auth_user_id: int | None = None,
) -> pagination.Paginated[schemas.EncounterRead]:
    """
    Retrieves a paginated list of encounters and converts them to Pydantic schemas.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        params (schemas.EncounterSearchParams): Search, pagination, and sorting parameters.
        workspace_id (int | None): Optional workspace ID to filter encounters.

    Returns:
        pagination.Paginated[schemas.EncounterRead]: A paginated list of Pydantic schemas representing the encounters.
    """
    encounters, total = await service.get_all_encounters(
        session,
        params,
        workspace_id=workspace_id,
        viewer_auth_user_id=viewer_auth_user_id,
    )
    return pagination.Paginated(
        total=total,
        per_page=params.per_page,
        page=params.page,
        results=[await to_pydantic(session, encounter, params.entities) for encounter in encounters],
    )


def _saved_view_to_read(saved_view: models.EncounterSavedView) -> schemas.EncounterSavedViewRead:
    return schemas.EncounterSavedViewRead(
        id=saved_view.id,
        workspace_id=saved_view.workspace_id,
        name=saved_view.name,
        filters=schemas.EncounterFiltersRead.model_validate(saved_view.filters_json or {}),
        sort_order=saved_view.sort_order,
    )


async def get_saved_views(
    session: AsyncSession,
    *,
    workspace_id: int,
    auth_user_id: int,
) -> list[schemas.EncounterSavedViewRead]:
    views = await service.get_saved_views(session, workspace_id=workspace_id, auth_user_id=auth_user_id)
    return [_saved_view_to_read(view) for view in views]


async def save_view(
    session: AsyncSession,
    *,
    workspace_id: int,
    auth_user_id: int,
    data: schemas.EncounterSavedViewCreate,
) -> schemas.EncounterSavedViewRead:
    saved_view = await service.upsert_saved_view(
        session,
        workspace_id=workspace_id,
        auth_user_id=auth_user_id,
        name=data.name,
        filters=data.filters.model_dump(exclude_none=True),
    )
    return _saved_view_to_read(saved_view)


async def delete_saved_view(
    session: AsyncSession,
    *,
    workspace_id: int,
    auth_user_id: int,
    saved_view_id: int,
) -> None:
    await service.delete_saved_view(
        session,
        workspace_id=workspace_id,
        auth_user_id=auth_user_id,
        saved_view_id=saved_view_id,
    )


async def get_encounters_overview(
    session: AsyncSession,
    params: schemas.EncounterSearchParams,
    workspace_id: int | None = None,
    viewer_auth_user_id: int | None = None,
) -> schemas.EncounterOverviewRead:
    data = await service.get_overview_data(
        session,
        params,
        workspace_id=workspace_id,
        viewer_auth_user_id=viewer_auth_user_id,
    )
    total = data["total"]
    with_logs_count = data["with_logs_count"]
    completed_series_count = data["completed_series_count"]
    sweep_count = data["sweep_count"]
    home_wins = data["home_wins"]
    away_wins = data["away_wins"]
    decided_count = home_wins + away_wins

    histogram_by_bucket = {int(bucket): int(count) for bucket, count in data["histogram_rows"] if bucket is not None}
    histogram = [
        schemas.EncounterHistogramBucketRead(
            label=f"{index * 10}-{(index + 1) * 10}%",
            start=index / 10,
            end=(index + 1) / 10,
            count=histogram_by_bucket.get(index, 0),
        )
        for index in range(10)
    ]

    return schemas.EncounterOverviewRead(
        kpis=schemas.EncounterKpiRead(
            total_encounters=total,
            recent_count=data["recent_count"],
            with_logs_count=with_logs_count,
            with_logs_pct=round((with_logs_count / total) * 100, 1) if total else 0,
            avg_closeness=round(data["avg_closeness"] * 100, 1) if data["avg_closeness"] is not None else None,
            live_now_count=data["live_now_count"],
            upcoming_count=data["upcoming_count"],
        ),
        preset_counts=data["preset_counts"],
        closeness_histogram=histogram,
        score_heatmap=[
            schemas.EncounterScoreHeatmapCellRead(home=int(home), away=int(away), count=int(count))
            for home, away, count in data["score_rows"]
        ],
        stage_split=[
            schemas.EncounterStageSplitRead(
                name=str(name),
                count=int(count),
                pct=round((int(count) / total) * 100, 1) if total else 0,
            )
            for name, count in data["stage_rows"]
        ],
        featured=schemas.EncounterFeaturedRead(
            closest=[
                await to_pydantic(
                    session,
                    encounter,
                    ["tournament", "stage", "stage_item", "home_team", "away_team", "matches", "matches.map"],
                )
                for encounter in data["closest"]
            ],
            upcoming=[
                await to_pydantic(
                    session,
                    encounter,
                    ["tournament", "stage", "stage_item", "home_team", "away_team", "matches", "matches.map"],
                )
                for encounter in data["upcoming"]
            ],
            live=[
                await to_pydantic(
                    session,
                    encounter,
                    ["tournament", "stage", "stage_item", "home_team", "away_team", "matches", "matches.map"],
                )
                for encounter in data["live"]
            ],
        ),
        hot_maps=[
            schemas.EncounterMapMetricRead(name=str(name), count=int(count))
            for name, count in data["hot_map_rows"]
        ],
        pulse=schemas.EncounterPulseRead(
            avg_series_seconds=data["avg_series_seconds"],
            completed_series_count=completed_series_count,
            sweep_rate=round((sweep_count / completed_series_count) * 100, 1) if completed_series_count else 0,
            sweep_count=sweep_count,
            went_distance_count=data["went_distance_count"],
            reverse_sweep_rate=0,
            most_decisive_map=str(data["hot_map_rows"][0][0]) if data["hot_map_rows"] else None,
        ),
        side_balance=schemas.EncounterSideBalanceRead(
            home_wins=home_wins,
            away_wins=away_wins,
            home_win_pct=round((home_wins / decided_count) * 100, 1) if decided_count else 0,
            away_win_pct=round((away_wins / decided_count) * 100, 1) if decided_count else 0,
        ),
    )


async def get_all_matches(
    session: AsyncSession, params: schemas.MatchSearchParams, workspace_id: int | None = None
) -> pagination.Paginated[schemas.MatchRead]:
    """
    Retrieves a paginated list of matches and converts them to Pydantic schemas.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        params (schemas.MatchSearchParams): Search, pagination, and sorting parameters.
        workspace_id (int | None): Optional workspace ID to filter matches by workspace.

    Returns:
        pagination.Paginated[schemas.MatchRead]: A paginated list of Pydantic schemas representing the matches.
    """
    matches, total = await service.get_all_matches(session, params, workspace_id=workspace_id)
    return pagination.Paginated(
        total=total,
        per_page=params.per_page,
        page=params.page,
        results=[await to_pydantic_match(session, match, params.entities) for match in matches],
    )


def create_team_with_match_stats(
    team: schemas.TeamRead,
    team_stats: dict[int, tuple[dict[int, dict[enums.LogStatsName, int]], dict[int, list[dict]]]],
) -> schemas.TeamWithMatchStats:
    """
    Creates a TeamWithMatchStats schema from a TeamRead schema and a dictionary of team statistics.

    Parameters:
        team (schemas.TeamRead): The team data.
        team_stats (dict[int, tuple[dict[int, dict[enums.LogStatsName, int]], dict[int, list[dict]]]]):
            A dictionary where the key is the player user ID and the value is a tuple containing:
                - A dictionary of round numbers to dictionaries of log stats names and their values.
                - A dictionary of round numbers to lists of hero statistics.

    Returns:
        schemas.TeamWithMatchStats: The team data with match statistics included.
    """
    return schemas.TeamWithMatchStats(
        **team.model_dump(exclude={"players"}),
        players=[
            schemas.PlayerWithMatchStats(
                **player.model_dump(),
                stats=team_stats[player.user_id][0],
                heroes=team_stats[player.user_id][1],  # type: ignore
            )
            for player in team.players
            if team_stats[player.user_id][1]
        ],
    )


async def get_match(session: AsyncSession, match_id: int, entities: list[str]) -> schemas.MatchRead:
    """
    Retrieves a match by its ID and converts it to a Pydantic schema.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        match_id (int): The ID of the match to retrieve.
        entities (list[str]): A list of related entities to include (e.g., ["teams", "map"]).

    Returns:
        schemas.MatchRead: The Pydantic schema representing the match.

    Raises:
        errors.ApiHTTPException: If the match is not found.
    """
    match = await service.get_match(session, match_id, entities)
    if not match:
        raise errors.ApiHTTPException(
            status_code=404,
            detail=[errors.ApiExc(code="not_found", msg=f"Match with id {match_id} not found")],
        )
    return await to_pydantic_match(session, match, entities)


async def get_match_with_stats(session: AsyncSession, match_id: int, entities: list[str]) -> schemas.MatchReadWithStats:
    """
    Retrieves a match by its ID and converts it to a Pydantic schema with detailed statistics.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        match_id (int): The ID of the match to retrieve.
        entities (list[str]): A list of related entities to include (e.g., ["teams", "map"]).

    Returns:
        schemas.MatchReadWithStats: The Pydantic schema representing the match with detailed statistics.

    Raises:
        errors.ApiHTTPException: If the match is not found.
    """
    if "teams" not in entities:
        entities.append("teams")
    if "teams.players" not in entities:
        entities.append("teams.players")
    match = await get_match(session, match_id, entities)
    max_round: int = 0
    home_team_stats: dict[int, tuple[dict[int, dict[enums.LogStatsName, int]], dict[int, list[dict]]]] = {}
    away_team_stats: dict[int, tuple[dict[int, dict[enums.LogStatsName, int]], dict[int, list[dict]]]] = {}
    for player in match.home_team.players:
        player_data = await service.get_match_stats_for_user(session, match.id, player.user_id)
        home_team_stats[player.user_id] = player_data
        max_round = max(max_round, max(player_data[0].keys()) if player_data[0] else 0)
    for player in match.away_team.players:
        player_data = await service.get_match_stats_for_user(session, match.id, player.user_id)
        away_team_stats[player.user_id] = player_data
        max_round = max(max_round, max(player_data[0].keys()) if player_data[0] else 0)

    home_team = create_team_with_match_stats(match.home_team, home_team_stats)
    away_team = create_team_with_match_stats(match.away_team, away_team_stats)
    return schemas.MatchReadWithStats(
        **match.model_dump(exclude={"home_team", "away_team"}),
        rounds=max_round,
        home_team=home_team,
        away_team=away_team,
    )


async def get_encounters_by_user(
    session: AsyncSession, user_id: int, params: pagination.PaginationSortParams, workspace_id: int | None = None
) -> pagination.Paginated[schemas.EncounterReadWithUserStats]:
    """
    Retrieves a paginated list of encounters involving a specific user, including user statistics.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        user_id (int): The ID of the user.
        params (pagination.PaginationSortParams): Pagination and sorting parameters.

    Returns:
        pagination.Paginated[schemas.EncounterReadWithUserStats]: A paginated list of Pydantic schemas representing the encounters with user statistics.
    """
    match_entities = utils.prepare_entities(params.entities, "matches")

    if "teams" in params.entities:
        match_entities = utils.remove_from_entities(match_entities, "teams")

    if "matches" in params.entities:
        match_entities.extend(utils.find_entities(params.entities, "matches"))
        params.entities = utils.remove_from_entities(params.entities, "matches")

    params.entities = [*match_entities, *params.entities]

    user = await user_flows.get(session, user_id, [])
    encounters, total = await service.get_by_user(session, user.id, params, workspace_id=workspace_id)
    encounters_read: list[schemas.EncounterReadWithUserStats] = []
    encounters_cache: dict[int, models.Encounter] = {}
    matches_cache: dict[int, list[schemas.MatchReadWithUserStats]] = {}

    for encounter, match, performance, heroes in encounters:
        encounters_cache.setdefault(encounter.id, encounter)
        matches_cache.setdefault(encounter.id, [])

        if match:
            match_read_ = await to_pydantic_match(session, match, match_entities)
            match_read = schemas.MatchReadWithUserStats(
                **match_read_.model_dump(),
                performance=performance,
                heroes=heroes if heroes else [],  # type: ignore
            )
            matches_cache[encounter.id].append(match_read)

    for encounter_id, encounter in encounters_cache.items():
        encounter_read_ = await to_pydantic(session, encounter, params.entities)
        encounter_read = schemas.EncounterReadWithUserStats(
            **encounter_read_.model_dump(exclude={"matches"}),
            matches=matches_cache.get(encounter_id, []),
        )
        encounters_read.append(encounter_read)

    return pagination.Paginated(
        total=total,
        per_page=params.per_page,
        page=params.page,
        results=encounters_read,
    )


async def get_encounters_by_team(
    session: AsyncSession, team_id: int, entities: list[str]
) -> list[schemas.EncounterRead]:
    """
    Retrieves all encounters involving a specific team and converts them to Pydantic schemas.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        team_id (int): The ID of the team.
        entities (list[str]): A list of related entities to include (e.g., ["tournament", "teams"]).

    Returns:
        list[schemas.EncounterRead]: A list of Pydantic schemas representing the encounters.
    """
    encounters = await service.get_by_team(session, team_id, entities)
    return [await to_pydantic(session, encounter, entities) for encounter in encounters]


async def get_encounters_by_team_group(
    session: AsyncSession, team_id: int, group_id: int, entities: list[str]
) -> list[schemas.EncounterRead]:
    """
    Retrieves all encounters involving a specific team within a specific tournament group and converts them to Pydantic schemas.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        team_id (int): The ID of the team.
        group_id (int): The ID of the tournament group.
        entities (list[str]): A list of related entities to include (e.g., ["tournament", "teams"]).

    Returns:
        list[schemas.EncounterRead]: A list of Pydantic schemas representing the encounters.
    """
    encounters = await service.get_by_team_group(session, team_id, group_id, entities)
    return [await to_pydantic(session, encounter, entities) for encounter in encounters]
