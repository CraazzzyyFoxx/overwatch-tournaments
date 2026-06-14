import csv
import re
from datetime import UTC, datetime

from loguru import logger
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from src import models, schemas
from src.core import config, errors

from . import service

battle_tag_validator = re.compile(config.settings.battle_tag_regex, re.UNICODE)


async def to_pydantic(session: AsyncSession, user: models.User, entities: list[str]) -> schemas.UserRead:
    battle_tags: list[schemas.UserBattleTagRead] = []
    twitch: list[schemas.UserTwitchRead] = []
    discord: list[schemas.UserDiscordRead] = []

    unresolved = datetime(1, 1, 1, tzinfo=UTC)
    if "battle_tag" in entities:
        battle_tags = [
            schemas.UserBattleTagRead.model_validate(tag, from_attributes=True)
            for tag in user.battle_tag
        ]
    if "twitch" in entities:
        twitch = [
            schemas.UserTwitchRead.model_validate(twitch_identity, from_attributes=True)
            for twitch_identity in sorted(
                user.twitch,
                key=lambda identity: unresolved
                if identity.updated_at is None
                else identity.updated_at,
                reverse=True,
            )
        ]
    if "discord" in entities:
        discord = [
            schemas.UserDiscordRead.model_validate(discord_identity, from_attributes=True)
            for discord_identity in sorted(
                user.discord,
                key=lambda identity: unresolved
                if identity.updated_at is None
                else identity.updated_at,
                reverse=True,
            )
        ]

    return schemas.UserRead(
        id=user.id,
        name=user.name,
        avatar_url=user.avatar_url,
        battle_tag=battle_tags,
        twitch=twitch,
        discord=discord,
    )


async def get(session: AsyncSession, user_id: int, entities: list[str]) -> models.User:
    user = await service.get(session, user_id, entities)
    if not user:
        raise errors.ApiHTTPException(
            status_code=400,
            detail=[errors.ApiExc(code="not_found", msg=f"User with id {user_id} not found.")],
        )
    return user


async def get_by_battle_tag(session: AsyncSession, battle_tag: str, entities: list[str]) -> models.User:
    user = await service.find_by_battle_tag(session, battle_tag, entities)
    if not user:
        raise errors.ApiHTTPException(
            status_code=400,
            detail=[
                errors.ApiExc(
                    code="not_found",
                    msg=f"User with battle tag {battle_tag} not found.",
                )
            ],
        )
    return user


async def find_by_battle_tag(session: AsyncSession, battle_tag: str) -> models.User:
    user = await service.find_by_battle_tag(session, battle_tag, [])
    if not user:
        raise errors.ApiHTTPException(
            status_code=400,
            detail=[
                errors.ApiExc(
                    code="not_found",
                    msg=f"User with battle tag {battle_tag} not found.",
                )
            ],
        )
    return user


async def create_or_ignore_battle_tags(session: AsyncSession, player: models.User, in_battle_tags: list[str]) -> None:
    battle_tags = [tag.battle_tag for tag in player.battle_tag]

    maybe_need_add_battle_tags = list(in_battle_tags)
    for battle_tag in set(maybe_need_add_battle_tags):
        if battle_tag and battle_tag not in battle_tags and not await service.get_battle_tag(session, battle_tag):
            try:
                name, tag = battle_tag.split("#")
                await service.create_battle_tag(session, player, battle_tag=battle_tag, name=name, tag=tag)
            except ValueError:
                pass


async def create_or_ignore_discords(session: AsyncSession, player: models.User, in_discords: list[str]) -> None:
    discords = [discord.name for discord in player.discord]

    maybe_need_add_discords = list(in_discords)
    for discord in set(maybe_need_add_discords):
        if discord and discord not in discords and not await service.get_discord(session, discord):
            await service.create_discord(session, player, discord=discord)


async def create_or_ignore_twitches(session: AsyncSession, player: models.User, in_twitches: list[str]) -> None:
    twitches = [twitch.name for twitch in player.twitch]

    maybe_need_add_twitches = list(in_twitches)
    for twitch in set(maybe_need_add_twitches):
        if twitch and twitch not in twitches and not await service.get_twitch(session, twitch):
            await service.create_twitch(session, player, twitch=twitch)


async def create(session: AsyncSession, data_in: schemas.UserCSV) -> models.User:
    player_data = await service.find_by_csv(session, data_in)
    if not player_data:
        user = await service.create(
            session,
            battle_tag=data_in.battle_tag,
            discord=data_in.discord,
            twitch=data_in.twitch,
        )
        await create_or_ignore_battle_tags(session, user, [*data_in.smurfs, data_in.battle_tag])
    else:
        user = await get(session, player_data.id, ["battle_tag", "twitch", "discord"])
        await create_or_ignore_battle_tags(session, user, [*data_in.smurfs, data_in.battle_tag])
        await service.update(session, user, name=data_in.battle_tag)

        twitch_names: dict[str, models.UserTwitch] = {twitch.name: twitch for twitch in user.twitch}
        discord_names: dict[str, models.UserDiscord] = {discord.name: discord for discord in user.discord}

        if data_in.twitch:
            if data_in.twitch not in twitch_names.keys():
                if not await service.get_twitch(session, data_in.twitch):
                    await service.create_twitch(session, user, twitch=data_in.twitch)
            else:
                await service.update_twitch(session, twitch_names[data_in.twitch], name=data_in.twitch)
        if data_in.discord:
            if data_in.discord not in discord_names.keys():
                if not await service.get_discord(session, data_in.discord):
                    await service.create_discord(session, user, discord=data_in.discord)
            else:
                await service.update_discord(session, discord_names[data_in.discord], name=data_in.discord)

    return await service.get(session, user.id, ["battle_tag", "twitch", "discord"])  # type: ignore


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
                f"Battle Tag: {battle_tag}, Discord: {discord}, "
                f"Twitch: {twitch}, Smurfs: {smurfs}"
            )
            continue

        await create(session, payload)
