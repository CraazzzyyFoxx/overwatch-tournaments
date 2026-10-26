"""Admin service layer for team and player CRUD operations"""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.models.tournament.player_role import assignment_of
from shared.repository import (
    PlayerRepository,
    StandingRepository,
    TeamRepository,
    UserRepository,
    resolve_workspace_member_id,
)
from shared.services.ontology import resolve_role_ref
from shared.services.stats_owner_delete import capture_owner_delete, stage_owner_delete
from src import schemas
from src.services.tournament.events import STRUCTURE_RESOURCES, publish_tournament_invalidation


async def _tournament_scope(session: AsyncSession, tournament_id: int) -> sa.Row | None:
    """The tournament's ``(workspace_id, discipline)``, or ``None`` when it does not exist.

    Two columns, not ``tournament_repo.get``: a tournament row loads its grid
    version (and that its tiers) and phase schedule eagerly, four statements
    for what these roster writes read two columns of.
    """
    query = sa.select(models.Tournament.workspace_id, models.Tournament.discipline).where(
        models.Tournament.id == tournament_id
    )
    return (await session.execute(query)).first()


def _prepare_player_create_data(data: schemas.PlayerCreate) -> dict:
    player_data = data.model_dump(exclude={"role"})
    if not player_data.get("is_substitution"):
        player_data["related_player_id"] = None
    return player_data


def _prepare_player_update_data(
    player: models.Player,
    data: schemas.PlayerUpdate,
) -> dict:
    update_data = data.model_dump(exclude_unset=True, exclude={"role"})
    if update_data.get("is_substitution") is False:
        update_data["related_player_id"] = None
    return update_data


def _validate_related_player_scope(
    *,
    related_player: models.Player | None,
    related_player_id: int | None,
    team_id: int,
    tournament_id: int,
    player_id: int | None = None,
) -> None:
    if related_player_id is None:
        return

    if related_player is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Related player not found",
        )

    if player_id is not None and related_player.id == player_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Player cannot reference itself as related player",
        )

    if related_player.team_id != team_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Related player must belong to the same team",
        )

    if related_player.tournament_id != tournament_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Related player must belong to the same tournament",
        )


def _prepare_team_create_data(data: schemas.TeamCreate) -> dict:
    team_data = data.model_dump()
    if team_data["balancer_name"] is None:
        team_data["balancer_name"] = team_data["name"]
    return team_data


def _prepare_team_update_data(team: models.Team, data: schemas.TeamUpdate) -> dict:
    update_data = data.model_dump(exclude_unset=True)
    if update_data.get("balancer_name") is None and "balancer_name" in update_data:
        update_data["balancer_name"] = update_data.get("name") or team.name
    return update_data


