import re
from dataclasses import dataclass

import sqlalchemy as sa
from loguru import logger
from shared.division_grid import DEFAULT_GRID
from shared.services.division_grid_resolution import resolve_tournament_division
from sqlalchemy.ext.asyncio import AsyncSession

from src import models, schemas
from src.core import enums, errors, utils
from src.services.challonge import service as challonge_service
from src.services.tournament import flows as tournament_flows
from src.services.user import flows as user_flows

from . import service


def resolve_team_placement(team: models.Team) -> int | None:
    standings = getattr(team, "standings", None) or []
    positive_positions = [
        standing.overall_position
        for standing in standings
        if getattr(standing, "overall_position", 0) > 0
    ]
    if positive_positions:
        return min(positive_positions)
    return None


def resolve_hero_role_from_balancer(role: str) -> enums.HeroClass | None:
    if role is None:
        return None

    if role.lower() == "tank":
        return enums.HeroClass.tank
    if role.lower() == "dps":
        return enums.HeroClass.damage
    if role.lower() == "support":
        return enums.HeroClass.support
    raise errors.ApiHTTPException(
        status_code=400,
        detail=[errors.ApiExc(code="invalid_hero_role", msg=f"{role} is not a valid hero role.")],
    )


async def to_pydantic(
    session: AsyncSession,
    team: models.Team,
    entities: list[str],
) -> schemas.TeamRead:
    tournament: schemas.TournamentRead | None = None
    players_read: list[schemas.PlayerRead] = []
    captain: schemas.UserRead | None = None
    placement: int | None = None

    if "tournament" in entities and team.tournament is not None:
        tournament = await tournament_flows.to_pydantic(session, team.tournament, [])
    if "players" in entities:
        players_entities = utils.prepare_entities(entities, "players")
        players_read = [
            await to_pydantic_player(session, player, players_entities)
            for player in team.players
        ]
    if "captain" in entities and team.captain is not None:
        captain = await user_flows.to_pydantic(
            session, team.captain, utils.prepare_entities(entities, "captain")
        )
    if "placement" in entities:
        placement = resolve_team_placement(team)

    return schemas.TeamRead(
        id=team.id,
        name=team.name,
        avg_sr=team.avg_sr,
        total_sr=team.total_sr,
        tournament_id=team.tournament_id,
        captain_id=team.captain_id,
        tournament=tournament,
        players=players_read,
        captain=captain,
        placement=placement,
    )


async def to_pydantic_player(
    session: AsyncSession,
    player: models.Player,
    entities: list[str],
) -> schemas.PlayerRead:
    user: schemas.UserRead | None = None
    tournament: schemas.TournamentRead | None = None
    team: schemas.TeamRead | None = None

    if "user" in entities and player.user is not None:
        user = await user_flows.to_pydantic(
            session, player.user, utils.prepare_entities(entities, "user")
        )
    if "tournament" in entities and player.tournament is not None:
        tournament = await tournament_flows.to_pydantic(
            session, player.tournament, []
        )
    if "team" in entities and player.team is not None:
        team = await to_pydantic(session, player.team, [])

    division = getattr(player, "division", None)
    if division is None:
        division = resolve_tournament_division(
            player.rank,
            fallback_grid=DEFAULT_GRID,
        )

    return schemas.PlayerRead(
        **player.to_dict(),
        division=division,
        tournament=tournament,
        team=team,
        user=user,
    )



async def get(session: AsyncSession, id: int, entities: list[str]) -> models.Team:
    team = await service.get(session, id, entities)
    if not team:
        raise errors.ApiHTTPException(
            status_code=404,
            detail=[errors.ApiExc(code="not_found", msg="Team with id {id} not found.")],
        )
    return team


async def get_by_name_and_tournament(
    session: AsyncSession, tournament_id: int, name: str, entities: list[str]
) -> models.Team:
    team = await service.get_by_name_and_tournament(session, tournament_id, name, entities)
    if not team:
        raise errors.ApiHTTPException(
            status_code=404,
            detail=[
                errors.ApiExc(
                    code="not_found",
                    msg=f"Team with name {name} in tournament {tournament_id} not found.",
                )
            ],
        )
    return team


