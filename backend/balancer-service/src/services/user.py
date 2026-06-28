"""Simplified user service for balancer-service.

Provides the subset of user operations needed by the balancer admin:
find_by_csv, find_by_battle_tag, and create (upsert flow).
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from shared.core.social import SocialProvider, normalize_social_handle
from shared.services import social_identity
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src import models
from src.schemas.user import UserCSV

logger = logging.getLogger(__name__)


def _battlenet_name_part() -> sa.ColumnElement[str]:
    """Lowercased in-game name (before ``#``) of a battlenet social account."""
    return sa.func.lower(sa.func.split_part(models.SocialAccount.username, "#", 1))


def _usernames(user: models.User, provider: str) -> set[str]:
    return {a.username for a in (user.social_accounts or []) if a.provider == provider}


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


async def find_by_csv(session: AsyncSession, data_in: UserCSV) -> models.User | None:
    """Find a user by battle tag, discord nick, twitch nick, or smurf tags."""
    acc = models.SocialAccount
    clauses = []
    if data_in.battle_tag:
        clauses.append(
            sa.and_(
                acc.provider == SocialProvider.BATTLENET,
                acc.username_normalized == normalize_social_handle(SocialProvider.BATTLENET, data_in.battle_tag),
            )
        )
        clauses.extend(
            [
                models.User.name == data_in.battle_tag,
                models.User.name == data_in.battle_tag.capitalize(),
                sa.func.initcap(models.User.name) == data_in.battle_tag,
            ]
        )
    if data_in.discord:
        clauses.append(
            sa.and_(
                acc.provider == SocialProvider.DISCORD,
                acc.username_normalized == normalize_social_handle(SocialProvider.DISCORD, data_in.discord),
            )
        )

    if clauses:
        query = (
            sa.select(models.User)
            .outerjoin(acc, models.User.id == acc.user_id)
            .where(sa.or_(*clauses))
        )
        player = (await session.scalars(query)).unique().first()
        if player:
            return player

    if data_in.twitch:
        twitch_query = (
            sa.select(models.User)
            .join(acc, models.User.id == acc.user_id)
            .where(
                acc.provider == SocialProvider.TWITCH,
                acc.username_normalized == normalize_social_handle(SocialProvider.TWITCH, data_in.twitch),
            )
        )
        player_by_twitch = (await session.scalars(twitch_query)).unique().first()
        if player_by_twitch:
            return player_by_twitch

    if data_in.smurfs:
        smurf_norms = [normalize_social_handle(SocialProvider.BATTLENET, smurf) for smurf in data_in.smurfs]
        smurf_query = (
            sa.select(models.User)
            .join(acc, models.User.id == acc.user_id)
            .where(acc.provider == SocialProvider.BATTLENET, acc.username_normalized.in_(smurf_norms))
        )
        return (await session.scalars(smurf_query)).unique().first()

    return None


async def _get_with_relations(session: AsyncSession, user_id: int) -> models.User | None:
    """Load a user with its unified social accounts."""
    result = await session.execute(
        sa.select(models.User)
        .where(models.User.id == user_id)
        .options(selectinload(models.User.social_accounts))
    )
    return result.unique().scalar_one_or_none()


async def find_by_battle_tag(
    session: AsyncSession,
    battle_tag: str,
    entities: list[str],  # noqa: ARG001 — kept for API compatibility
) -> models.User | None:
    """Find a user by battle tag (name field or battlenet social account)."""
    query = sa.select(models.User).where(
        sa.or_(
            models.User.name == battle_tag,
            sa.func.initcap(models.User.name) == battle_tag,
        )
    )
    result = await session.scalars(query)
    user = result.unique().first()
    if user:
        return await _get_with_relations(session, user.id)

    bt_query = (
        sa.select(models.User)
        .join(models.SocialAccount, models.User.id == models.SocialAccount.user_id)
        .where(
            models.SocialAccount.provider == SocialProvider.BATTLENET,
            sa.or_(
                models.SocialAccount.username_normalized
                == normalize_social_handle(SocialProvider.BATTLENET, battle_tag),
                _battlenet_name_part() == battle_tag.lower(),
            ),
        )
    )
    result_by_bt = await session.scalars(bt_query)
    user = result_by_bt.unique().first()
    if user:
        return await _get_with_relations(session, user.id)

    return None


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------


async def _get_battle_tag(session: AsyncSession, battle_tag: str) -> models.SocialAccount | None:
    return await social_identity.find_by_handle(
        session, provider=SocialProvider.BATTLENET, username=battle_tag
    )


async def _get_discord(session: AsyncSession, discord: str) -> models.SocialAccount | None:
    return await social_identity.find_by_handle(session, provider=SocialProvider.DISCORD, username=discord)


async def _get_twitch(session: AsyncSession, twitch: str) -> models.SocialAccount | None:
    return await social_identity.find_by_handle(session, provider=SocialProvider.TWITCH, username=twitch)


async def _create_battle_tag(session: AsyncSession, user: models.User, *, battle_tag: str) -> None:
    if "#" not in battle_tag:
        return
    await social_identity.upsert_social_account(
        session, user_id=user.id, provider=SocialProvider.BATTLENET, username=battle_tag
    )
    await session.commit()


async def _create_discord(session: AsyncSession, user: models.User, *, discord: str) -> None:
    await social_identity.upsert_social_account(
        session, user_id=user.id, provider=SocialProvider.DISCORD, username=discord
    )
    await session.commit()


async def _create_twitch(session: AsyncSession, user: models.User, *, twitch: str) -> None:
    await social_identity.upsert_social_account(
        session, user_id=user.id, provider=SocialProvider.TWITCH, username=twitch
    )
    await session.commit()


async def create(session: AsyncSession, data_in: UserCSV) -> models.User:
    """Create or upsert a user from a UserCSV payload."""
    existing = await find_by_csv(session, data_in)

    if existing is None:
        user = models.User(name=data_in.battle_tag)
        session.add(user)
        await session.commit()
        logger.info("User created [id=%s name=%s]", user.id, data_in.battle_tag)

        all_tags = list({data_in.battle_tag, *data_in.smurfs})
        for tag in all_tags:
            if tag and not await _get_battle_tag(session, tag):
                await _create_battle_tag(session, user, battle_tag=tag)
        if data_in.discord and not await _get_discord(session, data_in.discord):
            await _create_discord(session, user, discord=data_in.discord)
        if data_in.twitch and not await _get_twitch(session, data_in.twitch):
            await _create_twitch(session, user, twitch=data_in.twitch)
    else:
        user = await _get_with_relations(session, existing.id)  # type: ignore[assignment]

        existing_tags = _usernames(user, SocialProvider.BATTLENET)
        for tag in {data_in.battle_tag, *data_in.smurfs}:
            if tag and tag not in existing_tags and not await _get_battle_tag(session, tag):
                await _create_battle_tag(session, user, battle_tag=tag)

        existing_discords = _usernames(user, SocialProvider.DISCORD)
        if data_in.discord and data_in.discord not in existing_discords:
            if not await _get_discord(session, data_in.discord):
                await _create_discord(session, user, discord=data_in.discord)

        existing_twitches = _usernames(user, SocialProvider.TWITCH)
        if data_in.twitch and data_in.twitch not in existing_twitches:
            if not await _get_twitch(session, data_in.twitch):
                await _create_twitch(session, user, twitch=data_in.twitch)

        user.name = data_in.battle_tag
        await session.commit()

    return await _get_with_relations(session, user.id)  # type: ignore[return-value]
