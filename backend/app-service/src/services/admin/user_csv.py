"""Bulk user creation from CSV / Google Sheets, relocated from parser-service.

Ports the parser ``services/user`` create-side helpers needed by the CSV import
(parser keeps its own copy — match-log processing still creates users there). The
read ``get`` is reused from app-service's existing user service.
"""

from __future__ import annotations

import csv
import re
from datetime import UTC, datetime

import sqlalchemy as sa
from loguru import logger
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from src import models, schemas
from src.core import config
from src.services.user import service as user_service

battle_tag_validator = re.compile(config.settings.battle_tag_regex, re.UNICODE)


# ─── Create-side user/identity service helpers (ported) ───────────────────────


async def _find_by_csv(session: AsyncSession, data_in: schemas.UserCSV) -> models.User | None:
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
                    (
                        sa.func.upper(sa.func.left(models.UserTwitch.name, 1)).cast(sa.String)
                        + sa.func.lower(sa.func.substring(models.UserTwitch.name, 2)).cast(sa.String)
                    )
                    == data_in.twitch.capitalize(),
                    sa.func.initcap(models.UserTwitch.name) == data_in.twitch,
                    models.UserTwitch.name == data_in.twitch.capitalize(),
                    (
                        sa.func.upper(sa.func.left(models.UserTwitch.name, 1)).cast(sa.String)
                        + sa.func.lower(sa.func.substring(models.UserTwitch.name, 2)).cast(sa.String)
                    )
                    == data_in.battle_tag,
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


async def _get_battle_tag(session: AsyncSession, battle_tag: str) -> models.UserBattleTag | None:
    query = sa.select(models.UserBattleTag).where(
        sa.or_(
            models.UserBattleTag.battle_tag == battle_tag,
            sa.func.initcap(models.UserBattleTag.battle_tag) == battle_tag,
        )
    )
    result = await session.execute(query)
    return result.unique().first()


async def _get_discord(session: AsyncSession, discord: str) -> models.UserDiscord | None:
    result = await session.execute(sa.select(models.UserDiscord).where(models.UserDiscord.name == discord))
    return result.unique().first()


async def _get_twitch(session: AsyncSession, twitch: str) -> models.UserTwitch | None:
    result = await session.execute(sa.select(models.UserTwitch).where(models.UserTwitch.name == twitch))
    return result.unique().first()


async def _create_battle_tag(
    session: AsyncSession, player: models.User, *, battle_tag: str, name: str, tag: str
) -> models.UserBattleTag:
    player_battle_tag = models.UserBattleTag(user_id=player.id, battle_tag=battle_tag, name=name, tag=tag)
    session.add(player_battle_tag)
    await session.commit()
    logger.info(f"Battle Tag created [tag={battle_tag}] for player [id={player.id} name={name}]")
    return player_battle_tag


async def _create_discord(session: AsyncSession, player: models.User, *, discord: str) -> models.UserDiscord:
    player_discord = models.UserDiscord(user_id=player.id, name=discord)
    session.add(player_discord)
    await session.commit()
    logger.info(f"Discord created [discord={discord}] for player [id={player.id} name={player.name}]")
    return player_discord


async def _update_discord(session: AsyncSession, discord: models.UserDiscord, *, name: str) -> models.UserDiscord:
    discord.name = name
    discord.updated_at = datetime.now(UTC)
    await session.commit()
    return discord


async def _create_twitch(session: AsyncSession, player: models.User, *, twitch: str) -> models.UserTwitch:
    player_twitch = models.UserTwitch(user_id=player.id, name=twitch)
    session.add(player_twitch)
    await session.commit()
    logger.info(f"Twitch created [twitch={twitch}] for player [id={player.id} name={player.name}]")
    return player_twitch


async def _update_twitch(session: AsyncSession, twitch: models.UserTwitch, *, name: str) -> models.UserTwitch:
    twitch.updated_at = datetime.now(UTC)
    twitch.name = name
    await session.commit()
    return twitch


