import json
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from src import schemas
from src.services.team import flows


async def create_from_folder(session: AsyncSession) -> None:
    paths: list[tuple[int, str]] = []

    for path in Path("teams").glob("*.json"):
        number = str(path).split("_")[-1].replace(".json", "")
        tournament_id = int(number)
        paths.append((tournament_id, str(path)))

    paths = sorted(paths, key=lambda item: item[0])

    for tournament_id, path in paths:
        with open(path, encoding="utf-8") as file:
            payload = json.loads(file.read())

        if "data" in payload and isinstance(payload["data"], dict) and "teams" in payload["data"]:
            teams = [schemas.BalancerTeam.model_validate(team) for team in payload["data"]["teams"]]
        else:
            internal_payload = schemas.InternalBalancerTeamsPayload.model_validate(payload)
            teams = [team.to_balancer_team() for team in internal_payload.teams]

        await flows.bulk_create_from_balancer(session, tournament_id, teams)


async def bulk_create_from_challonge(session: AsyncSession) -> None:
    raise RuntimeError("Challonge team sync requires explicit participant-to-team mappings.")
