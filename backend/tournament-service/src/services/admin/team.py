"""Admin service layer for team and player CRUD operations"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.domain.player_sub_roles import normalize_sub_role
from shared.repository import (
    PlayerRepository,
    StandingRepository,
    TeamRepository,
    TournamentRepository,
    UserRepository,
    resolve_workspace_member_id,
)
from src import models, schemas
from src.services.tournament.events import STRUCTURE_RESOURCES, publish_tournament_invalidation


def _prepare_player_create_data(data: schemas.PlayerCreate) -> dict:
    player_data = data.model_dump()
    player_data["sub_role"] = normalize_sub_role(player_data.get("sub_role"))
    if not player_data.get("is_substitution"):
        player_data["related_player_id"] = None
    return player_data


def _prepare_player_update_data(
    player: models.Player,
    data: schemas.PlayerUpdate,
) -> dict:
    update_data = data.model_dump(exclude_unset=True)
    if "sub_role" in update_data:
        update_data["sub_role"] = normalize_sub_role(update_data["sub_role"])
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
        tournament_repo: TournamentRepository = TournamentRepository(),
        user_repo: UserRepository = UserRepository(),
        standing_repo: StandingRepository = StandingRepository(),
    ) -> None:
        self.team_repo = team_repo
        self.player_repo = player_repo
        self.tournament_repo = tournament_repo
        self.user_repo = user_repo
        self.standing_repo = standing_repo

    async def _publish_structure_changed(self, session: AsyncSession, tournament_id: int) -> None:
        """A roster write moved the tournament's materialized teams.

        Kept at ``tournament.structure`` rather than the narrower
        ``tournament.teams``: the FIRST team an organizer creates is what makes
        the page grow a teams section, and that is the one thing a client cannot
        fix by refetching a query. A later rename pays one redundant route
        refresh for it, which is what this path already cost before.
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
        idempotent get-or-create) that ``parser-service``'s roster import derives
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
        """Create a new team"""
        # Verify tournament exists
        tournament = await self.tournament_repo.get(session, data.tournament_id)

        if not tournament:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")

        # Verify captain exists
        captain = await self.user_repo.get(session, data.captain_id)

        if not captain:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Captain user not found")

        # Create team
        team = await self.team_repo.create(session, models.Team(**_prepare_team_create_data(data)))

        await self._publish_structure_changed(session, data.tournament_id)
        await session.commit()
        return await self.get_team(session, team.id)

    async def update_team(self, session: AsyncSession, team_id: int, data: schemas.TeamUpdate) -> models.Team:
        """Update team fields"""
        team = await self.team_repo.get(
            session,
            team_id,
            options=[selectinload(models.Team.players).selectinload(models.Player.workspace_member)],
        )

        if not team:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

        # Verify captain exists if being updated
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

        # Update fields
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
        await self.standing_repo.delete_for_team(session, team_id)
        await self.team_repo.delete(session, team)
        await self._publish_structure_changed(session, tournament_id)
        await session.commit()

    # ─── Player Management ───────────────────────────────────────────────────

    async def add_player_to_team(
        self, session: AsyncSession, team_id: int, data: schemas.PlayerCreate
    ) -> models.Player:
        """Add a player to a team"""
        # Verify team exists
        team = await self.team_repo.get(session, team_id)

        if not team:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

        # Verify user exists
        user = await self.user_repo.get(session, data.user_id)

        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        # Override team_id from URL parameter
        player_data = _prepare_player_create_data(data)
        player_data["team_id"] = team_id
        player_data["tournament_id"] = team.tournament_id
        related_player = await self._get_related_player(
            session,
            related_player_id=player_data.get("related_player_id"),
        )
        _validate_related_player_scope(
            related_player=related_player,
            related_player_id=player_data.get("related_player_id"),
            team_id=team_id,
            tournament_id=team.tournament_id,
        )

        player_data["workspace_member_id"] = await self._resolve_workspace_member_id(
            session,
            tournament_id=team.tournament_id,
            player_id=player_data.pop("user_id"),
        )

        # Create player
        player = await self.player_repo.create(session, models.Player(**player_data))

        await self._publish_structure_changed(session, team.tournament_id)
        await session.commit()
        return await self.get_player(session, player.id)

    async def remove_player_from_team(self, session: AsyncSession, team_id: int, player_id: int) -> None:
        """Remove a player from a team"""
        player = await self.player_repo.get_by(session, id=player_id, team_id=team_id)

        if not player:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found in this team")

        tournament_id = player.tournament_id
        await self.player_repo.delete(session, player)
        await self._publish_structure_changed(session, tournament_id)
        await session.commit()

    # ─── Player CRUD ─────────────────────────────────────────────────────────

    async def create_player(self, session: AsyncSession, data: schemas.PlayerCreate) -> models.Player:
        """Create a new player"""
        # Verify user exists
        user = await self.user_repo.get(session, data.user_id)

        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        # Verify team exists
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

        # Create player
        player = await self.player_repo.create(session, models.Player(**player_data))

        await self._publish_structure_changed(session, team.tournament_id)
        await session.commit()
        return await self.get_player(session, player.id)

    async def update_player(self, session: AsyncSession, player_id: int, data: schemas.PlayerUpdate) -> models.Player:
        """Update player fields"""
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

        # Update fields
        update_data = _prepare_player_update_data(player, data)
        for field, value in update_data.items():
            setattr(player, field, value)

        await self._publish_structure_changed(session, player.tournament_id)
        await session.commit()
        return await self.get_player(session, player.id)

    async def delete_player(self, session: AsyncSession, player_id: int) -> None:
        """Delete player"""
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
