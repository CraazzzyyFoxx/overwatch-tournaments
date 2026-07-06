"""Player linking service with ownership checks.

Single-link model (identity/workspace refactor): a player↔auth-user link is
stored as ``players.user.auth_user_id`` (nullable, unique FK to ``auth.user.id``)
rather than the former ``auth.user_player`` M2M table. Because the FK is unique,
an auth user links to at most one player, so the historical ``is_primary``
bookkeeping is meaningless. The ``is_primary`` parameter is kept on the public
signatures purely as a transition shim so the RPC wire schema, gateway, and
frontend do not have to change in this task; it is ignored internally and every
returned/linked player is treated as primary. Removing it from the wire schema
is later work.
"""

from collections.abc import Iterable

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.core.social import SocialProvider
from shared.models.identity.auth_user import AuthUser
from shared.models.identity.oauth import OAuthConnection
from shared.models.identity.social import SocialAccount
from shared.models.identity.user import User
from shared.models.tenancy.workspace import WorkspaceMember
from shared.rbac import assign_default_member_role_if_roleless, workspace_names_blocking_player_unlink
from src import models


def _normalized(values: Iterable[str | None]) -> set[str]:
    return {value.strip().casefold() for value in values if value and value.strip()}


async def ensure_player_for_auth_user(session: AsyncSession, auth_user: AuthUser) -> User:
    """Idempotently provision the ``players.user`` identity backbone.

    Returns the existing linked player (via ``User.auth_user_id``) if one
    already exists, else creates a new bare player (name = username/email,
    no battletag yet — that is reconciled later at registration) and flushes
    it so the caller can rely on ``player.id`` before commit.

    Call this on every signup path (password + OAuth) right after the new
    ``auth.user`` row is flushed. Idempotency covers "OAuth existing user
    logs in again" — calling this more than once for the same auth_user is
    always safe and never creates a duplicate player.
    """
    existing = await session.scalar(select(User).where(User.auth_user_id == auth_user.id))
    if existing is not None:
        return existing

    player = User(name=auth_user.username or auth_user.email, auth_user_id=auth_user.id)
    session.add(player)
    await session.flush()
    return player


