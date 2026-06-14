import csv
from uuid import uuid4

from src import schemas

users_path_const = r"C:\Users\andre\PycharmProjects\anak-tournament-backend\parser\_Players__202412302224.csv"
teams_path_const = r"C:\Users\andre\PycharmProjects\anak-tournament-backend\parser\_Team__202412302225.csv"
matches_path_const = r"C:\Users\andre\PycharmProjects\anak-tournament-backend\parser\_Match__202412302226.csv"


async def get_users_from_dasha(payload: list) -> dict[int, schemas.UserDasha]:
    data: dict[int, schemas.UserDasha] = {}

    with open(users_path_const, encoding="utf-8") as r_file:
        file_reader = csv.reader(r_file)

        for index, row in enumerate(file_reader, 0):
            if index == 0:
                continue

            user_id = int(row[2])
            battle_tag = row[1].strip()
            nickname = row[3].strip()
            twitch = row[4].strip()
            discord = row[5].strip() if row[5] else None

            if not battle_tag:
                continue

            if user_id not in data:
                data[user_id] = schemas.UserDasha(
                    id=user_id,
                    battle_tag=battle_tag,
                    nickname=nickname,
                    twitch=twitch,
                    discord=discord,
                    twitches=[twitch],
                    discords=[discord] if discord else [],
                    battle_tags=[battle_tag],
                )
            else:
                data[user_id].twitch = twitch
                data[user_id].discord = discord

                data[user_id].twitches.append(twitch)
                data[user_id].twitches = list(set(data[user_id].twitches))
                data[user_id].battle_tags.append(battle_tag)
                data[user_id].battle_tags = list(set(data[user_id].battle_tags))
                if discord:
                    data[user_id].discords.append(discord)
                    data[user_id].discords = list(set(data[user_id].discords))

    return data


async def get_teams_from_dasha(payload: list) -> dict[int, schemas.DashaTeam]:
    data: dict[int, schemas.DashaTeam] = {}
    data_costs: dict[int, list[int]] = {}

    with open(teams_path_const, encoding="utf-8") as r_file:
        file_reader = csv.reader(r_file)

        for index, row in enumerate(file_reader, 0):
            if index == 0:
                continue

            player_id: int = int(row[0])
            tournament_id: int = int(row[1])
            team_id: int = int(row[2])
            user_id: int = int(row[3])
            team_name = row[4].strip()
            player_name = row[5].strip()
            role = row[6].strip()
            price: int = int(row[7])
            division: int = int(row[8].strip())

            if team_id in data_costs:
                data_costs[team_id].append(price)
            else:
                data_costs[team_id] = [price]

            if team_id not in data:
                data[team_id] = schemas.DashaTeam(
                    id=team_id,
                    tournament_id=tournament_id,
                    name=team_name,
                    avg_sr=0,
                    total_sr=0,
                    players=[
                        schemas.DashaTeamMember(
                            id=player_id,
                            tournament_id=tournament_id,
                            team_id=team_id,
                            user_id=user_id,
                            name=player_name,
                            role=role if role != "Flex" else None,  # type: ignore
                            price=price,
                            division=division,
                        )
                    ],
                )
            else:
                data[team_id].players.append(
                    schemas.DashaTeamMember(
                        id=player_id,
                        tournament_id=tournament_id,
                        team_id=team_id,
                        user_id=user_id,
                        name=player_name,
                        role=role if role != "Flex" else None,  # type: ignore
                        price=price,
                        division=division,
                    )
                )

    for team_id, costs in data_costs.items():
        data[team_id].total_sr = sum(costs)
        data[team_id].avg_sr = data[team_id].total_sr / len(costs)

    return data


async def transform_dasha_teams_to_normal(
    teams: dict[int, schemas.DashaTeam],
) -> dict[int, list[schemas.BalancerTeam]]:
    data: dict[int, list[schemas.BalancerTeam]] = {}

    for team in teams.values():
        if team.tournament_id not in data:
            data[team.tournament_id] = []

        data[team.tournament_id].append(
            schemas.BalancerTeam(
                uuid=uuid4(),
                avgSr=team.avg_sr,
                name=team.name,
                totalSr=team.total_sr,
                members=[
                    schemas.BalancerTeamMember(
                        uuid=uuid4(),
                        name=player.name,
                        sub_role=None,
                        role=player.role,
                        rank=player.price,
                    )
                    for player in team.players
                ],
            )
        )

    return data
