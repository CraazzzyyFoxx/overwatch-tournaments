"""Simplified user service for balancer-service.

Provides the subset of user operations needed by the balancer admin:
find_by_csv, find_by_battle_tag, and create (upsert flow).
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from src import models
from src.schemas.user import UserCSV

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


async def find_by_csv(session: AsyncSession, data_in: UserCSV) -> models.User | None:
    """Find a user by battle tag, discord nick, twitch nick, or smurf tags."""
    clauses = []
    if data_in.battle_tag:
        clauses.append(models.UserBattleTag.battle_tag == data_in.battle_tag)
        clauses.append(sa.func.initcap(models.UserBattleTag.battle_tag) == data_in.battle_tag)
    if data_in.discord:
        clauses.append(models.UserDiscord.name == data_in.discord)

    query = (
        sa.select(models.User)
        .join(models.UserDiscord, models.User.id == models.UserDiscord.user_id, isouter=True)
        .join(models.UserBattleTag, models.User.id == models.UserBattleTag.user_id)
        .where(
            sa.or_(
                sa.or_(
                    models.User.name == data_in.battle_tag,
                    models.User.name == data_in.battle_tag.capitalize(),
                    sa.func.initcap(models.User.name) == data_in.battle_tag,
                ),
                sa.or_(*clauses),
            )
        )
    )
    result = await session.scalars(query)
    player = result.unique().first()
    if player:
        return player

    if data_in.twitch:
        twitch_query = (
            sa.select(models.User)
            .join(models.UserTwitch, models.User.id == models.UserTwitch.user_id)
            .where(
                sa.or_(
                    models.UserTwitch.name == data_in.twitch,
                    sa.func.initcap(models.UserTwitch.name) == data_in.twitch,
                    models.UserTwitch.name == data_in.twitch.capitalize(),
                )
            )
        )
        result_by_twitch = await session.scalars(twitch_query)
        player_by_twitch = result_by_twitch.unique().first()
        if player_by_twitch:
            return player_by_twitch

    if data_in.smurfs:
        smurf_clauses = []
        for smurf in data_in.smurfs:
            smurf_clauses.append(models.UserBattleTag.battle_tag == smurf)
            smurf_clauses.append(sa.func.initcap(models.UserBattleTag.battle_tag) == smurf)
        smurf_query = (
            sa.select(models.User)
            .join(models.UserBattleTag, models.User.id == models.UserBattleTag.user_id)
            .where(sa.or_(*smurf_clauses))
        )
        result_by_smurf = await session.scalars(smurf_query)
        return result_by_smurf.unique().first()

    return None


async def _get_with_relations(session: AsyncSession, user_id: int) -> models.User | None:
    """Load a user with battle_tag, discord, and twitch relationships."""
    result = await session.execute(
        sa.select(models.User)
        .where(models.User.id == user_id)
        .options(
            joinedload(models.User.battle_tag),
            joinedload(models.User.discord),
            joinedload(models.User.twitch),
        )
    )
    return result.unique().scalar_one_or_none()


async def find_by_battle_tag(
    session: AsyncSession,
    battle_tag: str,
    entities: list[str],  # noqa: ARG001 — kept for API compatibility
) -> models.User | None:
    """Find a user by battle tag (name field or UserBattleTag records)."""
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
        .join(models.UserBattleTag, models.User.id == models.UserBattleTag.user_id)
        .where(
            sa.or_(
                models.UserBattleTag.battle_tag == battle_tag,
                sa.func.initcap(models.UserBattleTag.battle_tag) == battle_tag,
                sa.func.lower(models.UserBattleTag.battle_tag) == battle_tag,
                models.UserBattleTag.name == battle_tag,
                sa.func.initcap(models.UserBattleTag.name) == battle_tag,
                sa.func.lower(models.UserBattleTag.name) == battle_tag,
            )
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


async def _get_battle_tag(session: AsyncSession, battle_tag: str) -> models.UserBattleTag | None:
    result = await session.execute(
        sa.select(models.UserBattleTag).where(
            sa.or_(
                models.UserBattleTag.battle_tag == battle_tag,
                sa.func.initcap(models.UserBattleTag.battle_tag) == battle_tag,
            )
        )
    )
    return result.unique().first()


async def _get_discord(session: AsyncSession, discord: str) -> models.UserDiscord | None:
    result = await session.execute(
        sa.select(models.UserDiscord).where(models.UserDiscord.name == discord)
    )
    return result.unique().first()


async def _get_twitch(session: AsyncSession, twitch: str) -> models.UserTwitch | None:
    result = await session.execute(
        sa.select(models.UserTwitch).where(models.UserTwitch.name == twitch)
    )
    return result.unique().first()


async def _create_battle_tag(session: AsyncSession, user: models.User, *, battle_tag: str) -> None:
    try:
        name, tag = battle_tag.split("#")
    except ValueError:
        return
    session.add(models.UserBattleTag(user_id=user.id, battle_tag=battle_tag, name=name, tag=tag))
    await session.commit()


async def _create_discord(session: AsyncSession, user: models.User, *, discord: str) -> None:
    session.add(models.UserDiscord(user_id=user.id, name=discord))
    await session.commit()


async def _create_twitch(session: AsyncSession, user: models.User, *, twitch: str) -> None:
    session.add(models.UserTwitch(user_id=user.id, name=twitch))
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

        existing_tags = {bt.battle_tag for bt in (user.battle_tag or [])}
        for tag in {data_in.battle_tag, *data_in.smurfs}:
            if tag and tag not in existing_tags and not await _get_battle_tag(session, tag):
                await _create_battle_tag(session, user, battle_tag=tag)

        existing_discords = {d.name for d in (user.discord or [])}
        if data_in.discord and data_in.discord not in existing_discords:
            if not await _get_discord(session, data_in.discord):
                await _create_discord(session, user, discord=data_in.discord)

        existing_twitches = {t.name for t in (user.twitch or [])}
        if data_in.twitch and data_in.twitch not in existing_twitches:
            if not await _get_twitch(session, data_in.twitch):
                await _create_twitch(session, user, twitch=data_in.twitch)

        user.name = data_in.battle_tag
        await session.commit()

    return await _get_with_relations(session, user.id)  # type: ignore[return-value]
