"""RPC-callable player-linking flows (no FastAPI Request/Depends).

Faithful ports of the player route bodies in ``src/routes/player.py`` so the
link/unlink/list/set-primary logic runs from the typed-RPC handlers in serve.py
with identical 404 semantics. ``fastapi.HTTPException`` remains the error vehicle
the RPC envelope maps; a later phase removes it.
"""

from __future__ import annotations

from shared.core.errors import BaseAPIException as HTTPException
from shared.core import http_status as status
from loguru import logger
from shared.models.user import User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src import models, schemas
from src.services.player_link_service import PlayerLinkService


async def link_player(
    session: AsyncSession,
    current_user: models.AuthUser,
    link_data: schemas.PlayerLinkRequest,
) -> schemas.PlayerLinkResponse:
    """Link a game player to the current auth user."""
    logger.info(f"Linking player {link_data.player_id} to user {current_user.username}")

    player_link = await PlayerLinkService.link_player(session, current_user, link_data.player_id, link_data.is_primary)

    result = await session.execute(select(User).where(User.id == link_data.player_id))
    player = result.scalar_one()

    linked_player = schemas.LinkedPlayer(
        player_id=player.id,
        player_name=player.name,
        is_primary=player_link.is_primary,
        linked_at=player_link.created_at.isoformat(),
    )

    return schemas.PlayerLinkResponse(message="Player linked successfully", player=linked_player)


async def unlink_player(
    session: AsyncSession,
    current_user: models.AuthUser,
    player_id: int,
) -> None:
    """Unlink a game player from the current auth user."""
    logger.info(f"Unlinking player {player_id} from user {current_user.username}")
    await PlayerLinkService.unlink_player(session, current_user, player_id)


async def get_linked_players(
    session: AsyncSession,
    current_user: models.AuthUser,
) -> list[schemas.LinkedPlayer]:
    """Get all linked players for the current auth user."""
    player_links = await PlayerLinkService.get_linked_players(session, current_user)

    result: list[schemas.LinkedPlayer] = []
    for link in player_links:
        player_result = await session.execute(select(User).where(User.id == link.player_id))
        player = player_result.scalar_one()

        result.append(
            schemas.LinkedPlayer(
                player_id=player.id,
                player_name=player.name,
                is_primary=link.is_primary,
                linked_at=link.created_at.isoformat(),
            )
        )

    return result


async def set_primary_player(
    session: AsyncSession,
    current_user: models.AuthUser,
    player_id: int,
) -> dict:
    """Set a linked player as primary for the current auth user."""
    logger.info(f"Setting player {player_id} as primary for user {current_user.username}")

    result = await session.execute(
        select(models.AuthUserPlayer).where(
            models.AuthUserPlayer.auth_user_id == current_user.id, models.AuthUserPlayer.player_id == player_id
        )
    )
    target_link = result.scalar_one_or_none()
    if target_link is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Player link not found",
        )

    result = await session.execute(
        select(models.AuthUserPlayer).where(
            models.AuthUserPlayer.auth_user_id == current_user.id,
            models.AuthUserPlayer.is_primary.is_(True),
        )
    )
    for link in result.scalars():
        link.is_primary = False

    target_link.is_primary = True

    await session.commit()

    return {"message": "Primary player updated successfully"}
