"""Simplified team service for balancer-service.

Provides bulk_create_from_balancer used when exporting a balance result
to tournament teams and players.
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.domain.player_sub_roles import normalize_sub_role
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
    """Create tournament teams and players from a balancer export payload."""
    tournament_result = await session.execute(
        sa.select(models.Tournament).where(models.Tournament.id == tournament_id)
    )
    tournament = tournament_result.scalar_one_or_none()
    if tournament is None:
        logger.warning("Tournament %s not found, skipping bulk_create_from_balancer", tournament_id)
        return

    for team_data in payload:
        try:
            name = team_data.name.split("#")[0]
        except ValueError:
            name = team_data.name

        captain = await user_svc.find_by_battle_tag(session, team_data.name, [])

        existing_team_result = await session.execute(
            sa.select(models.Team).where(
                sa.func.lower(models.Team.name) == name.lower(),
                models.Team.tournament_id == tournament_id,
            )
        )
        team = existing_team_result.scalar_one_or_none()

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
            logger.info("Team %s created in tournament %s", name, tournament_id)
        else:
            logger.info("Team %s already exists in tournament %s, skipping", name, tournament_id)

        for member in team_data.members:
            logger.info("Adding player %s to team %s", member.name, team.name)
            user = await user_svc.find_by_battle_tag(session, member.name, [])
            if user is None:
                logger.warning("User %s not found, skipping player creation", member.name)
                continue

            existing_player_result = await session.execute(
                sa.select(models.Player).where(
                    models.Player.user_id == user.id,
                    models.Player.tournament_id == tournament_id,
                )
            )
            if existing_player_result.scalar_one_or_none() is not None:
                logger.info("Player %s already in tournament %s, skipping", member.name, tournament_id)
                continue

            existing_globally_result = await session.execute(
                sa.select(models.Player).where(models.Player.user_id == user.id).limit(1)
            )
            is_newcomer = existing_globally_result.scalar_one_or_none() is None

            role = _resolve_hero_role(member.role)
            existing_role_result = await session.execute(
                sa.select(models.Player).where(
                    models.Player.user_id == user.id,
                    models.Player.role == role,
                ).limit(1)
            )
            is_newcomer_role = existing_role_result.scalar_one_or_none() is None

            player = models.Player(
                name=member.name,
                sub_role=normalize_sub_role(member.sub_role),
                rank=member.rank,
                role=role,
                user_id=user.id,
                tournament_id=tournament.id,
                team_id=team.id,
                is_newcomer=is_newcomer,
                is_newcomer_role=is_newcomer_role,
            )
            session.add(player)
            logger.info("Player %s added to team %s", member.name, team.name)

    await session.commit()