async def get_by_tournament_challonge_id(
    session: AsyncSession, tournament_id: int, challonge_id: int, entities: list[str]
) -> models.Team:
    team = await service.get_by_tournament_challonge_id(session, tournament_id, challonge_id, entities)
    if not team:
        raise errors.ApiHTTPException(
            status_code=404,
            detail=[
                errors.ApiExc(
                    code="not_found",
                    msg=f"Team with challonge_id {challonge_id} in tournament {tournament_id} not found.",
                )
            ],
        )
    return team


async def get_player_by_user_and_tournament(
    session: AsyncSession, user_id: int, tournament_id: int, entities: list[str]
) -> models.Player:
    player = await service.get_player_by_user_and_tournament(session, user_id, tournament_id, entities)
    if not player:
        raise errors.ApiHTTPException(
            status_code=400,
            detail=[
                errors.ApiExc(
                    code="not_found",
                    msg=f"Player with user [id={user_id}] not found in tournament [number={tournament_id}].",
                )
            ],
        )

    return player


async def get_player_by_team_and_user(
    session: AsyncSession, team_id: int, user_id: int, entities: list[str]
) -> models.Player:
    player = await service.get_player_by_team_and_user(session, team_id, user_id, entities)
    if not player:
        raise errors.ApiHTTPException(
            status_code=404,
            detail=[
                errors.ApiExc(
                    code="not_found",
                    msg=f"Player with user [id={user_id}] not found in team [id={team_id}].",
                )
            ],
        )

    return player


async def create_player(
    session: AsyncSession,
    *,
    name: str,
    sub_role: str | None = None,
    rank: int,
    role: enums.HeroClass,
    user: models.User,
    tournament: models.Tournament,
    team: models.Team,
    is_substitution: bool = False,
    related_player_id: int | None = None,
    is_newcomer: bool = False,
    is_newcomer_role: bool = False,
):
    if await service.get_player_by_team_and_user(session, team.id, user.id, []):
        raise errors.ApiHTTPException(
            status_code=400,
            detail=[
                errors.ApiExc(
                    code="player_already_exists",
                    msg=f"Player [id={user.id} name={user.name}] already exists in this tournament [number={tournament.number}].",
                )
            ],
        )
    return await service.create_player(
        session,
        name=name,
        sub_role=sub_role,
        rank=rank,
        role=role,
        user=user,
        tournament=tournament,
        team=team,
        is_substitution=is_substitution,
        related_player_id=related_player_id,
        is_newcomer=is_newcomer,
        is_newcomer_role=is_newcomer_role,
    )


async def create(
    session: AsyncSession,
    *,
    name: str,
    balancer_name: str,
    avg_sr: float,
    total_sr: int,
    tournament: models.Tournament,
    captain: models.User,
) -> models.Team:
    if await service.get_by_name_and_tournament(session, tournament.id, name, []):
        raise errors.ApiHTTPException(
            status_code=400,
            detail=[
                errors.ApiExc(
                    code="already_exists",
                    msg=f"Team with name {name} already exists in tournament "
                    f"[id={tournament.id}, number={tournament.number}].",
                )
            ],
        )

    return await service.create(
        session,
        name=name,
        balancer_name=balancer_name,
        avg_sr=avg_sr,
        total_sr=total_sr,
        tournament=tournament,
        captain=captain,
    )


async def bulk_create_from_balancer(
    session: AsyncSession, tournament_id: int, payload: list[schemas.BalancerTeam]
) -> None:
    tournament = await tournament_flows.get(session, tournament_id, [])
    for team_data in payload:
        try:
            name = team_data.name.split("#")[0]
        except ValueError:
            name = team_data.name

        captain = await user_flows.find_by_battle_tag(session, team_data.name)
        team = await service.get_by_name_and_tournament(session, tournament.id, name, [])
        if not team:
            team = await create(
                session,
                name=name,
                balancer_name=team_data.name,
                avg_sr=team_data.avg_sr,
                total_sr=team_data.total_sr,
                tournament=tournament,
                captain=captain,
            )
        else:
            logger.info(f"Team {name} already exists in tournament {tournament.name}. Skipping...")

        for player in team_data.members:
            logger.info(f"Trying to add player {player.name} to team {team.name} in tournament {tournament.name}")
            user = await user_flows.find_by_battle_tag(session, player.name)
            player_db = await service.get_player_by_user_and_tournament(session, user.id, tournament.id, [])
            if player_db:
                logger.info(
                    f"Player {player.name} already exists in team [name={team.name} tournament={tournament.name}]."
                )
                continue

            is_newcomer = not bool(await service.get_player_by_user(session, user.id, []))
            role = resolve_hero_role_from_balancer(player.role)
            is_newcomer_role = not bool(await service.get_player_by_user_and_role(session, user.id, role, []))

            await create_player(
                session,
                name=player.name,
                sub_role=player.sub_role,
                rank=player.rank,
                role=role,
                user=user,
                tournament=tournament,
                team=team,
                is_newcomer=is_newcomer,
                is_newcomer_role=is_newcomer_role,
            )
            logger.info(f"Player {player.name} added to team {team.name} in tournament {tournament.id}")

    return None


