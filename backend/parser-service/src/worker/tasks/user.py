import csv
import re

from loguru import logger
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from src import schemas
from src.core import config
from src.services.user import flows

battle_tag_validator = re.compile(config.settings.battle_tag_regex, re.UNICODE)


async def create_or_update_player_from_csv(
    session: AsyncSession,
    file_path: str,
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
    with open(file_path, encoding="utf-8") as r_file:
        file_reader = csv.reader(r_file, delimiter=delimiter)
        for index, row in enumerate(file_reader, 0):
            if index < start_row:
                continue
            battle_tag = row[battle_tag_row].strip().replace(" #", "#").replace("# ", "#")
            twitch = row[twitch_row].strip() if has_twitch else None
            discord = row[discord_row].strip() if has_discord else None
            smurfs = row[smurf_row] if has_smurf else ""

            try:
                payload = schemas.UserCSV(
                    battle_tag=battle_tag_validator.findall(battle_tag)[0],
                    discord=discord,
                    twitch=twitch,
                    smurfs=battle_tag_validator.findall(smurfs),
                )
            except (IndexError, ValidationError):
                logger.error(
                    f"Invalid data in row {index + 1} of {file_path}: "
                    f"Battle Tag: {battle_tag}, Discord: {discord}, "
                    f"Twitch: {twitch}, Smurfs: {smurfs}"
                )
                continue

            await flows.create(session, payload)


async def initial_parse(session: AsyncSession) -> None:
    for index in range(3, 4 + 1):
        await create_or_update_player_from_csv(
            session,
            f"answers/{index}.csv",
            battle_tag_row=1,
            discord_row=3,
            twitch_row=2,
            smurf_row=4,
            has_discord=False,
            has_smurf=False,
        )
    for index in range(5, 23 + 1):
        logger.warning(f"Processing {index}")
        await create_or_update_player_from_csv(
            session,
            f"answers/{index}.csv",
            battle_tag_row=1,
            discord_row=4,
            twitch_row=3,
            smurf_row=2,
            has_discord=False,
            has_smurf=True,
        )
    for index in range(24, 32 + 1):
        await create_or_update_player_from_csv(
            session,
            f"answers/{index}.csv",
            battle_tag_row=1,
            discord_row=4,
            twitch_row=3,
            smurf_row=2,
            has_discord=True,
            has_smurf=True,
        )
    await create_or_update_player_from_csv(
        session,
        "answers/33.csv",
        battle_tag_row=1,
        discord_row=4,
        twitch_row=3,
        smurf_row=2,
        has_discord=False,
        has_smurf=True,
    )
    for index in range(34, 37 + 1):
        await create_or_update_player_from_csv(
            session,
            f"answers/{index}.csv",
            battle_tag_row=1,
            discord_row=4,
            twitch_row=3,
            smurf_row=2,
            has_discord=True,
            has_smurf=True,
        )
