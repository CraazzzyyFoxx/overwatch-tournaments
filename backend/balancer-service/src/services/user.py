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


async def find_users_by_battle_tags(
    session: AsyncSession, battle_tags: list[str]
) -> dict[str, models.User]:
    """Batch equivalent of :func:`find_by_battle_tag` for a set of tags.

    Resolves every tag in at most two queries (name pass, then battlenet social
    account pass) instead of the 2-4 SELECTs :func:`find_by_battle_tag` issues
    per name — this is what lets ``bulk_create_from_balancer`` avoid its N+1 fan
    of per-player lookups (review H12). Matching precedence mirrors
    ``find_by_battle_tag``: an in-game/``initcap`` name match wins over a social
    handle match. Relations are intentionally not eager-loaded (callers use only
    ``.id``).
    """
    tags = {tag for tag in battle_tags if tag}
    if not tags:
        return {}
    tag_list = list(tags)
    resolved: dict[str, models.User] = {}

    # Pass 1: direct in-game name / initcap(name). Select the DB-computed
    # ``initcap`` value so we can map each matched row back to its tag exactly.
    name_query = sa.select(
        models.User,
        models.User.name.label("raw_name"),
        sa.func.initcap(models.User.name).label("initcap_name"),
    ).where(
        sa.or_(
            models.User.name.in_(tag_list),
            sa.func.initcap(models.User.name).in_(tag_list),
        )
    )
    for user, raw_name, initcap_name in (await session.execute(name_query)).unique().all():
        for candidate in (raw_name, initcap_name):
            if candidate in tags:
                resolved.setdefault(candidate, user)

    # Pass 2: battlenet social account (normalized handle or in-game name part),
    # only for tags not already resolved by name.
    remaining = [tag for tag in tag_list if tag not in resolved]
    if remaining:
        norm_to_tag = {normalize_social_handle(SocialProvider.BATTLENET, tag): tag for tag in remaining}
        lower_to_tag = {tag.lower(): tag for tag in remaining}
        bt_query = (
            sa.select(
                models.User,
                models.SocialAccount.username_normalized,
                _battlenet_name_part().label("name_part"),
            )
            .join(models.SocialAccount, models.User.id == models.SocialAccount.user_id)
            .where(
                models.SocialAccount.provider == SocialProvider.BATTLENET,
                sa.or_(
                    models.SocialAccount.username_normalized.in_(list(norm_to_tag.keys())),
                    _battlenet_name_part().in_(list(lower_to_tag.keys())),
                ),
            )
        )
        for user, username_normalized, name_part in (await session.execute(bt_query)).unique().all():
            tag = norm_to_tag.get(username_normalized) or lower_to_tag.get(name_part)
            if tag is not None:
                resolved.setdefault(tag, user)

    return resolved


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