_TEAM_WORD_RE = re.compile(r"\bteam\b", flags=re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class _ChallongeParticipantRow:
    participant_id: int
    challonge_id: int
    source_id: int | None
    group_id: int | None
    group_name: str | None
    challonge_tournament_id: int
    name: str
    active: bool


def normalize_challonge_team_name(name: str) -> str:
    normalized = name.split("#", 1)[0]
    normalized = _TEAM_WORD_RE.sub("", normalized)
    normalized = _WHITESPACE_RE.sub(" ", normalized)
    return normalized.strip().casefold()


def _effective_challonge_id(
    participant: schemas.ChallongeParticipant,
    *,
    is_playoff: bool,
) -> int:
    if is_playoff and participant.group_player_ids:
        return participant.group_player_ids[0]
    return participant.id


def _build_team_suggestion_index(
    teams: list[models.Team],
) -> dict[str, int]:
    candidates: dict[str, set[int]] = {}
    for team in teams:
        for name in {team.name, team.balancer_name}:
            if not name:
                continue
            normalized = normalize_challonge_team_name(name)
            if not normalized:
                continue
            candidates.setdefault(normalized, set()).add(team.id)

    return {
        normalized: next(iter(team_ids))
        for normalized, team_ids in candidates.items()
        if len(team_ids) == 1
    }


def _suggest_team_id(
    participant_name: str,
    team_suggestion_index: dict[str, int],
) -> int | None:
    return team_suggestion_index.get(normalize_challonge_team_name(participant_name))


async def _get_or_create_challonge_source_id(
    session: AsyncSession,
    tournament: models.Tournament,
    *,
    challonge_tournament_id: int,
    slug: str | None,
    group: models.TournamentGroup | None = None,
    create: bool = False,
) -> int | None:
    result = await session.execute(
        sa.select(models.ChallongeSource).where(
            models.ChallongeSource.tournament_id == tournament.id,
            models.ChallongeSource.challonge_tournament_id == challonge_tournament_id,
        )
    )
    source = result.scalar_one_or_none()
    if source is not None or not create:
        return getattr(source, "id", None)

    stage = getattr(group, "stage", None)
    stage_item_id = None
    if stage is not None and getattr(stage, "items", None):
        stage_item_id = sorted(stage.items, key=lambda item: (item.order, item.id))[0].id

    if stage is None and group is None:
        stage = next(
            (
                candidate
                for candidate in getattr(tournament, "stages", []) or []
                if candidate.challonge_id == challonge_tournament_id
            ),
            None,
        )
        if stage is not None and getattr(stage, "items", None):
            stage_item_id = sorted(stage.items, key=lambda item: (item.order, item.id))[0].id

    source = models.ChallongeSource(
        tournament_id=tournament.id,
        stage_id=stage.id if stage is not None else None,
        stage_item_id=stage_item_id,
        challonge_tournament_id=challonge_tournament_id,
        slug=slug,
        source_type=(
            "group"
            if group is not None and group.is_groups
            else "playoff"
            if group is not None
            else "tournament"
        ),
    )
    session.add(source)
    await session.flush()
    return source.id


async def _fetch_challonge_participant_rows(
    session: AsyncSession,
    tournament: models.Tournament,
    *,
    create_sources: bool = False,
) -> list[_ChallongeParticipantRow]:
    rows: list[_ChallongeParticipantRow] = []
    groups = list(tournament.groups or [])

    if tournament.challonge_id:
        source_id = await _get_or_create_challonge_source_id(
            session,
            tournament,
            challonge_tournament_id=tournament.challonge_id,
            slug=tournament.challonge_slug,
            create=create_sources,
        )
        participants = await challonge_service.fetch_participants(tournament.challonge_id)
        if not groups:
            groups = [None]

        for group in groups:
            is_playoff = bool(group is not None and not group.is_groups)
            for participant in participants:
                rows.append(
                    _ChallongeParticipantRow(
                        participant_id=participant.id,
                        challonge_id=_effective_challonge_id(
                            participant,
                            is_playoff=is_playoff,
                        ),
                        source_id=source_id,
                        group_id=getattr(group, "id", None),
                        group_name=getattr(group, "name", None),
                        challonge_tournament_id=tournament.challonge_id,
                        name=participant.name,
                        active=participant.active,
                    )
                )
        return rows

    for group in groups:
        if group.challonge_id is None:
            continue

        source_id = await _get_or_create_challonge_source_id(
            session,
            tournament,
            challonge_tournament_id=group.challonge_id,
            slug=group.challonge_slug,
            group=group,
            create=create_sources,
        )
        participants = await challonge_service.fetch_participants(group.challonge_id)
        is_playoff = not group.is_groups
        for participant in participants:
            rows.append(
                _ChallongeParticipantRow(
                    participant_id=participant.id,
                    challonge_id=_effective_challonge_id(
                        participant,
                        is_playoff=is_playoff,
                    ),
                    source_id=source_id,
                    group_id=group.id,
                    group_name=group.name,
                    challonge_tournament_id=group.challonge_id,
                    name=participant.name,
                    active=participant.active,
                )
            )

    return rows


async def _get_existing_challonge_mappings(
    session: AsyncSession,
    tournament_id: int,
) -> dict[tuple[int | None, int], models.ChallongeTeam]:
    result = await session.execute(
        sa.select(models.ChallongeTeam).where(
            models.ChallongeTeam.tournament_id == tournament_id
        )
    )
    mappings: dict[tuple[int | None, int], models.ChallongeTeam] = {}
    for mapping in result.scalars().all():
        mappings.setdefault((mapping.group_id, mapping.challonge_id), mapping)
    return mappings


async def _get_existing_challonge_participant_mappings(
    session: AsyncSession,
    source_ids: set[int],
) -> dict[tuple[int, int], models.ChallongeParticipantMapping]:
    if not source_ids:
        return {}
    result = await session.execute(
        sa.select(models.ChallongeParticipantMapping).where(
            models.ChallongeParticipantMapping.source_id.in_(source_ids)
        )
    )
    mappings: dict[tuple[int, int], models.ChallongeParticipantMapping] = {}
    for mapping in result.scalars().all():
        mappings.setdefault((mapping.source_id, mapping.challonge_participant_id), mapping)
    return mappings


async def preview_challonge_team_sync(
    session: AsyncSession,
    tournament_id: int,
) -> schemas.ChallongeTeamSyncPreview:
    tournament = await tournament_flows.get(session, tournament_id, ["groups"])
    teams = list(await service.get_by_tournament(session, tournament.id, []))
    participant_rows = await _fetch_challonge_participant_rows(session, tournament)
    existing_mappings = await _get_existing_challonge_mappings(session, tournament.id)
    team_suggestion_index = _build_team_suggestion_index(teams)

    return schemas.ChallongeTeamSyncPreview(
        teams=[
            schemas.ChallongeTeamPreviewTeam(
                id=team.id,
                name=team.name,
                balancer_name=team.balancer_name,
            )
            for team in teams
        ],
        participants=[
            schemas.ChallongeTeamPreviewParticipant(
                participant_id=row.participant_id,
                challonge_id=row.challonge_id,
                group_id=row.group_id,
                group_name=row.group_name,
                challonge_tournament_id=row.challonge_tournament_id,
                name=row.name,
                active=row.active,
                suggested_team_id=_suggest_team_id(row.name, team_suggestion_index),
                mapped_team_id=getattr(
                    existing_mappings.get((row.group_id, row.challonge_id)),
                    "team_id",
                    None,
                ),
            )
            for row in participant_rows
        ],
    )


def _validate_challonge_team_mappings(
    mappings: list[schemas.ChallongeTeamMapping],
    rows_by_request_key: dict[tuple[int, int | None], _ChallongeParticipantRow],
    team_ids: set[int],
) -> list[str]:
    errors_out: list[str] = []
    seen: set[tuple[int, int | None]] = set()

    for mapping in mappings:
        key = (mapping.participant_id, mapping.group_id)
        if key in seen:
            errors_out.append(
                f"Duplicate mapping for participant {mapping.participant_id} "
                f"in group {mapping.group_id}."
            )
            continue
        seen.add(key)

        if key not in rows_by_request_key:
            errors_out.append(
                f"Challonge participant {mapping.participant_id} "
                f"in group {mapping.group_id} was not found."
            )
        if mapping.team_id not in team_ids:
            errors_out.append(
                f"Team {mapping.team_id} does not belong to this tournament."
            )

    return errors_out


async def sync_challonge_team_mappings(
    session: AsyncSession,
    tournament_id: int,
    payload: schemas.ChallongeTeamSyncRequest,
) -> schemas.ChallongeTeamSyncResult:
    tournament = await tournament_flows.get(session, tournament_id, ["groups"])
    logger.info(f"Syncing Challonge team mappings for tournament {tournament.name}")

    teams = list(await service.get_by_tournament(session, tournament.id, []))
    team_ids = {team.id for team in teams}
    participant_rows = await _fetch_challonge_participant_rows(
        session,
        tournament,
        create_sources=True,
    )
    rows_by_request_key = {
        (row.participant_id, row.group_id): row
        for row in participant_rows
    }

    validation_errors = _validate_challonge_team_mappings(
        payload.mappings,
        rows_by_request_key,
        team_ids,
    )
    if validation_errors:
        raise errors.ApiHTTPException(
            status_code=400,
            detail=[
                errors.ApiExc(code="invalid_challonge_mapping", msg=message)
                for message in validation_errors
            ],
        )

    existing_mappings = await _get_existing_challonge_mappings(session, tournament.id)
    existing_source_mappings = await _get_existing_challonge_participant_mappings(
        session,
        {row.source_id for row in participant_rows if row.source_id is not None},
    )
    created = 0
    updated = 0
    unchanged = 0

    for mapping in payload.mappings:
        participant_row = rows_by_request_key[(mapping.participant_id, mapping.group_id)]
        existing_key = (participant_row.group_id, participant_row.challonge_id)
        existing_mapping = existing_mappings.get(existing_key)
        source_mapping = None
        if participant_row.source_id is not None:
            source_mapping = existing_source_mappings.get(
                (participant_row.source_id, participant_row.challonge_id)
            )

        if existing_mapping is None:
            if participant_row.source_id is not None and source_mapping is None:
                source_mapping = models.ChallongeParticipantMapping(
                    source_id=participant_row.source_id,
                    challonge_participant_id=participant_row.challonge_id,
                    team_id=mapping.team_id,
                )
                session.add(source_mapping)
                existing_source_mappings[
                    (participant_row.source_id, participant_row.challonge_id)
                ] = source_mapping
            challonge_team = models.ChallongeTeam(
                challonge_id=participant_row.challonge_id,
                team_id=mapping.team_id,
                group_id=participant_row.group_id,
                tournament_id=tournament.id,
            )
            session.add(challonge_team)
            existing_mappings[existing_key] = challonge_team
            created += 1
            continue

        if existing_mapping.team_id == mapping.team_id:
            if source_mapping is not None and source_mapping.team_id != mapping.team_id:
                source_mapping.team_id = mapping.team_id
                updated += 1
                continue
            if participant_row.source_id is not None and source_mapping is None:
                source_mapping = models.ChallongeParticipantMapping(
                    source_id=participant_row.source_id,
                    challonge_participant_id=participant_row.challonge_id,
                    team_id=mapping.team_id,
                )
                session.add(source_mapping)
                existing_source_mappings[
                    (participant_row.source_id, participant_row.challonge_id)
                ] = source_mapping
                updated += 1
                continue
            unchanged += 1
            continue

        existing_mapping.team_id = mapping.team_id
        if source_mapping is not None:
            source_mapping.team_id = mapping.team_id
        elif participant_row.source_id is not None:
            source_mapping = models.ChallongeParticipantMapping(
                source_id=participant_row.source_id,
                challonge_participant_id=participant_row.challonge_id,
                team_id=mapping.team_id,
            )
            session.add(source_mapping)
            existing_source_mappings[
                (participant_row.source_id, participant_row.challonge_id)
            ] = source_mapping
        updated += 1

    await session.commit()

    mapped_count = len({(mapping.participant_id, mapping.group_id) for mapping in payload.mappings})
    skipped = max(len(rows_by_request_key) - mapped_count, 0)
    return schemas.ChallongeTeamSyncResult(
        success=True,
        count=created + updated + unchanged,
        created=created,
        updated=updated,
        unchanged=unchanged,
        skipped=skipped,
    )
