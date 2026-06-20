from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from shared.core.errors import BaseAPIException as HTTPException
from shared.core import http_status as status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.models.balancer import WorkspaceBalancerConfig
from src import models
from src.services.balancer.config.provider import normalize_tournament_config_payload, serialize_saved_config_payload
from src.services.balancer.config.public_contract import normalize_balance_response_payload
from src.schemas.admin import balancer as admin_schemas
from src.schemas.team import InternalBalancerTeamsPayload
from src.services import team as team_flows
from src.services.admin.balance_analytics import create_balance_snapshot
from src.services.admin.balancer_dual_write import sync_balance_variants_and_slots

logger = logging.getLogger(__name__)


async def ensure_tournament_exists(session: AsyncSession, tournament_id: int) -> None:
    result = await session.execute(sa.select(models.Tournament.id).where(models.Tournament.id == tournament_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")


async def get_tournament_workspace_id(session: AsyncSession, tournament_id: int) -> int:
    workspace_id = await session.scalar(
        sa.select(models.Tournament.workspace_id).where(models.Tournament.id == tournament_id)
    )
    if workspace_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")
    return int(workspace_id)


async def get_tournament_config(
    session: AsyncSession,
    tournament_id: int,
) -> models.BalancerTournamentConfig | None:
    result = await session.execute(
        sa.select(models.BalancerTournamentConfig).where(
            models.BalancerTournamentConfig.tournament_id == tournament_id
        )
    )
    return result.scalar_one_or_none()


async def upsert_tournament_config(
    session: AsyncSession,
    tournament_id: int,
    config_json: dict[str, Any] | None,
    auth_user: models.AuthUser,
) -> models.BalancerTournamentConfig:
    workspace_id = await get_tournament_workspace_id(session, tournament_id)
    normalized_config = normalize_tournament_config_payload(config_json)
    tournament_config = await get_tournament_config(session, tournament_id)

    if tournament_config is None:
        tournament_config = models.BalancerTournamentConfig(
            tournament_id=tournament_id,
            workspace_id=workspace_id,
            config_json=normalized_config,
            updated_by=auth_user.id,
            updated_at=datetime.now(UTC),
        )
        session.add(tournament_config)
    else:
        tournament_config.workspace_id = workspace_id
        tournament_config.config_json = normalized_config
        tournament_config.updated_by = auth_user.id
        tournament_config.updated_at = datetime.now(UTC)

    await session.commit()
    return tournament_config


async def get_workspace_balancer_config(
    session: AsyncSession,
    workspace_id: int,
) -> WorkspaceBalancerConfig | None:
    result = await session.execute(
        sa.select(WorkspaceBalancerConfig).where(
            WorkspaceBalancerConfig.workspace_id == workspace_id
        )
    )
    return result.scalar_one_or_none()


async def upsert_workspace_balancer_config(
    session: AsyncSession,
    workspace_id: int,
    rank_delta_threshold: int | None,
    rank_delta_hide_from_pool: bool,
    updated_by: int | None,
) -> WorkspaceBalancerConfig:
    config = await get_workspace_balancer_config(session, workspace_id)
    payload: dict[str, Any] = {
        "rank_delta_threshold": rank_delta_threshold,
        "rank_delta_hide_from_pool": rank_delta_hide_from_pool,
    }
    if config is None:
        config = WorkspaceBalancerConfig(
            workspace_id=workspace_id,
            config_json=payload,
            updated_by=updated_by,
        )
        session.add(config)
    else:
        config.config_json = payload
        config.updated_by = updated_by
    await session.commit()
    await session.refresh(config)
    return config


async def get_balance(session: AsyncSession, tournament_id: int) -> models.BalancerBalance | None:
    result = await session.execute(
        sa.select(models.BalancerBalance)
        .where(models.BalancerBalance.tournament_id == tournament_id)
        .options(selectinload(models.BalancerBalance.teams))
    )
    return result.scalar_one_or_none()


def materialize_balance_teams(
    balance_id: int,
    payload: InternalBalancerTeamsPayload,
) -> list[models.BalancerTeam]:
    teams: list[models.BalancerTeam] = []
    for sort_order, team in enumerate(payload.teams):
        total_sr = sum(player.assigned_rating for players in team.roster.values() for player in players)
        teams.append(
            models.BalancerTeam(
                balance_id=balance_id,
                exported_team_id=None,
                name=team.name.split("#")[0],
                balancer_name=team.name,
                captain_battle_tag=team.name,
                avg_sr=team.average_mmr,
                total_sr=total_sr,
                sort_order=sort_order,
            )
        )
    return teams


async def save_balance(
    session: AsyncSession,
    tournament_id: int,
    data: admin_schemas.BalanceSaveRequest,
    auth_user: models.AuthUser,
) -> models.BalancerBalance:
    await ensure_tournament_exists(session, tournament_id)
    normalized_config_json = serialize_saved_config_payload(data.config_json)
    normalized_result_json = normalize_balance_response_payload(data.result_json)
    payload = InternalBalancerTeamsPayload.model_validate(normalized_result_json)
    if not payload.teams:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Balance result does not contain teams")

    balance = await get_balance(session, tournament_id)
    if balance is None:
        balance = models.BalancerBalance(
            tournament_id=tournament_id,
            config_json=normalized_config_json,
            result_json=normalized_result_json,
            saved_by=auth_user.id,
            saved_at=datetime.now(UTC),
            export_status=None,
            export_error=None,
            exported_at=None,
        )
        session.add(balance)
        await session.flush()
    else:
        balance.config_json = normalized_config_json
        balance.result_json = normalized_result_json
        balance.saved_by = auth_user.id
        balance.saved_at = datetime.now(UTC)
        balance.export_status = None
        balance.export_error = None
        balance.exported_at = None
        await session.execute(sa.delete(models.BalancerTeam).where(models.BalancerTeam.balance_id == balance.id))

    session.add_all(materialize_balance_teams(balance.id, payload))
    await session.flush()

    algorithm = normalized_config_json.get("algorithm", "unknown") if normalized_config_json else "unknown"
    await sync_balance_variants_and_slots(session, balance, payload, algorithm=algorithm)

    await session.commit()

    saved_balance = await get_balance(session, tournament_id)
    if saved_balance is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to save balance")
    return saved_balance


async def export_balance(session: AsyncSession, balance_id: int) -> tuple[models.BalancerBalance, int, int]:
    result = await session.execute(
        sa.select(models.BalancerBalance)
        .where(models.BalancerBalance.id == balance_id)
        .options(selectinload(models.BalancerBalance.teams))
    )
    balance = result.scalar_one_or_none()
    if balance is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Balance not found")

    payload = InternalBalancerTeamsPayload.model_validate(normalize_balance_response_payload(balance.result_json))

    linked_team_ids = [team.exported_team_id for team in balance.teams if team.exported_team_id is not None]
    removed_teams = len(linked_team_ids)

    if linked_team_ids:
        await session.execute(sa.delete(models.Standing).where(models.Standing.team_id.in_(linked_team_ids)))
        await session.execute(sa.delete(models.Player).where(models.Player.team_id.in_(linked_team_ids)))
        await session.execute(sa.delete(models.Team).where(models.Team.id.in_(linked_team_ids)))
        for team in balance.teams:
            team.exported_team_id = None
        await session.commit()

    try:
        balancer_teams = [team.to_balancer_team() for team in payload.teams]
        await team_flows.bulk_create_from_balancer(session, balance.tournament_id, balancer_teams)

        imported_names = [team.name for team in payload.teams]
        result = await session.execute(
            sa.select(models.Team).where(
                models.Team.tournament_id == balance.tournament_id,
                models.Team.balancer_name.in_(imported_names),
            )
        )
        public_teams = {team.balancer_name: team for team in result.scalars().all()}
        for materialized_team in balance.teams:
            public_team = public_teams.get(materialized_team.balancer_name)
            if public_team is not None:
                materialized_team.exported_team_id = public_team.id

        balance.exported_at = datetime.now(UTC)
        balance.export_status = "success"
        balance.export_error = None

        await create_balance_snapshot(session, balance, payload, public_teams)

        await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to export balance %s", balance.id)
        balance.export_status = "failed"
        balance.export_error = str(exc)
        await session.commit()
        raise

    refreshed = await get_balance(session, balance.tournament_id)
    if refreshed is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to refresh exported balance"
        )
    return refreshed, removed_teams, len(payload.teams)
