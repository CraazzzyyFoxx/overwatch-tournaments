import typing

import sqlalchemy as sa
from cashews import cache
from shared.services.stage_refs import StageRefs, resolve_stage_refs_from_group
from sqlalchemy.ext.asyncio import AsyncSession

from src import models, schemas
from src.core import config, enums, errors, pagination, utils
from src.services.map import flows as map_flows
from src.services.team import flows as team_flows
from src.services.tournament import flows as tournament_flows

from . import service


async def _prefetch_stage_refs(
    session: AsyncSession,
    encounters: typing.Sequence[models.Encounter],
) -> dict[tuple[int, int], StageRefs]:
    """Batch counterpart of ``resolve_stage_refs_from_group`` for list pages.

    ``to_pydantic`` self-heals legacy encounters (``stage_id`` NULL but
    ``tournament_group_id`` set) via ``resolve_stage_refs_from_group``, which
    fires queries PER encounter. List endpoints instead resolve every distinct
    ``(tournament_id, tournament_group_id)`` pair up-front here (a constant
    number of queries per page) and pass the mapping into ``to_pydantic``.

    Replicates the resolution order of ``resolve_stage_refs_from_group`` for
    the ``stage_id is None`` path exactly: group.stage_id with a stage item
    name-matched to the group name (else the first item by order/id), falling
    back to the tournament's first stage and its first item.
    """
    pairs = {
        (encounter.tournament_id, encounter.tournament_group_id)
        for encounter in encounters
        if encounter.stage_id is None and encounter.tournament_group_id is not None
    }
    if not pairs:
        return {}

    groups_result = await session.execute(
        sa.select(models.TournamentGroup).where(models.TournamentGroup.id.in_({group_id for _, group_id in pairs}))
    )
    groups_by_id = {group.id: group for group in groups_result.scalars().all()}

    # Case-4 fallback tournaments: group is missing or has no stage_id.
    fallback_tournament_ids = {
        tournament_id
        for tournament_id, group_id in pairs
        if group_id not in groups_by_id or groups_by_id[group_id].stage_id is None
    }
    first_stage_by_tournament: dict[int, int] = {}
    if fallback_tournament_ids:
        stage_rows = await session.execute(
            sa.select(models.Stage.tournament_id, models.Stage.id)
            .where(models.Stage.tournament_id.in_(fallback_tournament_ids))
            .order_by(models.Stage.tournament_id, models.Stage.order.asc(), models.Stage.id.asc())
        )
        for tournament_id, stage_id in stage_rows.all():
            first_stage_by_tournament.setdefault(tournament_id, stage_id)

    stage_ids = {group.stage_id for group in groups_by_id.values() if group.stage_id is not None}
    stage_ids.update(first_stage_by_tournament.values())
    items_by_stage: dict[int, list[models.StageItem]] = {}
    if stage_ids:
        items_result = await session.execute(
            sa.select(models.StageItem)
            .where(models.StageItem.stage_id.in_(stage_ids))
            .order_by(models.StageItem.order.asc(), models.StageItem.id.asc())
        )
        for item in items_result.scalars().all():
            items_by_stage.setdefault(item.stage_id, []).append(item)

    def pick_default_item(stage_id: int, hint_name: str | None = None) -> int | None:
        items = items_by_stage.get(stage_id)
        if not items:
            return None
        if hint_name:
            normalized = hint_name.strip().lower()
            for item in items:
                if item.name.strip().lower() == normalized:
                    return item.id
        return items[0].id

    refs_by_pair: dict[tuple[int, int], StageRefs] = {}
    for tournament_id, group_id in pairs:
        group = groups_by_id.get(group_id)
        if group is not None and group.stage_id is not None:
            refs_by_pair[(tournament_id, group_id)] = StageRefs(
                stage_id=group.stage_id,
                stage_item_id=pick_default_item(group.stage_id, hint_name=group.name),
                tournament_group_id=group_id,
            )
            continue
        first_stage_id = first_stage_by_tournament.get(tournament_id)
        refs_by_pair[(tournament_id, group_id)] = StageRefs(
            stage_id=first_stage_id,
            stage_item_id=pick_default_item(first_stage_id) if first_stage_id is not None else None,
            tournament_group_id=group_id,
        )
    return refs_by_pair


