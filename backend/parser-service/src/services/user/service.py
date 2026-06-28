import typing

import sqlalchemy as sa
from loguru import logger
from shared.core.social import SocialProvider, normalize_social_handle
from shared.services import social_identity
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.strategy_options import _AbstractLoad

from src import models, schemas
from src.core import utils


def _battlenet_name_part() -> sa.ColumnElement[str]:
    """Lowercased in-game name (before ``#``) of a battlenet social account."""
    return sa.func.lower(sa.func.split_part(models.SocialAccount.username, "#", 1))


def user_entities(in_entities: list[str], child: typing.Any | None = None) -> list[_AbstractLoad]:
    entities = []
    # Unified identity source consumed by ``to_pydantic``. Loaded whenever any
    # identity entity token is requested (legacy ``battle_tag``/``discord``/
    # ``twitch`` tokens are still accepted for caller/API compatibility).
    if any(name in in_entities for name in ("social_accounts", "battle_tag", "discord", "twitch")):
        entities.append(utils.join_entity(child, models.User.social_accounts))
    return entities


async def get(session: AsyncSession, user_id: int, entities: list[str]) -> models.User | None:
    query = sa.select(models.User).options(*user_entities(entities)).where(sa.and_(models.User.id == user_id))
    result = await session.execute(query)
    return result.unique().scalar_one_or_none()


async def get_by_battle_tag(session: AsyncSession, battle_tag: str, entities: list[str]) -> models.User | None:
    query = (
        sa.select(models.User)
        .options(*user_entities(entities))
        .join(models.SocialAccount, models.User.id == models.SocialAccount.user_id)
        .where(
            models.SocialAccount.provider == SocialProvider.BATTLENET,
            models.SocialAccount.username_normalized
            == normalize_social_handle(SocialProvider.BATTLENET, battle_tag),
        )
    )
    result = await session.execute(query)
    return result.unique().scalar_one_or_none()


async def find_by_csv(session: AsyncSession, data_in: schemas.UserCSV) -> models.User | None:
    acc = models.SocialAccount

    # 1. Match by display name (case variants) or a battlenet/discord social account.
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
            .where(
                acc.provider == SocialProvider.BATTLENET,
                acc.username_normalized.in_(smurf_norms),
            )
        )
        return (await session.scalars(smurf_query)).unique().first()

    return None


async def find_by_battle_tag(session: AsyncSession, battle_tag: str, entities: list[str]) -> models.User | None:
    query = (
        sa.select(models.User)
        .options(*user_entities(entities))
        .where(
            sa.or_(
                models.User.name == battle_tag,
                sa.func.initcap(models.User.name) == battle_tag,
            )
        )
    )
    result = await session.scalars(query)
    user = result.unique().first()
    if user:
        return await get(session, user.id, ["battle_tag", "twitch", "discord"])

    # Match a battlenet social account by full normalized handle or by in-game
    # name part (case-insensitive), covering both "Name#1234" and "Name" inputs.
    battle_tag_query = (
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
    result_by_battle_tag = await session.scalars(battle_tag_query)
    user = result_by_battle_tag.unique().first()
    if user:
        return await get(session, user.id, ["battle_tag", "twitch", "discord"])

    return None


async def get_battle_tag(session: AsyncSession, battle_tag: str) -> models.SocialAccount | None:
    return await social_identity.find_by_handle(
        session, provider=SocialProvider.BATTLENET, username=battle_tag
    )


async def get_discord(session: AsyncSession, discord: str) -> models.SocialAccount | None:
    return await social_identity.find_by_handle(
        session, provider=SocialProvider.DISCORD, username=discord
    )


async def get_twitch(session: AsyncSession, twitch: str) -> models.SocialAccount | None:
    return await social_identity.find_by_handle(
        session, provider=SocialProvider.TWITCH, username=twitch
    )


async def get_all(session: AsyncSession, entities: list[str]) -> typing.Sequence[models.User]:
    query = sa.select(models.User).options(*user_entities(entities))
    result = await session.scalars(query)
    return result.unique().all()


async def create(
    session: AsyncSession,
    *,
    battle_tag: str,
    discord: str | None,
    twitch: str | None,
) -> models.User:
    player = models.User(name=battle_tag)
    session.add(player)
    await session.commit()
    logger.info(f"Player created [id={player.id} name={battle_tag}]")
    try:
        name, tag = battle_tag.split("#")
        await create_battle_tag(session, player, battle_tag=battle_tag, name=name, tag=tag)
    except ValueError:
        pass
    if discord:
        await create_discord(session, player, discord=discord)
    if twitch:
        await create_twitch(session, player, twitch=twitch)
    return await get(session, player.id, ["battle_tag", "twitch", "discord"])


async def create_battle_tag(
    session: AsyncSession,
    player: models.User,
    *,
    battle_tag: str,
    name: str | None = None,
    tag: str | None = None,
) -> models.SocialAccount:
    """Attach a battlenet identity to ``player`` (idempotent). ``name``/``tag`` are
    accepted for caller compatibility but derived from ``battle_tag`` on read."""
    account = await social_identity.upsert_social_account(
        session, user_id=player.id, provider=SocialProvider.BATTLENET, username=battle_tag
    )
    await session.commit()
    logger.info(f"Battle Tag created [tag={battle_tag}] for player [id={player.id} name={player.name}]")
    return account


async def create_discord(
    session: AsyncSession,
    player: models.User,
    *,
    discord: str,
) -> models.SocialAccount:
    account = await social_identity.upsert_social_account(
        session, user_id=player.id, provider=SocialProvider.DISCORD, username=discord
    )
    await session.commit()
    logger.info(f"Discord created [discord={discord}] for player [id={player.id} name={player.name}]")
    return account


async def update_discord(
    session: AsyncSession,
    discord: models.SocialAccount,
    *,
    name: str,
) -> models.SocialAccount:
    updated = await social_identity.update_social_account(
        session, account_id=discord.id, user_id=discord.user_id, username=name
    )
    await session.commit()
    logger.info(f"Discord updated [id={discord.id} name={name}]")
    return updated or discord


async def create_twitch(
    session: AsyncSession,
    player: models.User,
    *,
    twitch: str,
) -> models.SocialAccount:
    account = await social_identity.upsert_social_account(
        session, user_id=player.id, provider=SocialProvider.TWITCH, username=twitch
    )
    await session.commit()
    logger.info(f"Twitch created [twitch={twitch}] for player [id={player.id} name={player.name}]")
    return account


async def update_twitch(
    session: AsyncSession,
    twitch: models.SocialAccount,
    *,
    name: str,
) -> models.SocialAccount:
    updated = await social_identity.update_social_account(
        session, account_id=twitch.id, user_id=twitch.user_id, username=name
    )
    await session.commit()
    logger.info(f"Twitch updated [id={twitch.id} name={name}]")
    return updated or twitch


async def update(
    session: AsyncSession,
    user: models.User,
    *,
    name: str,
) -> models.User:
    user.name = name
    await session.commit()
    logger.info(f"Player updated [id={user.id} name={name}]")
    return user
