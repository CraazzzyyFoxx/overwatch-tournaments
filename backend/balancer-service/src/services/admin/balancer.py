from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.models.balancer import WorkspaceBalancerConfig
from shared.repository import (
    BalancerBalanceRepository,
    BalancerTeamRepository,
    BalancerTournamentConfigRepository,
    TournamentRepository,
    WorkspaceBalancerConfigRepository,
)
from shared.services.balancer_realtime import BALANCER_BALANCE_SAVED, BALANCER_CONFIG_CHANGED
from shared.services.team_export import ExportPlan, sync_player_ranks, team_materialization
from src import models, schemas
from src.schemas.team import InternalBalancerTeamsPayload
from src.services.admin.balancer_dual_write import BalancerVariantService, balancer_variant_service
from src.services.balancer.config.provider import normalize_tournament_config_payload, serialize_saved_config_payload
from src.services.balancer.config.public_contract import normalize_balance_response_payload
from src.services.balancer.realtime import emit_balancer_data
from src.services.team import to_materialization_teams

__all__ = ("BalancerAdminService", "balancer_admin_service", "materialize_balance_teams")

logger = logging.getLogger(__name__)


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


class BalancerAdminService:
    def __init__(
        self,
        *,
        tournaments: TournamentRepository = TournamentRepository(),
        tournament_configs: BalancerTournamentConfigRepository = BalancerTournamentConfigRepository(),
        workspace_configs: WorkspaceBalancerConfigRepository = WorkspaceBalancerConfigRepository(),
        balances: BalancerBalanceRepository = BalancerBalanceRepository(),
        teams: BalancerTeamRepository = BalancerTeamRepository(),
        variants: BalancerVariantService = balancer_variant_service,
    ) -> None:
        self.tournaments = tournaments
        self.tournament_configs = tournament_configs
        self.workspace_configs = workspace_configs
        self.balances = balances
        self.teams = teams
        self.variants = variants

    async def ensure_tournament_exists(self, session: AsyncSession, tournament_id: int) -> None:
        if not await self.tournaments.exists(session, id=tournament_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")

    async def get_tournament_row(self, session: AsyncSession, tournament_id: int) -> sa.Row:
        """Minimal tournament projection (id/name/status) for the summary RPC.

        Deliberately NO ``is_hidden`` filter: the summary powers the staff-facing
        balancer tool context, and hidden (preview) tournaments must stay
        resolvable for callers who already passed the workspace ``team.read`` gate.
        """
        row = (
            await session.execute(
                sa.select(models.Tournament.id, models.Tournament.name, models.Tournament.status).where(
                    models.Tournament.id == tournament_id
                )
            )
        ).one_or_none()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")
        return row

    async def get_tournament_config(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> models.BalancerTournamentConfig | None:
        return await self.tournament_configs.get_by_tournament(session, tournament_id)

    async def upsert_tournament_config(
        self,
        session: AsyncSession,
        tournament_id: int,
        workspace_id: int,
        config_json: dict[str, Any] | None,
        auth_user: models.AuthUser,
    ) -> models.BalancerTournamentConfig:
        # workspace_id is resolved by the caller (the RPC handler already fetched
        # it for the permission check) — no second Tournament lookup here.
        normalized_config = normalize_tournament_config_payload(config_json)
        tournament_config = await self.get_tournament_config(session, tournament_id)
        now = datetime.now(UTC)

        if tournament_config is None:
            tournament_config = await self.tournament_configs.create(
                session,
                models.BalancerTournamentConfig(
                    tournament_id=tournament_id,
                    workspace_id=workspace_id,
                    config_json=normalized_config,
                    updated_by=auth_user.id,
                    updated_at=now,
                ),
            )
        else:
            await self.tournament_configs.update_fields(
                session,
                tournament_config,
                {
                    "workspace_id": workspace_id,
                    "config_json": normalized_config,
                    "updated_by": auth_user.id,
                    "updated_at": now,
                },
            )

        await emit_balancer_data(session, tournament_id, BALANCER_CONFIG_CHANGED, actor_user_id=auth_user.id)
        await session.commit()
        return tournament_config

    async def get_workspace_balancer_config(
        self,
        session: AsyncSession,
        workspace_id: int,
    ) -> WorkspaceBalancerConfig | None:
        return await self.workspace_configs.get_by_workspace(session, workspace_id)

    async def upsert_workspace_balancer_config(
        self,
        session: AsyncSession,
        workspace_id: int,
        rank_delta_threshold: int | None,
        rank_delta_hide_from_pool: bool,
        mix_discord_channel_id: str | None,
        updated_by: int | None,
    ) -> WorkspaceBalancerConfig:
        config = await self.get_workspace_balancer_config(session, workspace_id)
        payload: dict[str, Any] = {
            "rank_delta_threshold": rank_delta_threshold,
            "rank_delta_hide_from_pool": rank_delta_hide_from_pool,
            # Digits as a string, the shape the wire uses: JSON has one number
            # type and a snowflake does not survive a float64 round-trip.
            "mix_discord_channel_id": mix_discord_channel_id,
        }
        if config is None:
            config = await self.workspace_configs.create(
                session,
                WorkspaceBalancerConfig(workspace_id=workspace_id, config_json=payload, updated_by=updated_by),
            )
        else:
            await self.workspace_configs.update_fields(
                session, config, {"config_json": payload, "updated_by": updated_by}
            )
        await session.commit()
        # expire_on_commit=False keeps attributes (incl. the flushed PK) live after
        # commit, so no refresh round-trip is needed.
        return config

    async def get_balance(self, session: AsyncSession, tournament_id: int) -> models.BalancerBalance | None:
        return await self.balances.get_by_tournament(session, tournament_id)

    async def save_balance(
        self,
        session: AsyncSession,
        tournament_id: int,
        data: schemas.BalanceSaveRequest,
        auth_user: models.AuthUser,
    ) -> models.BalancerBalance:
        await self.ensure_tournament_exists(session, tournament_id)
        normalized_config_json = serialize_saved_config_payload(data.config_json)
        normalized_result_json = normalize_balance_response_payload(data.result_json)
        payload = InternalBalancerTeamsPayload.model_validate(normalized_result_json)
        if not payload.teams:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Balance result does not contain teams")

        balance = await self.get_balance(session, tournament_id)
        if balance is None:
            balance = await self.balances.create(
                session,
                models.BalancerBalance(
                    tournament_id=tournament_id,
                    config_json=normalized_config_json,
                    result_json=normalized_result_json,
                    saved_by=auth_user.id,
                    saved_at=datetime.now(UTC),
                    export_status=None,
                    export_error=None,
                    exported_at=None,
                ),
            )
        else:
            balance.config_json = normalized_config_json
            balance.result_json = normalized_result_json
            balance.saved_by = auth_user.id
            balance.saved_at = datetime.now(UTC)
            balance.export_status = None
            balance.export_error = None
            balance.exported_at = None
            await self.teams.delete_for_balance(session, balance.id)

        await self.teams.create_many(session, materialize_balance_teams(balance.id, payload))

        algorithm = normalized_config_json.get("algorithm", "unknown") if normalized_config_json else "unknown"
        await self.variants.sync(session, balance, payload, algorithm=algorithm)

        await emit_balancer_data(session, tournament_id, BALANCER_BALANCE_SAVED, actor_user_id=auth_user.id)
        await session.commit()
        # expire_on_commit=False keeps the instance usable after commit, and the
        # response (``serialize_balance``) never touches the teams relationship —
        # no refetch needed.
        return balance

    async def export_balance(self, session: AsyncSession, balance_id: int) -> tuple[models.BalancerBalance, int, int]:
        balance = await self.balances.get_for_export(session, balance_id)
        if balance is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Balance not found")

        payload = InternalBalancerTeamsPayload.model_validate(normalize_balance_response_payload(balance.result_json))
        linked_team_ids = [team.exported_team_id for team in balance.teams if team.exported_team_id is not None]

        def _unlink() -> None:
            for team in balance.teams:
                team.exported_team_id = None

        async def _finalize(_inner: AsyncSession, by_name: Mapping[str, models.Team]) -> None:
            for materialized_team in balance.teams:
                public_team = by_name.get(materialized_team.balancer_name)
                if public_team is not None:
                    materialized_team.exported_team_id = public_team.id

            balance.exported_at = datetime.now(UTC)
            balance.export_status = "success"
            balance.export_error = None

        async def _on_failure(inner: AsyncSession, exc: BaseException) -> None:
            # Runs after the orchestrator's rollback, in a fresh transaction, so the
            # ORM state from the failed attempt is gone — re-load before stamping.
            logger.exception("Failed to export balance %s", balance_id)
            fresh = await self.balances.get(inner, balance_id)
            if fresh is not None:
                fresh.export_status = "failed"
                fresh.export_error = str(exc)

        outcome = await team_materialization.run(
            session,
            ExportPlan(
                tournament_id=balance.tournament_id,
                teams=to_materialization_teams([team.to_balancer_team() for team in payload.teams]),
                prior_team_ids=linked_team_ids,
                on_unresolved="skip",
                unlink=_unlink,
                finalize=_finalize,
                on_failure=_on_failure,
            ),
        )
        return balance, outcome.removed_teams, outcome.imported_teams

    async def export_balance_ranks(self, session: AsyncSession, balance_id: int) -> tuple[models.BalancerBalance, int]:
        """Push the saved balance's ranks onto the already-exported players.

        Non-destructive counterpart to :meth:`export_balance`: no team is removed
        or created, so a bracket built on those teams survives. Returns the balance
        and how many player ranks actually changed.

        Does NOT commit: the caller stages the staleness this causes and commits
        both together, so no client can be told about ranks that a later failure
        rolls back.
        """
        balance = await self.balances.get_for_export(session, balance_id)
        if balance is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Balance not found")

        payload = InternalBalancerTeamsPayload.model_validate(normalize_balance_response_payload(balance.result_json))
        updated = await sync_player_ranks(
            session,
            balance.tournament_id,
            to_materialization_teams([team.to_balancer_team() for team in payload.teams]),
        )
        return balance, updated


balancer_admin_service = BalancerAdminService()
