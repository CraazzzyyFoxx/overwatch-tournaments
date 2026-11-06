from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Row
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.disciplines import DISCIPLINES
from shared.models.balancer import WorkspaceBalancerConfig
from shared.repository import (
    BalancerBalanceRepository,
    BalancerTeamRepository,
    BalancerTournamentConfigRepository,
    TournamentRepository,
    WorkspaceBalancerConfigRepository,
)
from shared.services.balancer_realtime import BALANCER_BALANCE_SAVED, BALANCER_CONFIG_CHANGED, BALANCER_TEAMS_CHANGED
from shared.services.discord_errors import DiscordError
from shared.services.roster import roster_engine
from src import schemas
from src.domain.balancer.config.public_contract import (
    normalize_balance_response_payload,
    normalize_config_payload,
)
from src.schemas.team import InternalBalancerTeamsPayload
from src.services.admin.balancer_variant import BalancerVariantService, balancer_variant_service
from src.services.balancer.config.provider import normalize_tournament_config_payload
from src.services.balancer.realtime import emit_balancer_data, stage_export_invalidation
from src.services.formation_node import require_forming
from src.services.team import to_materialization_teams
from src.services.team_export import ExportPlan, refuse_missing_handles, sync_player_ranks, team_materialization

__all__ = ("BalancerAdminService", "balancer_admin_service", "materialize_balance_teams")

logger = logging.getLogger(__name__)

#: The workspace guild's channel listing (``DiscordClient.guild_channels``),
#: passed in by the RPC layer, which holds the broker.
ChannelReader = Callable[[str], Awaitable[list[dict[str, Any]]]]


