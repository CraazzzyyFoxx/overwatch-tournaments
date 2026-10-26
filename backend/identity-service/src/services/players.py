"""Player linking with ownership checks.

A player↔auth-user link is ``players.user.auth_user_id`` (nullable, unique FK to
``auth.user.id``), so an auth user links to at most one player, and every linked
player is reported as primary.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.core.social import SocialProvider, normalize_social_handle
from shared.models.identity.oauth import OAuthConnection
from shared.rbac import assign_default_member_role_if_roleless, workspace_names_blocking_player_unlink
from shared.repository import (
    OAuthConnectionRepository,
    SocialAccountRepository,
    UserRepository,
    WorkspaceMemberRepository,
)
from src import schemas
from src.services.session_cache import SessionCache, session_cache

__all__ = ("PlayerLinkService", "players")

#: Game sign-ons whose OAuth subject proves a stored game handle (``oauth_handle_candidates``).
_GAME_SIGN_ONS = (SocialProvider.RIOT, SocialProvider.STEAM)


def _normalized(values: Iterable[str | None]) -> set[str]:
    return {value.strip().casefold() for value in values if value and value.strip()}


def describe_link(player: models.User) -> dict[str, Any]:
    """Wire shape of a player link; ``is_primary`` is always True (one link per auth user)."""
    return {
        "player_id": player.id,
        "player_name": player.name,
        "is_primary": True,
        "linked_at": player.created_at.isoformat(),
    }


class PlayerLinkService:
    """Single-link model: ``players.user.auth_user_id``."""

    def __init__(
        self,
        *,
        players: UserRepository = UserRepository(),
        connections: OAuthConnectionRepository = OAuthConnectionRepository(),
        socials: SocialAccountRepository = SocialAccountRepository(),
        members: WorkspaceMemberRepository = WorkspaceMemberRepository(),
        cache: SessionCache = session_cache,
    ) -> None:
        self.players = players
        self.connections = connections
        self.socials = socials
        self.members = members
        self.cache = cache

    # -- lookups -----------------------------------------------------------

    async def _get_oauth_connections(
        self,
        session: AsyncSession,
        auth_user_id: int,
    ) -> tuple[OAuthConnection | None, OAuthConnection | None, list[OAuthConnection]]:
        connections = await self.connections.list_by_user_providers(
            session,
            auth_user_id=auth_user_id,
            providers=["discord", "battlenet", *_GAME_SIGN_ONS],
        )
        discord_conn = next((conn for conn in connections if conn.provider == "discord"), None)
        battlenet_conn = next((conn for conn in connections if conn.provider == "battlenet"), None)
        game_conns = [conn for conn in connections if conn.provider in _GAME_SIGN_ONS]

        if discord_conn is None and battlenet_conn is None and not game_conns:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Link Discord, Battle.net, Riot or Steam OAuth account before linking a player",
            )

        return discord_conn, battlenet_conn, game_conns

    async def _get_player(self, session: AsyncSession, player_id: int) -> models.User:
        player = await self.players.get(session, player_id)
        if player is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Player not found",
            )
        return player

    # -- ownership ---------------------------------------------------------

    async def _verify_ownership(self, session: AsyncSession, auth_user_id: int, player_id: int) -> None:
        """Proof by unique handles only: Discord ``username``, BattleTag, Riot ID, Steam account id.

        A display name (Discord ``global_name``, a persona name) or an email is
        free text anyone can set to someone else's, so it proves nothing.
        """
        discord_conn, battlenet_conn, game_conns = await self._get_oauth_connections(session, auth_user_id)

        discord_match = False
        battlenet_match = False

        if discord_conn is not None:
            oauth_names = _normalized((discord_conn.username, (discord_conn.provider_data or {}).get("username")))
            player_discord_names = _normalized(
                await self.socials.list_handles(session, user_id=player_id, provider=SocialProvider.DISCORD)
            )
            if player_discord_names and not oauth_names.isdisjoint(player_discord_names):
                discord_match = True

        if battlenet_conn is not None:
            oauth_battletags = _normalized(
                (
                    battlenet_conn.username,
                    battlenet_conn.display_name,
                    (battlenet_conn.provider_data or {}).get("battletag"),
                    (battlenet_conn.provider_data or {}).get("battle_tag"),
                    (battlenet_conn.provider_data or {}).get("preferred_username"),
                )
            )
            player_battletags = _normalized(
                await self.socials.list_handles(session, user_id=player_id, provider=SocialProvider.BATTLENET)
            )
            if oauth_battletags and player_battletags and not oauth_battletags.isdisjoint(player_battletags):
                battlenet_match = True

        game_match = False
        for conn in game_conns:
            oauth_ids = {normalize_social_handle(conn.provider, conn.username)} if conn.username else set()
            player_ids = {
                normalize_social_handle(conn.provider, handle)
                for handle in await self.socials.list_handles(session, user_id=player_id, provider=conn.provider)
            }
            game_match = game_match or bool(oauth_ids & player_ids)

        if not discord_match and not battlenet_match and not game_match:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Discord, Battle.net, Riot or Steam account does not match selected player",
            )

    # -- storage -----------------------------------------------------------

    async def _link_to_auth_user(
        self,
        session: AsyncSession,
        *,
        auth_user_id: int,
        player_id: int,
    ) -> models.User:
        """Set ``players.user.auth_user_id`` for the single-link model.

        Idempotent when the player is already linked to the same auth user;
        rejects with 409 when it belongs to a different account.
        """
        player = await self._get_player(session, player_id)

        if player.auth_user_id is not None and player.auth_user_id != auth_user_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Player is already linked to another account",
            )

        await self.players.link_auth_user(session, player, auth_user_id)
        # Autofill the baseline ``member`` role for every workspace this player is
        # already anchored to (tournament participation created the member rows
        # before the account existed). Now that the row is auth-linked it becomes
        # a visible RBAC member and must not be role-less. Additive/idempotent.
        await self._autofill_member_roles(session, auth_user_id=auth_user_id, player_id=player_id)
        await session.commit()
        await session.refresh(player)
        # The account now holds the player's workspace memberships.
        await self.cache.invalidate_rbac(auth_user_id)
        logger.info(f"Linked player {player_id} to auth user {auth_user_id}")
        return player

    async def _autofill_member_roles(
        self,
        session: AsyncSession,
        *,
        auth_user_id: int,
        player_id: int,
    ) -> None:
        """Grant the baseline ``member`` role in each workspace where ``player_id``
        has a membership row but the (now-linked) auth user holds no role yet."""
        for workspace_id in await self.members.workspace_ids_for_player(session, player_id):
            await assign_default_member_role_if_roleless(session, user_id=auth_user_id, workspace_id=workspace_id)

    async def _unlink_from_auth_user(self, session: AsyncSession, *, player_id: int) -> None:
        """Clear ``players.user.auth_user_id`` for the single-link model.

        Refuses (409) when the auth user still holds a real workspace
        membership role: ``workspace_member`` is anchored on this player, so
        clearing the link would strand that membership row auth-less — hidden
        from the members list and unmanageable via the auth-keyed lookup. The
        409 names the blocking workspaces so the user knows which to leave
        first. Baseline ``player`` participation does not block the unlink (see
        ``workspace_names_blocking_player_unlink``).
        """
        player = await self._get_player(session, player_id)
        auth_user_id = player.auth_user_id
        if auth_user_id is None:
            return  # already unlinked — idempotent no-op
        blocking_workspaces = await workspace_names_blocking_player_unlink(session, user_id=auth_user_id)
        if blocking_workspaces:
            listed = ", ".join(blocking_workspaces)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot unlink this player: the account is a member of the "
                    f"following workspace(s): {listed}. Leave those workspaces first."
                ),
            )
        await self.players.link_auth_user(session, player, None)
        await session.commit()
        await self.cache.invalidate_rbac(auth_user_id)
        logger.info(f"Unlinked player {player_id} from auth user {auth_user_id}")

    # -- self-service ------------------------------------------------------

    async def link(
        self,
        session: AsyncSession,
        current_user: models.AuthUser,
        player_id: int,
    ) -> models.User:
        """Link a game player to ``current_user`` after ownership verification.

        Returns the linked ``players.user`` row.
        """
        await self._verify_ownership(session, current_user.id, player_id)
        return await self._link_to_auth_user(session, auth_user_id=current_user.id, player_id=player_id)

    async def unlink(self, session: AsyncSession, current_user: models.AuthUser, player_id: int) -> None:
        logger.info(f"Unlinking player {player_id} from user {current_user.username}")
        player = await self._get_player(session, player_id)
        if player.auth_user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Player link not found",
            )
        await self._unlink_from_auth_user(session, player_id=player_id)

    async def linked_players(self, session: AsyncSession, current_user: models.AuthUser) -> list[models.User]:
        """Return the 0-or-1 player linked to ``current_user`` via
        ``players.user.auth_user_id`` (a list, for API-shape compatibility)."""
        player = await self.players.get_by_auth_user_id(session, current_user.id)
        return [player] if player is not None else []

    # -- admin -------------------------------------------------------------

    async def admin_link(self, session: AsyncSession, auth_user_id: int, player_id: int) -> models.User:
        """Admin link (no ownership check)."""
        return await self._link_to_auth_user(session, auth_user_id=auth_user_id, player_id=player_id)

    async def admin_unlink(self, session: AsyncSession, player_id: int) -> None:
        """Admin unlink (no ownership check): clears the player's single-link column."""
        await self._unlink_from_auth_user(session, player_id=player_id)

    # -- RPC-facing wrappers ----------------------------------------------

    async def link_and_describe(
        self,
        session: AsyncSession,
        current_user: models.AuthUser,
        link_data: schemas.PlayerLinkRequest,
    ) -> schemas.PlayerLinkResponse:
        """Link a game player to the current auth user."""
        logger.info(f"Linking player {link_data.player_id} to user {current_user.username}")

        player = await self.link(session, current_user, link_data.player_id)
        return schemas.PlayerLinkResponse(
            message="Player linked successfully", player=schemas.LinkedPlayer(**describe_link(player))
        )

    async def linked_payload(
        self,
        session: AsyncSession,
        current_user: models.AuthUser,
    ) -> list[schemas.LinkedPlayer]:
        """Get all linked players for the current auth user."""
        return [
            schemas.LinkedPlayer(**describe_link(player)) for player in await self.linked_players(session, current_user)
        ]


players = PlayerLinkService()