async def to_pydantic(
    session: AsyncSession,
    encounter: models.Encounter,
    entities: list[str],
    *,
    prefetched_stage_refs: typing.Mapping[tuple[int, int], StageRefs] | None = None,
) -> schemas.EncounterRead:
    """
    Converts an Encounter model instance to a Pydantic schema (EncounterRead), including related entities.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        encounter (models.Encounter): The Encounter model instance to convert.
        entities (list[str]): A list of related entities to include (e.g., ["tournament", "teams"]).
        prefetched_stage_refs: Optional mapping of (tournament_id, tournament_group_id)
            to already-resolved StageRefs (see ``_prefetch_stage_refs``). List call
            sites pass it to avoid a per-encounter resolver query; single-item call
            sites can omit it and fall back to the per-encounter resolver.

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
        refs = (
            prefetched_stage_refs.get((encounter.tournament_id, encounter.tournament_group_id))
            if prefetched_stage_refs is not None
            else None
        )
        if refs is None:
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


@cache(
    ttl=config.settings.encounters_cache_ttl,
    key="encounters:{workspace_id}:{params.tournament_id}:{params.page}:{params.per_page}:{params.sort}:{params.order}:{params.entities}:{params.only_count}:{params.query}:{params.fields}:{params.stage_id}:{params.stage_item_id}:{params.best_of}:{params.status}:{params.has_logs}:{params.closeness_min}:{params.closeness_max}:{params.scope}:{viewer_auth_user_id}",
    prefix="fastapi:",
)
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
    prefetched_stage_refs = await _prefetch_stage_refs(session, encounters)
    return pagination.Paginated(
        total=total,
        per_page=params.per_page,
        page=params.page,
        results=[
            await to_pydantic(session, encounter, params.entities, prefetched_stage_refs=prefetched_stage_refs)
            for encounter in encounters
        ],
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


@cache(
    ttl=config.settings.encounters_cache_ttl,
    key="encounters_overview:{workspace_id}:{params.tournament_id}:{params.page}:{params.per_page}:{params.sort}:{params.order}:{params.entities}:{params.only_count}:{params.query}:{params.fields}:{params.stage_id}:{params.stage_item_id}:{params.best_of}:{params.status}:{params.has_logs}:{params.closeness_min}:{params.closeness_max}:{params.scope}:{viewer_auth_user_id}",
    prefix="fastapi:",
    # NB: no ``lock=True`` — cashews builds the herd-lock key WITHOUT the
    # ``prefix``, and this codebase routes backends purely by key prefix (no
    # default backend), so the lock raises NotConfiguredError (same bug class
    # as lesson_cashews_prefixless_delete_match). TTL rollover herds are
    # mitigated by the FILTER-consolidated aggregate query instead.
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

    # One batched stage-ref resolution for all featured blocks instead of a
    # per-encounter resolver query inside to_pydantic (legacy encounters with
    # only tournament_group_id set).
    featured_stage_refs = await _prefetch_stage_refs(
        session,
        [*data["closest"], *data["upcoming"], *data["live"]],
    )

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
                    prefetched_stage_refs=featured_stage_refs,
                )
                for encounter in data["closest"]
            ],
            upcoming=[
                await to_pydantic(
                    session,
                    encounter,
                    ["tournament", "stage", "stage_item", "home_team", "away_team", "matches", "matches.map"],
                    prefetched_stage_refs=featured_stage_refs,
                )
                for encounter in data["upcoming"]
            ],
            live=[
                await to_pydantic(
                    session,
                    encounter,
                    ["tournament", "stage", "stage_item", "home_team", "away_team", "matches", "matches.map"],
                    prefetched_stage_refs=featured_stage_refs,
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


async def get_match(
    session: AsyncSession,
    match_id: int,
    entities: list[str],
    workspace_id: int | None = None,
) -> schemas.MatchRead:
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
    match = await service.get_match(session, match_id, entities, workspace_id=workspace_id)
    if not match:
        raise errors.ApiHTTPException(
            status_code=404,
            detail=[errors.ApiExc(code="not_found", msg=f"Match with id {match_id} not found")],
        )
    return await to_pydantic_match(session, match, entities)


@cache(
    ttl=config.settings.match_cache_ttl,
    # No tournament_id in the args, so this key can't participate in the
    # targeted invalidation patterns — staleness is bounded by the short TTL.
    key="match_stats:{match_id}:{entities}:{workspace_id}",
    prefix="fastapi:",
)
async def get_match_with_stats(
    session: AsyncSession,
    match_id: int,
    entities: list[str],
    workspace_id: int | None = None,
) -> schemas.MatchReadWithStats:
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
    match = await get_match(session, match_id, entities, workspace_id=workspace_id)
    max_round: int = 0
    home_ids = [player.user_id for player in match.home_team.players]
    away_ids = [player.user_id for player in match.away_team.players]
    # One batched pair of aggregate queries for the whole roster instead of
    # 2 queries per player (this is the hottest public read — the match page).
    all_stats = await service.get_match_stats_for_users(session, match.id, [*home_ids, *away_ids])
    home_team_stats: dict[int, tuple[dict[int, dict[enums.LogStatsName, int]], dict[int, list[dict]]]] = {}
    away_team_stats: dict[int, tuple[dict[int, dict[enums.LogStatsName, int]], dict[int, list[dict]]]] = {}
    for user_id in home_ids:
        player_data = all_stats[user_id]
        home_team_stats[user_id] = player_data
        max_round = max(max_round, max(player_data[0].keys()) if player_data[0] else 0)
    for user_id in away_ids:
        player_data = all_stats[user_id]
        away_team_stats[user_id] = player_data
        max_round = max(max_round, max(player_data[0].keys()) if player_data[0] else 0)

    home_team = create_team_with_match_stats(match.home_team, home_team_stats)
    away_team = create_team_with_match_stats(match.away_team, away_team_stats)
    return schemas.MatchReadWithStats(
        **match.model_dump(exclude={"home_team", "away_team"}),
        rounds=max_round,
        home_team=home_team,
        away_team=away_team,
    )
