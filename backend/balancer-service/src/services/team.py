"""Simplified team service for balancer-service.

Provides bulk_create_from_balancer used when exporting a balance result
to tournament teams and players.
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.domain.player_sub_roles import normalize_sub_role
from shared.repository import get_or_create_workspace_member
from src import models
from src.core.enums import HeroClass
from src.schemas.team import BalancerTeam
from src.services import user as user_svc

logger = logging.getLogger(__name__)


def _resolve_hero_role(role: str | None) -> HeroClass | None:
    if role is None:
        return None
    normalized = role.lower()
    if normalized == "tank":
        return HeroClass.tank
    if normalized in {"dps", "damage"}:
        return HeroClass.damage
    if normalized == "support":
        return HeroClass.support
    return None


async def bulk_create_from_balancer(
    session: AsyncSession,
    tournament_id: int,
    payload: list[BalancerTeam],
) -> None:
    """Create tournament teams and players from a balancer export payload.

    Previously this issued ~5 sequential queries per player (battle-tag lookup,
    existing-in-tournament, existing-globally, existing-role, member get/create)
    inside a single long transaction — O(players×5) round-trips (review H12).
    It now front-loads a handful of batch queries and makes only in-memory
    decisions plus INSERTs in the build loop.
    """
    tournament_result = await session.execute(
        sa.select(models.Tournament).where(models.Tournament.id == tournament_id)
    )
    tournament = tournament_result.scalar_one_or_none()
    if tournament is None:
        logger.warning("Tournament %s not found, skipping bulk_create_from_balancer", tournament_id)
        return

    # ── Batch phase: resolve everything the build loop needs up front ──────────
    # 1. Resolve every battle tag (team captains + members) to users in one pass.
    all_tags: set[str] = set()
    for team_data in payload:
        all_tags.add(team_data.name)
        for member in team_data.members:
            all_tags.add(member.name)
    users_by_tag = await user_svc.find_users_by_battle_tags(session, list(all_tags))
    resolved_user_ids = {user.id for user in users_by_tag.values()}

    # 2. Batch-load existing teams for this tournament by lowercased name.
    team_names = {team_data.name.split("#")[0].lower() for team_data in payload}
    existing_teams: dict[str, models.Team] = {}
    if team_names:
        team_rows = (
            await session.execute(
                sa.select(models.Team).where(
                    models.Team.tournament_id == tournament_id,
                    sa.func.lower(models.Team.name).in_(list(team_names)),
                )
            )
        ).scalars().all()
        for team in team_rows:
            existing_teams.setdefault(team.name.lower(), team)

    # 3. One query over the workspace_member→player join (uses
    #    ix_workspace_member_player_id) replaces the former three per-player
    #    SELECTs: existing-in-tournament, existing-globally, existing-per-role.
    players_in_tournament: set[int] = set()
    players_global: set[int] = set()
    players_by_role: set[tuple[int, HeroClass | None]] = set()
    members_by_player: dict[int, models.WorkspaceMember] = {}
    if resolved_user_ids:
        user_id_list = list(resolved_user_ids)
        player_rows = (
            await session.execute(
                sa.select(
                    models.WorkspaceMember.player_id,
                    models.Player.tournament_id,
                    models.Player.role,
                )
                .join(models.Player, models.Player.workspace_member_id == models.WorkspaceMember.id)
                .where(models.WorkspaceMember.player_id.in_(user_id_list))
            )
        ).all()
        for player_id, player_tournament_id, player_role in player_rows:
            players_global.add(player_id)
            players_by_role.add((player_id, player_role))
            if player_tournament_id == tournament_id:
                players_in_tournament.add(player_id)

        # 4. Batch-load existing workspace members for these users.
        member_rows = (
            await session.execute(
                sa.select(models.WorkspaceMember).where(
                    models.WorkspaceMember.workspace_id == tournament.workspace_id,
                    models.WorkspaceMember.player_id.in_(user_id_list),
                )
            )
        ).scalars().all()
        for member_row in member_rows:
            members_by_player[member_row.player_id] = member_row

    # ── Build phase: in-memory decisions + INSERTs only ────────────────────────
    # Tracks users already placed in this tournament (DB pre-state + this import)
    # so a repeated roster entry never creates a duplicate Player.
    placed_user_ids: set[int] = set(players_in_tournament)

    for team_data in payload:
        try:
            name = team_data.name.split("#")[0]
        except ValueError:
            name = team_data.name

        captain = users_by_tag.get(team_data.name)
        team = existing_teams.get(name.lower())

        if team is None:
            team = models.Team(
                name=name,
                balancer_name=team_data.name,
                avg_sr=team_data.avg_sr,
                total_sr=team_data.total_sr,
                tournament_id=tournament.id,
                captain_id=captain.id if captain else None,
            )
            session.add(team)
            await session.flush()
            existing_teams[name.lower()] = team
            logger.info("Team %s created in tournament %s", name, tournament_id)
        else:
            logger.info("Team %s already exists in tournament %s, skipping", name, tournament_id)

        for member in team_data.members:
            user = users_by_tag.get(member.name)
            if user is None:
                logger.warning("User %s not found, skipping player creation", member.name)
                continue

            if user.id in placed_user_ids:
                logger.info("Player %s already in tournament %s, skipping", member.name, tournament_id)
                continue

            role = _resolve_hero_role(member.role)
            is_newcomer = user.id not in players_global
            is_newcomer_role = (user.id, role) not in players_by_role

            workspace_member = members_by_player.get(user.id)
            if workspace_member is None:
                workspace_member = await get_or_create_workspace_member(
                    session, workspace_id=tournament.workspace_id, player_id=user.id
                )
                members_by_player[user.id] = workspace_member

            player = models.Player(
                name=member.name,
                sub_role=normalize_sub_role(member.sub_role),
                rank=member.rank,
                role=role,
                tournament_id=tournament.id,
                team_id=team.id,
                is_newcomer=is_newcomer,
                is_newcomer_role=is_newcomer_role,
                workspace_member_id=workspace_member.id,
            )
            session.add(player)
            placed_user_ids.add(user.id)
            logger.info("Player %s added to team %s", member.name, team.name)

    await session.commit()