def _newly_set_discord_ids(
    stored: Mapping[str, Any], channel: str | None, category: str | None, generals: list[str]
) -> set[tuple[str, str]]:
    """``(id, channel type)`` of every Discord id this write changes to a value.

    An unchanged or cleared value is not asked about, so saving the pool knobs
    beside an untouched channel -- or clearing one -- never needs Discord.
    """
    wanted: set[tuple[str, str]] = set()
    if channel and channel != str(stored.get("mix_discord_channel_id") or ""):
        wanted.add((channel, "text"))
    if category and category != str(stored.get("mix_voice_category_id") or ""):
        wanted.add((category, "category"))
    if generals != [str(v) for v in stored.get("mix_general_voice_channel_ids") or []]:
        wanted.update((voice, "voice") for voice in generals)
    return wanted


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

    async def get_tournament_row(self, session: AsyncSession, tournament_id: int) -> Row:
        """Minimal tournament projection (id/name/status) for the summary RPC.

        Deliberately NO ``is_hidden`` filter: the summary powers the staff-facing
        balancer tool context, and hidden (preview) tournaments must stay
        resolvable for callers who already passed the workspace ``team.read`` gate.
        """
        row = await self.tournaments.get_summary_row(session, tournament_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")
        return row

    async def get_tournament_config(
        self,
        session: AsyncSession,
        formation_node_id: int,
    ) -> models.BalancerTournamentConfig | None:
        return await self.tournament_configs.get_by_formation_node(session, formation_node_id)

    async def upsert_tournament_config(
        self,
        session: AsyncSession,
        tournament_id: int,
        formation_node_id: int,
        workspace_id: int,
        config_json: dict[str, Any] | None,
        auth_user: models.AuthUser,
    ) -> models.BalancerTournamentConfig:
        # workspace_id is resolved by the caller (the RPC handler already fetched
        # it for the permission check) — no second Tournament lookup here.
        normalized_config = normalize_tournament_config_payload(config_json)
        tournament_config = await self.get_tournament_config(session, formation_node_id)
        now = datetime.now(UTC)

        if tournament_config is None:
            tournament_config = await self.tournament_configs.create(
                session,
                models.BalancerTournamentConfig(
                    tournament_id=tournament_id,
                    formation_node_id=formation_node_id,
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
        mix_voice_category_id: str | None,
        mix_general_voice_channel_ids: list[str],
        updated_by: int | None,
        *,
        list_channels: ChannelReader,
    ) -> WorkspaceBalancerConfig:
        """Store the blob after proving every newly set Discord id is this workspace's guild's.

        Without the check an admin of workspace A could point the bot at a
        channel of guild B (the bot sits in both). Same rule and codes as
        app-service's notification channel: 409 ``discord_guild_not_linked``,
        422 ``discord_channel_not_in_guild``, 503 ``discord_unavailable`` --
        never a silent accept of an id nobody checked.
        """
        config = await self.get_workspace_balancer_config(session, workspace_id)
        wanted = _newly_set_discord_ids(
            (config.config_json or {}) if config is not None else {},
            mix_discord_channel_id,
            mix_voice_category_id,
            mix_general_voice_channel_ids,
        )
        if wanted:
            row = await self.workspace_configs.config_with_guild(session, workspace_id)
            guild_id = row[1] if row is not None else None
            if not guild_id:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="discord_guild_not_linked")
            try:
                channels = await list_channels(str(guild_id))
            except DiscordError as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="discord_unavailable"
                ) from exc
            if not wanted <= {(str(c.get("id")), c.get("type")) for c in channels}:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="discord_channel_not_in_guild"
                )
        payload: dict[str, Any] = {
            "rank_delta_threshold": rank_delta_threshold,
            "rank_delta_hide_from_pool": rank_delta_hide_from_pool,
            # Digits as a string, the shape the wire uses: JSON has one number
            # type and a snowflake does not survive a float64 round-trip.
            "mix_discord_channel_id": mix_discord_channel_id,
            "mix_voice_category_id": mix_voice_category_id,
            "mix_general_voice_channel_ids": list(mix_general_voice_channel_ids),
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

    async def get_balance(self, session: AsyncSession, formation_node_id: int) -> models.BalancerBalance | None:
        return await self.balances.get_by_formation_node(session, formation_node_id)

    async def save_balance(
        self,
        session: AsyncSession,
        tournament_id: int,
        formation_node_id: int,
        data: schemas.BalanceSaveRequest,
        auth_user: models.AuthUser,
    ) -> models.BalancerBalance:
        await self.ensure_tournament_exists(session, tournament_id)
        normalized_config_json = normalize_config_payload(data.config_json)
        normalized_result_json = normalize_balance_response_payload(data.result_json)
        payload = InternalBalancerTeamsPayload.model_validate(normalized_result_json)
        if not payload.teams:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Balance result does not contain teams")

        balance = await self.get_balance(session, formation_node_id)
        if balance is None:
            balance = await self.balances.create(
                session,
                models.BalancerBalance(
                    tournament_id=tournament_id,
                    formation_node_id=formation_node_id,
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

    async def export_balance(
        self, session: AsyncSession, balance_id: int, *, actor_user_id: int
    ) -> tuple[models.BalancerBalance, int, int, list[str]]:
        balance = await self.balances.get_for_export(session, balance_id)
        if balance is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Balance not found")
        await require_forming(session, balance.formation_node_id, mode="balancer")

        payload = InternalBalancerTeamsPayload.model_validate(normalize_balance_response_payload(balance.result_json))
        tournament = await self.tournaments.get(session, balance.tournament_id)
        dimension = DISCIPLINES[tournament.discipline].rated_dimension.code
        linked_team_ids = [team.exported_team_id for team in balance.teams if team.exported_team_id is not None]
        # A tournament balance seats registrations by id (an uploaded one may carry other uuids: resolved by name only).
        registration_ids = sorted(
            {
                int(player.uuid)
                for team in payload.teams
                for players in team.roster.values()
                for player in players
                if str(player.uuid).isdigit()
            }
        )
        refuse_missing_handles(
            (await roster_engine.for_node_registrations(session, balance.formation_node_id, registration_ids)).values()
        )

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
                formation_node_id=balance.formation_node_id,
                teams=to_materialization_teams([team.to_balancer_team(dimension) for team in payload.teams]),
                prior_team_ids=linked_team_ids,
                on_unresolved="skip",
                unlink=_unlink,
                finalize=_finalize,
                on_failure=_on_failure,
            ),
        )
        await emit_balancer_data(session, balance.tournament_id, BALANCER_TEAMS_CHANGED, actor_user_id=actor_user_id)
        await stage_export_invalidation(session, balance.tournament_id)
        return balance, outcome.removed_teams, outcome.imported_teams, outcome.materialization.advisories

    async def export_balance_ranks(
        self, session: AsyncSession, balance_id: int, *, actor_user_id: int
    ) -> tuple[models.BalancerBalance, int]:
        """Push the saved balance's ranks onto the already-exported players.

        Non-destructive counterpart to :meth:`export_balance`: no team is removed
        or created, so a bracket built on those teams survives. Returns the balance
        and how many player ranks actually changed.

        Does NOT commit: the staleness is staged beside the rank writes and the
        caller commits both together, so no client can be told about ranks that
        a later failure rolls back.
        """
        balance = await self.balances.get_for_export(session, balance_id)
        if balance is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Balance not found")

        payload = InternalBalancerTeamsPayload.model_validate(normalize_balance_response_payload(balance.result_json))
        tournament = await self.tournaments.get(session, balance.tournament_id)
        dimension = DISCIPLINES[tournament.discipline].rated_dimension.code
        updated = await sync_player_ranks(
            session,
            balance.formation_node_id,
            to_materialization_teams([team.to_balancer_team(dimension) for team in payload.teams]),
            linked_team_ids=[team.exported_team_id for team in balance.teams if team.exported_team_id is not None],
        )
        await emit_balancer_data(session, balance.tournament_id, BALANCER_TEAMS_CHANGED, actor_user_id=actor_user_id)
        await stage_export_invalidation(session, balance.tournament_id)
        return balance, updated


balancer_admin_service = BalancerAdminService()
