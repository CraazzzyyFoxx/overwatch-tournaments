"""Admin routes for Discord channel sync configuration per tournament."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.core import auth, db
from src.schemas.admin.discord_channel import DiscordChannelRead, DiscordChannelUpsert

router = APIRouter(
    prefix="/tournaments",
    tags=["admin", "discord"],
)


@router.get(
    "/{tournament_id}/discord-channel",
    response_model=DiscordChannelRead | None,
)
async def get_discord_channel(
    tournament_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("discord_channel", "read")),
):
    """Get the Discord sync channel configured for this tournament, or null."""
    result = await session.execute(
        select(models.TournamentDiscordChannel).where(
            models.TournamentDiscordChannel.tournament_id == tournament_id
        )
    )
    return result.scalar_one_or_none()


@router.post(
    "/{tournament_id}/discord-channel",
    response_model=DiscordChannelRead,
)
async def upsert_discord_channel(
    tournament_id: int,
    data: DiscordChannelUpsert,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("discord_channel", "update")),
):
    """Create or update the Discord sync channel for a tournament."""
    # Verify tournament exists
    tournament = await session.get(models.Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")

    result = await session.execute(
        select(models.TournamentDiscordChannel).where(
            models.TournamentDiscordChannel.tournament_id == tournament_id
        )
    )
    channel = result.scalar_one_or_none()

    if channel is None:
        channel = models.TournamentDiscordChannel(tournament_id=tournament_id)
        session.add(channel)

    channel.guild_id = int(data.guild_id)
    channel.channel_id = int(data.channel_id)
    channel.channel_name = data.channel_name
    channel.is_active = data.is_active

    await session.commit()
    await session.refresh(channel)
    return channel


@router.delete(
    "/{tournament_id}/discord-channel",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_discord_channel(
    tournament_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("discord_channel", "delete")),
):
    """Remove the Discord sync channel configuration for a tournament."""
    result = await session.execute(
        delete(models.TournamentDiscordChannel).where(
            models.TournamentDiscordChannel.tournament_id == tournament_id
        )
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Discord channel not configured")
    await session.commit()
