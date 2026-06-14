import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src import models
from src.core import auth, db, enums
from src.core.workspace import WorkspaceQuery
from src.services.analytics import flows as analytics_flows

router = APIRouter(
    prefix="/analytics",
    tags=[enums.RouteTag.ANALYTICS],
)


class AnalyticsRecalculateRequest(BaseModel):
    tournament_id: int
    algorithm_ids: list[int] = Field(default_factory=list)


async def _validate_tournament_workspace(
    session,
    tournament_id: int,
    workspace_id: int | None,
) -> None:
    if workspace_id is None:
        return

    tournament_workspace_id = await session.scalar(
        sa.select(models.Tournament.workspace_id).where(
            models.Tournament.id == tournament_id
        )
    )
    if tournament_workspace_id is None:
        raise HTTPException(status_code=404, detail="Tournament not found")
    if tournament_workspace_id != workspace_id:
        raise HTTPException(
            status_code=400,
            detail="workspace_id does not match tournament workspace",
        )


@router.post(path="/recalculate")
async def recalculate_analytics(
    data: AnalyticsRecalculateRequest,
    workspace_id: WorkspaceQuery = None,
    _user=Depends(auth.require_permission("analytics", "update")),
    session=Depends(db.get_async_session),
):
    await _validate_tournament_workspace(session, data.tournament_id, workspace_id)

    algorithm_names = None
    if data.algorithm_ids:
        algorithms = await analytics_flows.service.get_algorithms(session, data.algorithm_ids)
        algorithm_names = [algorithm.name for algorithm in algorithms]

    recalculated = await analytics_flows.recalculate_analytics(
        session,
        data.tournament_id,
        algorithm_names,
        workspace_id=workspace_id,
    )
    return {"message": "Analytics recalculated successfully", "algorithms": recalculated}


@router.post(path="/points")
async def create_analytics_tournament_points(
    tournament_id: int,
    workspace_id: WorkspaceQuery = None,
    _user=Depends(auth.require_permission("analytics", "update")),
    session=Depends(db.get_async_session),
):
    await _validate_tournament_workspace(session, tournament_id, workspace_id)
    await analytics_flows.recalculate_analytics(
        session,
        tournament_id,
        [analytics_flows.POINTS],
        workspace_id=workspace_id,
    )
    return {"message": "Points calculated successfully"}


@router.post(path="/openskill")
async def create_analytics_tournament_analytics(
    tournament_id: int,
    workspace_id: WorkspaceQuery = None,
    _user=Depends(auth.require_permission("analytics", "update")),
    session=Depends(db.get_async_session),
):
    await _validate_tournament_workspace(session, tournament_id, workspace_id)
    raise HTTPException(
        status_code=410,
        detail=(
            "Open Skill v1 is no longer available. "
            "Run the unified analytics job to compute OpenSkill + ML."
        ),
    )
