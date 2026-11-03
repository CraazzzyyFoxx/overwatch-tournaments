"""Admin side of the voice channels: the organizer's settings and what the bot made of them."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.repository import TournamentRepository
from shared.repository.voice import TournamentVoiceChannelRepository, TournamentVoiceSettingsRepository
from shared.services.discord_errors import DiscordError
from src.schemas import voice as voice_schemas
from src.services.tournament.events import enqueue_tournament_voice_sync
from src.services.voice.plan import build_voice_plan

__all__ = ("request_sync", "save_settings", "status_of")

#: ``DiscordClient.guild_channels`` / ``guild_roles``, passed in by the RPC layer, which holds the broker.
GuildReader = Callable[[str], Awaitable[list[dict[str, Any]]]]

_tournaments = TournamentRepository()
_settings = TournamentVoiceSettingsRepository()
_channels = TournamentVoiceChannelRepository()


def _settings_of(row: models.TournamentVoiceSettings | None) -> voice_schemas.VoiceSettings:
    if row is None:
        return voice_schemas.VoiceSettings()
    return voice_schemas.VoiceSettings(
        enabled=row.enabled,
        private=row.private,
        early_teams=row.early_teams,
        category_id=str(row.category_id) if row.category_id is not None else None,
        staff_role_ids=[str(role_id) for role_id in row.staff_role_ids],
    )


async def _tournament(session: AsyncSession, tournament_id: int) -> models.Tournament:
    tournament = await _tournaments.get(session, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")
    return tournament


async def _settings_row(session: AsyncSession, tournament_id: int) -> models.TournamentVoiceSettings | None:
    return await _settings.for_tournament(session, tournament_id)


async def status_of(session: AsyncSession, tournament_id: int) -> voice_schemas.VoiceStatus:
    """The settings, the plan's channels joined with the bot's rows by ``slot_key``, and the bot's last report."""
    await _tournament(session, tournament_id)
    row = await _settings_row(session, tournament_id)
    plan = await build_voice_plan(session, tournament_id)
    made = {channel.slot_key: channel for channel in await _channels.for_tournament(session, tournament_id)}
    channels = [
        voice_schemas.VoiceChannelStatus(
            slot_key=planned.slot_key,
            kind=planned.kind,
            name=planned.name,
            discord_channel_id=_snowflake(made[planned.slot_key]) if planned.slot_key in made else None,
            status=made[planned.slot_key].status if planned.slot_key in made else "planned",
        )
        for planned in plan.channels
    ]
    planned_keys = {planned.slot_key for planned in plan.channels}
    channels += [
        voice_schemas.VoiceChannelStatus(
            slot_key=channel.slot_key, kind=channel.kind, discord_channel_id=_snowflake(channel), status=channel.status
        )
        for channel in made.values()
        if channel.slot_key not in planned_keys
    ]
    return voice_schemas.VoiceStatus(
        settings=_settings_of(row),
        guild_linked=plan.guild_id is not None,
        channels=channels,
        warnings=[voice_schemas.VoiceWarning.model_validate(w.model_dump()) for w in plan.warnings],
        sync_issues=[voice_schemas.VoiceSyncIssue.model_validate(i) for i in (row.sync_issues if row else [])],
        last_synced_at=row.last_synced_at if row else None,
    )


def _snowflake(channel: models.TournamentVoiceChannel) -> str | None:
    return str(channel.discord_channel_id) if channel.discord_channel_id is not None else None


async def _check_discord_ids(
    session: AsyncSession,
    tournament: models.Tournament,
    stored: voice_schemas.VoiceSettings,
    body: voice_schemas.VoiceSettings,
    *,
    list_channels: GuildReader,
    list_roles: GuildReader,
) -> None:
    """A newly set category or role must belong to the workspace's guild; unchanged ids need no Discord."""
    category = body.category_id if body.category_id != stored.category_id else None
    roles = set(body.staff_role_ids) - set(stored.staff_role_ids)
    if category is None and not roles:
        return
    guild_id = await session.scalar(
        sa.select(models.Workspace.discord_guild_id).where(models.Workspace.id == tournament.workspace_id)
    )
    if not guild_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="discord_guild_not_linked")
    try:
        if category is not None and not any(
            str(channel.get("id")) == category and channel.get("type") == "category"
            for channel in await list_channels(guild_id)
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="discord_category_not_in_guild"
            )
        if roles and not roles <= {str(role.get("id")) for role in await list_roles(guild_id)}:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="discord_role_not_in_guild")
    except DiscordError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="discord_unavailable") from exc


async def save_settings(
    session: AsyncSession,
    tournament_id: int,
    body: voice_schemas.VoiceSettings,
    *,
    list_channels: GuildReader,
    list_roles: GuildReader,
) -> voice_schemas.VoiceStatus:
    """Validate, upsert, request a sync and return the new status."""
    tournament = await _tournament(session, tournament_id)
    row = await _settings_row(session, tournament_id)
    await _check_discord_ids(
        session, tournament, _settings_of(row), body, list_channels=list_channels, list_roles=list_roles
    )
    values = {
        "enabled": body.enabled,
        "private": body.private,
        "early_teams": body.early_teams,
        "category_id": int(body.category_id) if body.category_id else None,
        "staff_role_ids": [int(role_id) for role_id in dict.fromkeys(body.staff_role_ids)],
    }
    await _settings.upsert(session, tournament_id, values)
    await enqueue_tournament_voice_sync(session, tournament)
    await session.commit()
    return await status_of(session, tournament_id)


async def request_sync(session: AsyncSession, tournament_id: int) -> voice_schemas.VoiceStatus:
    await enqueue_tournament_voice_sync(session, await _tournament(session, tournament_id))
    await session.commit()
    return await status_of(session, tournament_id)
