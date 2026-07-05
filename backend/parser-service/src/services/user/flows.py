import csv
import re

from loguru import logger
from pydantic import ValidationError
from shared.core.social import SocialProvider, normalize_social_handle
from sqlalchemy.ext.asyncio import AsyncSession

from src import models, schemas
from src.core import config, errors

from . import service


def _usernames(player: models.User, provider: str) -> list[str]:
    """Usernames the player already has for a provider (from the unified table)."""
    return [a.username for a in player.social_accounts if a.provider == provider]

battle_tag_validator = re.compile(config.settings.battle_tag_regex, re.UNICODE)


_IDENTITY_ENTITIES = ("social_accounts", "battle_tag", "discord", "twitch")


async def to_pydantic(session: AsyncSession, user: models.User, entities: list[str]) -> schemas.UserRead:
    """Convert a ``User`` to ``UserRead``. Identities come from the unified
    ``user.social_accounts`` relationship and are only accessed when an identity
    entity was requested (and therefore eager-loaded), so this never triggers a
    lazy load outside the async greenlet. Legacy entity tokens are still honored.
    """
    social_accounts: list[schemas.SocialAccountRead] = []
    if any(name in entities for name in _IDENTITY_ENTITIES):
        social_accounts = [
            schemas.SocialAccountRead.model_validate(account, from_attributes=True)
            for account in sorted(
                user.social_accounts, key=lambda a: (a.provider, not a.is_primary, a.id)
            )
        ]
    return schemas.UserRead(
        id=user.id,
        name=user.name,
        avatar_url=user.avatar_url,
        social_accounts=social_accounts,
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
    battle_tags = _usernames(player, SocialProvider.BATTLENET)

    candidates = [
        battle_tag
        for battle_tag in set(in_battle_tags)
        if battle_tag and "#" in battle_tag and battle_tag not in battle_tags
    ]
    if not candidates:
        return

    # One existence query for the whole batch instead of a find_by_handle
    # round-trip per tag; matching stays on the normalized handle, exactly like
    # the old per-item ``service.get_battle_tag`` probe.
    taken = await service.get_taken_handles(session, SocialProvider.BATTLENET, candidates)
    for battle_tag in candidates:
        normalized = normalize_social_handle(SocialProvider.BATTLENET, battle_tag)
        if normalized in taken:
            continue
        taken.add(normalized)
        await service.create_battle_tag(session, player, battle_tag=battle_tag)


async def create_or_ignore_discords(session: AsyncSession, player: models.User, in_discords: list[str]) -> None:
    discords = _usernames(player, SocialProvider.DISCORD)

    candidates = [discord for discord in set(in_discords) if discord and discord not in discords]
    if not candidates:
        return

    taken = await service.get_taken_handles(session, SocialProvider.DISCORD, candidates)
    for discord in candidates:
        normalized = normalize_social_handle(SocialProvider.DISCORD, discord)
        if normalized in taken:
            continue
        taken.add(normalized)
        await service.create_discord(session, player, discord=discord)


async def create_or_ignore_twitches(session: AsyncSession, player: models.User, in_twitches: list[str]) -> None:
    twitches = _usernames(player, SocialProvider.TWITCH)

    candidates = [twitch for twitch in set(in_twitches) if twitch and twitch not in twitches]
    if not candidates:
        return

    taken = await service.get_taken_handles(session, SocialProvider.TWITCH, candidates)
    for twitch in candidates:
        normalized = normalize_social_handle(SocialProvider.TWITCH, twitch)
        if normalized in taken:
            continue
        taken.add(normalized)
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

        twitch_names: dict[str, models.SocialAccount] = {
            a.username: a for a in user.social_accounts if a.provider == SocialProvider.TWITCH
        }
        discord_names: dict[str, models.SocialAccount] = {
            a.username: a for a in user.social_accounts if a.provider == SocialProvider.DISCORD
        }

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
