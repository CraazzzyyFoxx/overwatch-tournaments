"""Player linking service with ownership checks."""

from collections.abc import Iterable

from fastapi import HTTPException, status
from loguru import logger
from shared.models.oauth import OAuthConnection
from shared.models.user import User, UserBattleTag, UserDiscord
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src import models


def _normalized(values: Iterable[str | None]) -> set[str]:
    return {value.strip().casefold() for value in values if value and value.strip()}


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
        result = await session.execute(select(User).where(User.id == player_id))
        player = result.scalar_one_or_none()
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

            result = await session.execute(select(UserDiscord).where(UserDiscord.user_id == player_id))
            player_discord_names = _normalized([discord.name for discord in result.scalars().all()])

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

            result = await session.execute(select(UserBattleTag).where(UserBattleTag.user_id == player_id))
            player_battletags = _normalized([battle_tag.battle_tag for battle_tag in result.scalars().all()])

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
    ) -> models.AuthUserPlayer:
        await PlayerLinkService._get_player(session, player_id)
        await PlayerLinkService._verify_player_ownership(session, current_user.id, player_id)

        return await PlayerLinkService._link_player_to_auth_user(
            session,
            auth_user_id=current_user.id,
            player_id=player_id,
            is_primary=is_primary,
        )

    @staticmethod
    async def _link_player_to_auth_user(
        session: AsyncSession,
        *,
        auth_user_id: int,
        player_id: int,
        is_primary: bool,
    ) -> models.AuthUserPlayer:
        await PlayerLinkService._get_player(session, player_id)

        result = await session.execute(
            select(models.AuthUserPlayer).where(models.AuthUserPlayer.player_id == player_id)
        )
        existing_global_link = result.scalar_one_or_none()
        if existing_global_link and existing_global_link.auth_user_id != auth_user_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Player is already linked to another account",
            )

        result = await session.execute(
            select(models.AuthUserPlayer).where(
                models.AuthUserPlayer.auth_user_id == auth_user_id,
                models.AuthUserPlayer.player_id == player_id,
            )
        )
        existing_user_link = result.scalar_one_or_none()

        if existing_user_link:
            if is_primary and not existing_user_link.is_primary:
                result = await session.execute(
                    select(models.AuthUserPlayer).where(models.AuthUserPlayer.auth_user_id == auth_user_id)
                )
                for link in result.scalars().all():
                    link.is_primary = link.player_id == player_id
                await session.commit()
            return existing_user_link

        # First link is always primary.
        result = await session.execute(
            select(models.AuthUserPlayer).where(models.AuthUserPlayer.auth_user_id == auth_user_id)
        )
        existing_links = result.scalars().all()
        final_is_primary = is_primary or len(existing_links) == 0

        if final_is_primary:
            for link in existing_links:
                link.is_primary = False

        player_link = models.AuthUserPlayer(
            auth_user_id=auth_user_id,
            player_id=player_id,
            is_primary=final_is_primary,
        )
        session.add(player_link)
        await session.commit()
        await session.refresh(player_link)

        logger.info(f"Linked player {player_id} to auth user {auth_user_id}")
        return player_link

    @staticmethod
    async def admin_link_player(
        session: AsyncSession,
        auth_user_id: int,
        player_id: int,
        is_primary: bool,
    ) -> models.AuthUserPlayer:
        return await PlayerLinkService._link_player_to_auth_user(
            session,
            auth_user_id=auth_user_id,
            player_id=player_id,
            is_primary=is_primary,
        )

    @staticmethod
    async def unlink_player(
        session: AsyncSession,
        current_user: models.AuthUser,
        player_id: int,
    ) -> None:
        await PlayerLinkService._unlink_player_from_auth_user(
            session,
            auth_user_id=current_user.id,
            player_id=player_id,
        )

    @staticmethod
    async def _unlink_player_from_auth_user(
        session: AsyncSession,
        *,
        auth_user_id: int,
        player_id: int,
    ) -> None:
        result = await session.execute(
            select(models.AuthUserPlayer).where(
                models.AuthUserPlayer.auth_user_id == auth_user_id,
                models.AuthUserPlayer.player_id == player_id,
            )
        )
        player_link = result.scalar_one_or_none()
        if player_link is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Player link not found",
            )

        was_primary = player_link.is_primary
        await session.delete(player_link)

        if was_primary:
            result = await session.execute(
                select(models.AuthUserPlayer)
                .where(models.AuthUserPlayer.auth_user_id == auth_user_id)
                .order_by(models.AuthUserPlayer.created_at.asc())
            )
            next_link = result.scalars().first()
            if next_link is not None:
                next_link.is_primary = True

        await session.commit()
        logger.info(f"Unlinked player {player_id} from auth user {auth_user_id}")

    @staticmethod
    async def admin_unlink_player(
        session: AsyncSession,
        auth_user_id: int,
        player_id: int,
    ) -> None:
        await PlayerLinkService._unlink_player_from_auth_user(
            session,
            auth_user_id=auth_user_id,
            player_id=player_id,
        )

    @staticmethod
    async def get_linked_players(session: AsyncSession, current_user: models.AuthUser) -> list[models.AuthUserPlayer]:
        result = await session.execute(
            select(models.AuthUserPlayer)
            .where(models.AuthUserPlayer.auth_user_id == current_user.id)
            .order_by(models.AuthUserPlayer.is_primary.desc(), models.AuthUserPlayer.created_at.asc())
        )
        return list(result.scalars().all())
