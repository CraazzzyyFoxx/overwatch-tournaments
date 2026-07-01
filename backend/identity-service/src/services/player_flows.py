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

    # Single-link model: ``link_player`` returns the linked ``players.user`` row.
    # ``is_primary`` is always True (one link per auth user).
    player = await PlayerLinkService.link_player(session, current_user, link_data.player_id, link_data.is_primary)

    linked_player = schemas.LinkedPlayer(
        player_id=player.id,
        player_name=player.name,
        is_primary=True,
        linked_at=player.created_at.isoformat(),
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
    # Single-link model: ``get_linked_players`` returns the 0-or-1
    # ``players.user`` row(s) linked via ``auth_user_id``.
    players = await PlayerLinkService.get_linked_players(session, current_user)

    return [
        schemas.LinkedPlayer(
            player_id=player.id,
            player_name=player.name,
            is_primary=True,
            linked_at=player.created_at.isoformat(),
        )
        for player in players
    ]


async def set_primary_player(
    session: AsyncSession,
    current_user: models.AuthUser,
    player_id: int,
) -> dict:
    """Set a linked player as primary for the current auth user.

    Single-link model (identity/workspace refactor): an auth user has at most
    one linked player (``players.user.auth_user_id``), so there is nothing to
    reassign. This is now validate-only — it confirms ``player_id`` is the
    caller's single linked player and returns success without any mutation. The
    endpoint is retained (no route/gateway churn); the wire response is
    unchanged.
    """
    logger.info(f"Setting player {player_id} as primary for user {current_user.username}")

    player = await session.scalar(select(User).where(User.auth_user_id == current_user.id))
    if player is None or player.id != player_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Player link not found",
        )

    return {"message": "Primary player updated successfully"}
