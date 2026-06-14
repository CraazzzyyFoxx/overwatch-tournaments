from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src import models, schemas
from src.core import auth, db, enums
from src.services.tournament import flows as tournament_flows

router = APIRouter(
    prefix="/tournament",
    tags=[enums.RouteTag.TOURNAMENT],
)


@router.post(path="/create", response_model=schemas.TournamentRead)
async def create(
    number: int,
    is_league: bool,
    start_date: date,
    end_date: date,
    playoffs_challonge_slug: str,
    groups_challonge_slugs: list[str] = Query([]),
    session=Depends(db.get_async_session),
    _user: models.AuthUser = Depends(auth.require_permission("tournament", "create")),
):
    tournament = await tournament_flows.create(
        session, number, is_league, start_date, end_date, groups_challonge_slugs, playoffs_challonge_slug
    )
    return await tournament_flows.to_pydantic(session, tournament, [])


@router.post(path="/create/with_groups", response_model=schemas.TournamentRead)
async def create_with_groups(
    workspace_id: int,
    number: int,
    challonge_slug: str,
    is_league: bool,
    start_date: date,
    end_date: date,
    division_grid_version_id: int | None = None,
    session=Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.get_current_active_user),
):
    if not user.has_workspace_permission(workspace_id, "tournament", "create"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: tournament.create required",
        )
    tournament = await tournament_flows.create_with_groups(
        session,
        workspace_id,
        number,
        is_league,
        start_date,
        end_date,
        challonge_slug,
        division_grid_version_id=division_grid_version_id,
    )
    return await tournament_flows.to_pydantic(session, tournament, [])