class PlayerLinkService:
    """Operations for linking auth users to game players."""

    @staticmethod
    async def _get_oauth_connections(
        session: AsyncSession,
        auth_user_id: int,
    ) -> tuple[OAuthConnection | None, OAuthConnection | None]:
        result = await session.execute(
            select(OAuthConnection).where(
                OAuthConnection.auth_user_id == auth_user_id,
                OAuthConnection.provider.in_(["discord", "battlenet"]),
            )
        )
        connections = result.scalars().all()
        discord_conn = next((conn for conn in connections if conn.provider == "discord"), None)
        battlenet_conn = next((conn for conn in connections if conn.provider == "battlenet"), None)

        if discord_conn is None and battlenet_conn is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Link Discord or Battle.net OAuth account before linking a player",
            )

        return discord_conn, battlenet_conn

    @staticmethod
    async def _get_player(session: AsyncSession, player_id: int) -> User:
        player = await session.get(User, player_id)
        if player is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Player not found",
            )
        return player

    @staticmethod
    async def _verify_player_ownership(session: AsyncSession, auth_user_id: int, player_id: int) -> None:
        discord_conn, battlenet_conn = await PlayerLinkService._get_oauth_connections(session, auth_user_id)

        discord_match = False
        battlenet_match = False

        if discord_conn is not None:
            oauth_names = _normalized(
                (
                    discord_conn.username,
                    discord_conn.display_name,
                    discord_conn.email,
                    (discord_conn.provider_data or {}).get("username"),
                    (discord_conn.provider_data or {}).get("global_name"),
                )
            )

            result = await session.execute(
                select(SocialAccount.username).where(
                    SocialAccount.user_id == player_id,
                    SocialAccount.provider == SocialProvider.DISCORD,
                )
            )
            player_discord_names = _normalized(result.scalars().all())

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

            result = await session.execute(
                select(SocialAccount.username).where(
                    SocialAccount.user_id == player_id,
                    SocialAccount.provider == SocialProvider.BATTLENET,
                )
            )
            player_battletags = _normalized(result.scalars().all())

            if oauth_battletags and player_battletags and not oauth_battletags.isdisjoint(player_battletags):
                battlenet_match = True

        if not discord_match and not battlenet_match:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Discord or Battle.net account does not match selected player",
            )

    @staticmethod
    async def link_player(
        session: AsyncSession,
        current_user: models.AuthUser,
        player_id: int,
        is_primary: bool,
    ) -> User:
        """Link a game player to ``current_user`` after ownership verification.

        ``is_primary`` is accepted for wire compatibility but ignored (single
        link => always primary). Returns the linked ``players.user`` row.
        """
        await PlayerLinkService._verify_player_ownership(session, current_user.id, player_id)

        return await PlayerLinkService._link_player_to_auth_user(
            session,
            auth_user_id=current_user.id,
            player_id=player_id,
        )

    @staticmethod
    async def _link_player_to_auth_user(
        session: AsyncSession,
        *,
        auth_user_id: int,
        player_id: int,
    ) -> User:
        """Set ``players.user.auth_user_id`` for the single-link model.

        Idempotent when the player is already linked to the same auth user;
        rejects with 409 when it belongs to a different account.
        """
        player = await PlayerLinkService._get_player(session, player_id)

        if player.auth_user_id is not None and player.auth_user_id != auth_user_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Player is already linked to another account",
            )

        player.auth_user_id = auth_user_id
        await session.flush()
        # Autofill the baseline ``member`` role for every workspace this player is
        # already anchored to (tournament participation created the member rows
        # before the account existed). Now that the row is auth-linked it becomes
        # a visible RBAC member and must not be role-less. Additive/idempotent.
        await PlayerLinkService._autofill_member_roles_for_player(
            session, auth_user_id=auth_user_id, player_id=player_id
        )
        await session.commit()
        await session.refresh(player)

        logger.info(f"Linked player {player_id} to auth user {auth_user_id}")
        return player

    @staticmethod
    async def _autofill_member_roles_for_player(
        session: AsyncSession,
        *,
        auth_user_id: int,
        player_id: int,
    ) -> None:
        """Grant the baseline ``member`` role in each workspace where ``player_id``
        has a membership row but the (now-linked) auth user holds no role yet."""
        workspace_ids = (
            await session.scalars(select(WorkspaceMember.workspace_id).where(WorkspaceMember.player_id == player_id))
        ).all()
        for workspace_id in workspace_ids:
            await assign_default_member_role_if_roleless(session, user_id=auth_user_id, workspace_id=workspace_id)

    @staticmethod
    async def admin_link_player(
        session: AsyncSession,
        auth_user_id: int,
        player_id: int,
        is_primary: bool,
    ) -> User:
        """Admin link (no ownership check). ``is_primary`` accepted but ignored."""
        return await PlayerLinkService._link_player_to_auth_user(
            session,
            auth_user_id=auth_user_id,
            player_id=player_id,
        )

    @staticmethod
    async def unlink_player(
        session: AsyncSession,
        current_user: models.AuthUser,
        player_id: int,
    ) -> None:
        player = await PlayerLinkService._get_player(session, player_id)
        if player.auth_user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Player link not found",
            )
        await PlayerLinkService._unlink_player_from_auth_user(session, player_id=player_id)

    @staticmethod
    async def _unlink_player_from_auth_user(
        session: AsyncSession,
        *,
        player_id: int,
    ) -> None:
        """Clear ``players.user.auth_user_id`` for the single-link model.

        Refuses (409) when the auth user still holds a real workspace
        membership role: ``workspace_member`` is anchored on this player, so
        clearing the link would strand that membership row auth-less — hidden
        from the members list and unmanageable via the auth-keyed lookup. The
        409 names the blocking workspaces so the user knows which to leave
        first. Baseline ``player`` participation does not block the unlink (see
        ``workspace_names_blocking_player_unlink``).
        """
        player = await PlayerLinkService._get_player(session, player_id)
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
        player.auth_user_id = None
        await session.commit()
        logger.info(f"Unlinked player {player_id} from auth user {auth_user_id}")

    @staticmethod
    async def admin_unlink_player(
        session: AsyncSession,
        auth_user_id: int,
        player_id: int,
    ) -> None:
        """Admin unlink (no ownership check). ``auth_user_id`` accepted for
        signature compatibility; the single-link column is cleared regardless."""
        await PlayerLinkService._unlink_player_from_auth_user(session, player_id=player_id)

    @staticmethod
    async def get_linked_players(session: AsyncSession, current_user: models.AuthUser) -> list[User]:
        """Return the 0-or-1 player linked to ``current_user`` via
        ``players.user.auth_user_id`` (a list, for API-shape compatibility)."""
        player = await session.scalar(select(User).where(User.auth_user_id == current_user.id))
        return [player] if player is not None else []
