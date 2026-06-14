import json
import typing

from fastapi import APIRouter, Depends, UploadFile

from src import schemas
from src.core import auth, db, enums
from src.services.team import flows as team_flows

router = APIRouter(
    prefix="/teams",
    tags=[enums.RouteTag.TEAMS],
    dependencies=[Depends(auth.require_role("admin"))],
)


@router.post(path="/create/balancer")
async def bulk_create_from_balancer(
    tournament_id: int,
    data: UploadFile,
    payload_format: typing.Literal["auto", "atravkovs", "internal"] = "auto",
    session=Depends(db.get_async_session),
):
    text = await data.read()
    payload = json.loads(text)

    use_atravkovs = payload_format == "atravkovs" or (
        payload_format == "auto"
        and isinstance(payload, dict)
        and isinstance(payload.get("data"), dict)
        and "teams" in payload["data"]
    )

    if use_atravkovs:
        teams = [schemas.BalancerTeam.model_validate(team) for team in payload["data"]["teams"]]
    else:
        internal_payload = schemas.InternalBalancerTeamsPayload.model_validate(payload)
        teams = [team.to_balancer_team() for team in internal_payload.teams]

    return await team_flows.bulk_create_from_balancer(session, tournament_id, teams)


@router.get(path="/challonge/preview")
async def preview_challonge_sync(
    tournament_id: int,
    session=Depends(db.get_async_session),
):
    return await team_flows.preview_challonge_team_sync(session, tournament_id)


@router.post(path="/create/challonge")
async def create_from_challonge(
    tournament_id: int,
    payload: schemas.ChallongeTeamSyncRequest,
    session=Depends(db.get_async_session),
):
    return await team_flows.sync_challonge_team_mappings(
        session,
        tournament_id,
        payload,
    )