class AdminTeamService:
    def __init__(
        self,
        *,
        team_repo: TeamRepository = TeamRepository(),
        player_repo: PlayerRepository = PlayerRepository(),
        user_repo: UserRepository = UserRepository(),
        standing_repo: StandingRepository = StandingRepository(),
    ) -> None:
        self.team_repo = team_repo
        self.player_repo = player_repo
        self.user_repo = user_repo
        self.standing_repo = standing_repo

    async def _publish_structure_changed(self, session: AsyncSession, tournament_id: int) -> None:
        """A roster write moved the tournament's materialized teams.

        Kept at ``tournament.structure`` rather than the narrower
        ``tournament.teams``: the FIRST team an organizer creates is what makes
        the page grow a teams section, and that rides on the overview's
        ``teams_count``, which ``tournament.teams`` does not stale. A later
        rename pays one redundant overview refetch for it.
        """
        await publish_tournament_invalidation(session, tournament_id, STRUCTURE_RESOURCES)

    async def _resolve_workspace_member_id(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        player_id: int,
    ) -> int:
        """Resolve the ``workspace_member`` anchor for a roster player being created.

        Delegates to the shared core (workspace from tournament, then an
        idempotent get-or-create) that ``stats-service``'s roster import derives
        this identically from; only the not-found error differs per service, which
        is why it stays here rather than in the shared helper.
        """
        member_id = await resolve_workspace_member_id(session, tournament_id=tournament_id, player_id=player_id)
        if member_id is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")
        return member_id

    async def _get_related_player(
        self,
        session: AsyncSession,
        *,
        related_player_id: int | None,
    ) -> models.Player | None:
        if related_player_id is None:
            return None

        return await self.player_repo.get(session, related_player_id)

    async def _collect_substitution_descendants(
        self,
        session: AsyncSession,
        *,
        player_id: int,
    ) -> list[models.Player]:
        descendants: list[models.Player] = []
        children = await self.player_repo.list_by_related_player(session, player_id)

        for child in children:
            descendants.append(child)
            descendants.extend(await self._collect_substitution_descendants(session, player_id=child.id))

        return descendants

    # ─── Team CRUD ───────────────────────────────────────────────────────────

    async def get_team(self, session: AsyncSession, team_id: int) -> models.Team:
        """Get one team with captain, tournament, and roster loaded."""
        team = await self.team_repo.get(
            session,
            team_id,
            options=[
                selectinload(models.Team.players)
                .selectinload(models.Player.workspace_member)
                .selectinload(models.WorkspaceMember.player),
                selectinload(models.Team.captain),
                selectinload(models.Team.tournament),
            ],
        )

        if not team:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

        return team

    async def get_player(self, session: AsyncSession, player_id: int) -> models.Player:
        player = await self.player_repo.get(
            session,
            player_id,
            options=[
                selectinload(models.Player.workspace_member).selectinload(models.WorkspaceMember.player),
                selectinload(models.Player.tournament),
            ],
        )

        if not player:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Player not found",
            )

        return player

    async def create_team(self, session: AsyncSession, data: schemas.TeamCreate) -> models.Team:
        tournament = await _tournament_scope(session, data.tournament_id)

        if not tournament:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")

        captain = await self.user_repo.get(session, data.captain_id)

        if not captain:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Captain user not found")

        team = await self.team_repo.create(session, models.Team(**_prepare_team_create_data(data)))

        await self._publish_structure_changed(session, data.tournament_id)
        await session.commit()
        return await self.get_team(session, team.id)

    async def update_team(self, session: AsyncSession, team_id: int, data: schemas.TeamUpdate) -> models.Team:
        team = await self.team_repo.get(
            session,
            team_id,
            options=[selectinload(models.Team.players).selectinload(models.Player.workspace_member)],
        )

        if not team:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

        if data.captain_id is not None:
            captain = await self.user_repo.get(session, data.captain_id)
            if not captain:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Captain user not found")
            if team.players and all(
                player.workspace_member is None or player.workspace_member.player_id != data.captain_id
                for player in team.players
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Captain must belong to the current team roster",
                )

        update_data = _prepare_team_update_data(team, data)
        for field, value in update_data.items():
            setattr(team, field, value)

        await self._publish_structure_changed(session, team.tournament_id)
        await session.commit()
        return await self.get_team(session, team.id)

    async def set_team_image(self, session: AsyncSession, team_id: int, image_url: str | None) -> models.Team:
        """Set (or clear, with ``None``) a team's logo URL.

        Deliberately separate from ``update_team``: the image is only ever written by
        the dedicated upload/delete RPC subjects after S3 succeeded, never through the
        generic PATCH body (``TeamUpdate`` has no ``image_url`` field).
        """
        team = await self.team_repo.get(session, team_id)

        if not team:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

        team.image_url = image_url

        await self._publish_structure_changed(session, team.tournament_id)
        await session.commit()
        return await self.get_team(session, team.id)

    async def delete_team(self, session: AsyncSession, team_id: int) -> None:
        """Delete team (cascade deletes players)"""
        team = await self.team_repo.get(session, team_id)

        if not team:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

        tournament_id = team.tournament_id
        evidence = await capture_owner_delete(session, team_id=team_id)
        tournament = await _tournament_scope(session, tournament_id)
        await self.standing_repo.delete_for_team(session, team_id)
        await self.team_repo.delete(session, team)
        await self._publish_structure_changed(session, tournament_id)
        await stage_owner_delete(
            session,
            evidence,
            workspace_id=tournament.workspace_id,
            entity_type="team",
            entity_id=team_id,
        )
        await session.commit()

    # ─── Player CRUD ─────────────────────────────────────────────────────────

    async def create_player(self, session: AsyncSession, data: schemas.PlayerCreate) -> models.Player:
        user = await self.user_repo.get(session, data.user_id)

        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        team = await self.team_repo.get(session, data.team_id)

        if not team:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

        # Tenant-isolation guard: the permission check upstream is resolved from
        # data.tournament_id, so the team must belong to that same tournament —
        # otherwise a caller with rights in workspace A could write into a team
        # (and auto-create a WorkspaceMember) in workspace B.
        if team.tournament_id != data.tournament_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="team_id does not belong to the specified tournament",
            )

        related_player = await self._get_related_player(session, related_player_id=data.related_player_id)
        _validate_related_player_scope(
            related_player=related_player,
            related_player_id=data.related_player_id,
            team_id=team.id,
            tournament_id=team.tournament_id,
        )

        player_data = _prepare_player_create_data(data)
        player_data["tournament_id"] = team.tournament_id
        player_data["workspace_member_id"] = await self._resolve_workspace_member_id(
            session,
            tournament_id=team.tournament_id,
            player_id=player_data.pop("user_id"),
        )
        tournament = await _tournament_scope(session, team.tournament_id)
        leaf = await resolve_role_ref(
            session, discipline=tournament.discipline, workspace_id=tournament.workspace_id, ref=data.role
        )
        player_data["assignments"] = [] if leaf is None else [assignment_of(leaf)]

        player = await self.player_repo.create(session, models.Player(**player_data))

        await self._publish_structure_changed(session, team.tournament_id)
        await session.commit()
        return await self.get_player(session, player.id)

    async def update_player(self, session: AsyncSession, player_id: int, data: schemas.PlayerUpdate) -> models.Player:
        player = await self.player_repo.get(session, player_id)

        if not player:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")

        related_player_id = (
            data.related_player_id if "related_player_id" in data.model_fields_set else player.related_player_id
        )
        related_player = await self._get_related_player(session, related_player_id=related_player_id)
        _validate_related_player_scope(
            related_player=related_player,
            related_player_id=related_player_id,
            team_id=player.team_id,
            tournament_id=player.tournament_id,
            player_id=player.id,
        )

        update_data = _prepare_player_update_data(player, data)
        if "role" in data.model_fields_set:
            tournament = await _tournament_scope(session, player.tournament_id)
            leaf = await resolve_role_ref(
                session, discipline=tournament.discipline, workspace_id=tournament.workspace_id, ref=data.role
            )
            player.assignments = [] if leaf is None else [assignment_of(leaf)]
        for field, value in update_data.items():
            setattr(player, field, value)

        await self._publish_structure_changed(session, player.tournament_id)
        await session.commit()
        return await self.get_player(session, player.id)

    async def delete_player(self, session: AsyncSession, player_id: int) -> None:
        player = await self.player_repo.get(session, player_id)

        if not player:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")

        tournament_id = player.tournament_id
        descendants = await self._collect_substitution_descendants(session, player_id=player.id)
        for descendant in descendants:
            await session.delete(descendant)
        await self.player_repo.delete(session, player)
        await self._publish_structure_changed(session, tournament_id)
        await session.commit()


team_service = AdminTeamService()
