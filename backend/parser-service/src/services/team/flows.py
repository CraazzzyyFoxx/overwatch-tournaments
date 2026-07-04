import asyncio
import re
from dataclasses import dataclass

import sqlalchemy as sa
from loguru import logger
from shared.division_grid import DEFAULT_GRID
from shared.domain.player_sub_roles import normalize_sub_role
from shared.services.division_grid_resolution import resolve_tournament_division
from sqlalchemy.ext.asyncio import AsyncSession

from src import models, schemas
from src.core import enums, errors, utils
from src.services.challonge import service as challonge_service
from src.services.tournament import flows as tournament_flows
from src.services.user import flows as user_flows
from src.services.user import service as user_service

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

    if "user" in entities:
        # workspace_member_id is NOT NULL (contract step, iwrefac07) and is always
        # eager-loaded regardless of the "user" entity flag (see the workspace_member
        # dereference below), so the old "workspace_member is not None" guard here was
        # dead — dropped to match tournament-service's to_pydantic_player.
        user = await user_flows.to_pydantic(
            session, player.workspace_member.player, utils.prepare_entities(entities, "user")
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

    player_dict = player.to_dict()
    # Player.user_id was dropped in the contract step (iwrefac07); PlayerRead.user_id
    # is resolved from workspace_member.player_id instead (workspace_member is always
    # loaded by team_entities/player_entities regardless of the "user" entity flag).
    player_dict["user_id"] = player.workspace_member.player_id

    return schemas.PlayerRead(
        **player_dict,
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


async def _bulk_resolve_users_by_battle_tags(
    session: AsyncSession, battle_tags: list[str]
) -> dict[str, models.User]:
    """Resolve every tag in 1-2 queries and fail like ``find_by_battle_tag``.

    Raises the same 400 ``not_found`` error as ``user_flows.find_by_battle_tag``
    for the first unresolvable tag in input order, so callers keep the exact
    per-item error contract of the old N+1 implementation.
    """
    users_by_tag = await user_service.find_users_by_battle_tags(session, battle_tags)
    for battle_tag in battle_tags:
        if battle_tag not in users_by_tag:
            raise errors.ApiHTTPException(
                status_code=400,
                detail=[
                    errors.ApiExc(
                        code="not_found",
                        msg=f"User with battle tag {battle_tag} not found.",
                    )
                ],
            )
    return users_by_tag


async def bulk_create_from_balancer(
    session: AsyncSession, tournament_id: int, payload: list[schemas.BalancerTeam]
) -> None:
    tournament = await tournament_flows.get(session, tournament_id, [])

    # Resolve every battle tag (captains + members) up front: 1-2 queries for
    # the whole import instead of 2-4 SELECTs per name. Tags are validated in
    # payload order so the first missing tag raises the same error as before.
    all_tags: list[str] = []
    for team_data in payload:
        all_tags.append(team_data.name)
        all_tags.extend(member.name for member in team_data.members)
    users_by_tag = await _bulk_resolve_users_by_battle_tags(session, all_tags)

    # Prefetch existing teams and roster rows for this tournament (one query
    # each) plus the resolved users' whole player history (one query) so the
    # per-team/per-player loops below never touch the database for lookups.
    teams_by_name: dict[str, models.Team] = {}
    for existing_team in await service.get_by_tournament(session, tournament.id, []):
        teams_by_name.setdefault(existing_team.name.lower(), existing_team)

    tournament_user_ids: set[int] = set(
        (
            await session.execute(
                sa.select(models.WorkspaceMember.player_id)
                .select_from(models.Player)
                .join(
                    models.WorkspaceMember,
                    models.WorkspaceMember.id == models.Player.workspace_member_id,
                )
                .where(models.Player.tournament_id == tournament.id)
            )
        )
        .scalars()
        .all()
    )

    experienced_user_ids: set[int] = set()
    experienced_user_roles: set[tuple[int, enums.HeroClass | None]] = set()
    resolved_user_ids = {user.id for user in users_by_tag.values()}
    if resolved_user_ids:
        history_rows = await session.execute(
            sa.select(models.WorkspaceMember.player_id, models.Player.role)
            .select_from(models.Player)
            .join(
                models.WorkspaceMember,
                models.WorkspaceMember.id == models.Player.workspace_member_id,
            )
            .where(models.WorkspaceMember.player_id.in_(resolved_user_ids))
        )
        for user_id, existing_role in history_rows.all():
            experienced_user_ids.add(user_id)
            experienced_user_roles.add((user_id, existing_role))

    pending_players: list[
        tuple[schemas.BalancerTeamMember, models.Team, models.User, enums.HeroClass | None, bool, bool]
    ] = []

    for team_data in payload:
        try:
            name = team_data.name.split("#")[0]
        except ValueError:
            name = team_data.name

        captain = users_by_tag[team_data.name]
        team = teams_by_name.get(name.lower())
        if not team:
            team = models.Team(
                name=name,
                balancer_name=team_data.name,
                avg_sr=team_data.avg_sr,
                total_sr=team_data.total_sr,
                tournament_id=tournament.id,
                captain_id=captain.id,
            )
            session.add(team)
            # Flush per new team only (a dozen INSERTs, not hundreds of
            # SELECTs) so ``team.id`` is available for the roster rows below.
            await session.flush()
            teams_by_name[name.lower()] = team
        else:
            logger.info(f"Team {name} already exists in tournament {tournament.name}. Skipping...")

        for player in team_data.members:
            logger.info(f"Trying to add player {player.name} to team {team.name} in tournament {tournament.name}")
            user = users_by_tag[player.name]
            if user.id in tournament_user_ids:
                logger.info(
                    f"Player {player.name} already exists in team [name={team.name} tournament={tournament.name}]."
                )
                continue

            is_newcomer = user.id not in experienced_user_ids
            role = resolve_hero_role_from_balancer(player.role)
            is_newcomer_role = (user.id, role) not in experienced_user_roles

            # In-payload dedupe: the old per-item re-SELECT would find the row
            # committed for a duplicate occurrence and skip it.
            tournament_user_ids.add(user.id)
            pending_players.append((player, team, user, role, is_newcomer, is_newcomer_role))

    if pending_players:
        member_ids = await service.resolve_workspace_member_ids(
            session,
            workspace_id=tournament.workspace_id,
            player_ids={user.id for _, _, user, _, _, _ in pending_players},
        )
        for player, team, user, role, is_newcomer, is_newcomer_role in pending_players:
            session.add(
                models.Player(
                    name=player.name,
                    sub_role=normalize_sub_role(player.sub_role),
                    rank=player.rank,
                    role=role,
                    tournament_id=tournament.id,
                    team_id=team.id,
                    is_substitution=False,
                    related_player_id=None,
                    is_newcomer=is_newcomer,
                    is_newcomer_role=is_newcomer_role,
                    workspace_member_id=member_ids[user.id],
                )
            )
        await session.flush()
        for player, team, _, _, _, _ in pending_players:
            logger.info(f"Player {player.name} added to team {team.name} in tournament {tournament.id}")

    await session.commit()
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


_CHALLONGE_FETCH_CONCURRENCY = 4


@dataclass(frozen=True)
class _ParticipantGroupContext:
    group_id: int | None
    group_name: str | None
    is_playoff: bool


@dataclass(frozen=True)
class _ParticipantFetchPlan:
    challonge_tournament_id: int
    source_id: int | None
    group_contexts: tuple[_ParticipantGroupContext, ...]


async def _build_participant_fetch_plans(
    session: AsyncSession,
    tournament: models.Tournament,
    *,
    create_sources: bool,
) -> list[_ParticipantFetchPlan]:
    """Do all the DB work for a participant sync (source get-or-create, group
    context capture) and return plain-value fetch plans, so the Challonge HTTP
    round-trips can run outside any open transaction."""
    groups = list(tournament.groups or [])

    if tournament.challonge_id:
        source_id = await _get_or_create_challonge_source_id(
            session,
            tournament,
            challonge_tournament_id=tournament.challonge_id,
            slug=tournament.challonge_slug,
            create=create_sources,
        )
        return [
            _ParticipantFetchPlan(
                challonge_tournament_id=tournament.challonge_id,
                source_id=source_id,
                group_contexts=tuple(
                    _ParticipantGroupContext(
                        group_id=getattr(group, "id", None),
                        group_name=getattr(group, "name", None),
                        is_playoff=bool(group is not None and not group.is_groups),
                    )
                    for group in (groups or [None])
                ),
            )
        ]

    plans: list[_ParticipantFetchPlan] = []
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
        plans.append(
            _ParticipantFetchPlan(
                challonge_tournament_id=group.challonge_id,
                source_id=source_id,
                group_contexts=(
                    _ParticipantGroupContext(
                        group_id=group.id,
                        group_name=group.name,
                        is_playoff=not group.is_groups,
                    ),
                ),
            )
        )
    return plans


async def _fetch_challonge_participant_rows(
    session: AsyncSession,
    tournament: models.Tournament,
    *,
    create_sources: bool = False,
) -> list[_ChallongeParticipantRow]:
    plans = await _build_participant_fetch_plans(session, tournament, create_sources=create_sources)
    if not plans:
        return []

    # Commit (and thereby release the pgBouncer/NullPool-backed connection)
    # before the rate-limited Challonge round-trips: holding a transaction open
    # across third-party HTTP pins a scarce backend slot for the whole network
    # wait. expire_on_commit=False keeps the already-loaded tournament/teams
    # usable; callers resume their writes in a fresh, short transaction.
    await session.commit()

    semaphore = asyncio.Semaphore(_CHALLONGE_FETCH_CONCURRENCY)

    async def _fetch_participants(challonge_tournament_id: int) -> list[schemas.ChallongeParticipant]:
        async with semaphore:
            return await challonge_service.fetch_participants(challonge_tournament_id)

    # No return_exceptions: a failed source aborts the whole sync, exactly like
    # the old serial loop did.
    participants_per_plan = await asyncio.gather(
        *(_fetch_participants(plan.challonge_tournament_id) for plan in plans)
    )

    rows: list[_ChallongeParticipantRow] = []
    for plan, participants in zip(plans, participants_per_plan, strict=True):
        for context in plan.group_contexts:
            for participant in participants:
                rows.append(
                    _ChallongeParticipantRow(
                        participant_id=participant.id,
                        challonge_id=_effective_challonge_id(
                            participant,
                            is_playoff=context.is_playoff,
                        ),
                        source_id=plan.source_id,
                        group_id=context.group_id,
                        group_name=context.group_name,
                        challonge_tournament_id=plan.challonge_tournament_id,
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