async def _create_user(session: AsyncSession, *, battle_tag: str, discord: str | None, twitch: str | None) -> models.User:
    player = models.User(name=battle_tag)
    session.add(player)
    await session.commit()
    logger.info(f"Player created [id={player.id} name={battle_tag}]")
    try:
        name, tag = battle_tag.split("#")
        await _create_battle_tag(session, player, battle_tag=battle_tag, name=name, tag=tag)
    except ValueError:
        pass
    if discord:
        await _create_discord(session, player, discord=discord)
    if twitch:
        await _create_twitch(session, player, twitch=twitch)
    return await user_service.get(session, player.id, ["battle_tag", "twitch", "discord"])


async def _update_name(session: AsyncSession, user: models.User, *, name: str) -> models.User:
    user.name = name
    await session.commit()
    return user


# ─── create-or-ignore identity helpers (ported from parser flows) ─────────────


async def _create_or_ignore_battle_tags(session: AsyncSession, player: models.User, in_battle_tags: list[str]) -> None:
    battle_tags = [tag.battle_tag for tag in player.battle_tag]
    for battle_tag in set(in_battle_tags):
        if battle_tag and battle_tag not in battle_tags and not await _get_battle_tag(session, battle_tag):
            try:
                name, tag = battle_tag.split("#")
                await _create_battle_tag(session, player, battle_tag=battle_tag, name=name, tag=tag)
            except ValueError:
                pass


# ─── per-row create + bulk import (ported from parser flows) ──────────────────


async def _create_from_row(session: AsyncSession, data_in: schemas.UserCSV) -> models.User:
    player_data = await _find_by_csv(session, data_in)
    if not player_data:
        user = await _create_user(
            session,
            battle_tag=data_in.battle_tag,
            discord=data_in.discord,
            twitch=data_in.twitch,
        )
        await _create_or_ignore_battle_tags(session, user, [*data_in.smurfs, data_in.battle_tag])
    else:
        user = await user_service.get(session, player_data.id, ["battle_tag", "twitch", "discord"])
        await _create_or_ignore_battle_tags(session, user, [*data_in.smurfs, data_in.battle_tag])
        await _update_name(session, user, name=data_in.battle_tag)

        twitch_names = {twitch.name: twitch for twitch in user.twitch}
        discord_names = {discord.name: discord for discord in user.discord}

        if data_in.twitch:
            if data_in.twitch not in twitch_names:
                if not await _get_twitch(session, data_in.twitch):
                    await _create_twitch(session, user, twitch=data_in.twitch)
            else:
                await _update_twitch(session, twitch_names[data_in.twitch], name=data_in.twitch)
        if data_in.discord:
            if data_in.discord not in discord_names:
                if not await _get_discord(session, data_in.discord):
                    await _create_discord(session, user, discord=data_in.discord)
            else:
                await _update_discord(session, discord_names[data_in.discord], name=data_in.discord)

    return await user_service.get(session, user.id, ["battle_tag", "twitch", "discord"])


async def bulk_create_users_from_csv(
    session: AsyncSession,
    filename: str,
    data: list[str],
    start_row: int = 0,
    *,
    battle_tag_row: int,
    discord_row: int,
    twitch_row: int,
    smurf_row: int,
    delimiter: str = ",",
    has_discord: bool = True,
    has_smurf: bool = True,
    has_twitch: bool = True,
) -> None:
    file_reader = csv.reader(data, delimiter=delimiter)
    for index, row in enumerate(file_reader, 0):
        if index < start_row:
            continue
        battle_tag = row[battle_tag_row - 1].strip().replace(" #", "#").replace("# ", "#")
        twitch = row[twitch_row - 1].strip() if has_twitch else None
        discord = row[discord_row - 1].strip() if has_discord else None
        smurfs = row[smurf_row - 1] if has_smurf else ""

        try:
            payload = schemas.UserCSV(
                battle_tag=battle_tag_validator.findall(battle_tag)[0],
                discord=discord,
                twitch=twitch,
                smurfs=battle_tag_validator.findall(smurfs),
            )
        except (IndexError, ValidationError):
            logger.error(
                f"Invalid data in row {index + 1} of {filename}: "
                f"Battle Tag: {battle_tag}, Discord: {discord}, Twitch: {twitch}, Smurfs: {smurfs}"
            )
            continue

        await _create_from_row(session, payload)
