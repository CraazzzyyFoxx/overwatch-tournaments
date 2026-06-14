import asyncio
import json
import pandas as pd

from loguru import logger
from shared.clients.s3 import S3Client

from src.core import config, db
from src.services.s3 import service as s3_service
from src.services.user.service import get_by_battle_tag


def update_player_data(player_data: dict, player_formated_data: dict) -> dict:
    is_flex = player_data.get("isFullFlex", False)
    if not player_formated_data.get("isFullFlex", None):
        player_formated_data["isFullFlex"] = "Flex" if is_flex else ""
        logger.info(f"Updated player {player_formated_data["name"]} with isFullFlex: {is_flex}")

    return player_formated_data


async def filter_owal_players() -> None:
    s3 = S3Client(
        access_key=config.settings.s3_access_key,
        secret_key=config.settings.s3_secret_key,
        endpoint_url=config.settings.s3_endpoint_url,
        bucket_name=config.settings.s3_bucket_name,
    )
    await s3.start()
    tournaments = await s3_service.get_tournaments_teams(s3)

    with open("players.json", "r", encoding="utf-8") as file:
        result_data = json.load(file)
        formated_data = {player["name"]: player for player in result_data}

    for tournament_name, data_raw in tournaments.items():
        data = json.loads(data_raw)
        players = data["data"].get("players", {})
        for player_uuid in players:
            player_data = players[player_uuid]["identity"]
            battle_tag = player_data["name"]
            if battle_tag in formated_data:
                formated_data[battle_tag] = update_player_data(player_data, formated_data[battle_tag])
            else:
                async with db.async_session_maker() as session:
                    player = await get_by_battle_tag(session, player_uuid, [])
                    if player and player.battle_tag in formated_data:
                        player_data = update_player_data(formated_data, player.to_dict())
                        formated_data[player_uuid] = player_data
                    else:
                        logger.warning(f"Player {battle_tag} not found in database or players.json")

    players_out = {}

    def check_player(player_info: dict, role: str, two_role: str, three_role: str) -> bool:
        return (
            player_info[role] >= 3 or
            (player_info[role] == 2 and (player_info[two_role] >= 1 or player_info[three_role] >= 1) and player_info.get("isFullFlex", "") == "Flex")
        )

    for player_uuid in formated_data:
        player_info = formated_data[player_uuid]
        if check_player(player_info, "tank", "damage", "support"):
            players_out[player_uuid] = player_info
        if check_player(player_info, "damage", "tank", "support"):
            players_out[player_uuid] = player_info
        if check_player(player_info, "support", "damage", "tank"):
            players_out[player_uuid] = player_info

    df = pd.DataFrame.from_dict(formated_data, orient="index")
    df.to_excel("players_owal.xlsx", index=False)
    logger.info("Filtered OWAL players and saved to players_owal.xlsx")



if __name__ == "__main__":
    # loop = asyncio.get_event_loop()
    # loop.run_until_complete(filter_owal_players())
    # loop.close()

    with open("players.json", "r", encoding="utf-8") as file:
        result_data = json.load(file)
        formated_data = {player["name"]: player for player in result_data}

    with open("players-25.07.2025, 00_45_37.json", "r", encoding="utf-8") as file:
        players = json.load(file)
        for player_uuid in players["players"]:
            player_data = players["players"][player_uuid]["identity"]
            battle_tag = player_data["name"]

            if battle_tag not in formated_data:
                logger.warning(f"Player {battle_tag} not found in players.json")