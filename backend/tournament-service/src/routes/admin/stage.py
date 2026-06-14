"""Admin routes for stage CRUD, bracket generation, and stage activation."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src import models, schemas
from src.core import auth, db
from src.schemas.admin import stage as admin_schemas
from src.services.admin import stage as stage_service
from src.services.computation import jobs as computation_jobs

router = APIRouter(
    prefix="/stages",
    tags=["admin", "stages"],
)


@router.get(
    "/tournament/{tournament_id}",
    response_model=list[schemas.StageRead],
)
async def get_stages(
    tournament_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("stage", "read")),
):
    """Get all stages for a tournament."""
    stages = await stage_service.get_stages_by_tournament(session, tournament_id)
    return [schemas.StageRead.model_validate(s, from_attributes=True) for s in stages]


@router.get("/tournament/{tournament_id}/progress")
async def get_stages_progress(
    tournament_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("stage", "read")),
):
    """Return completion progress per stage and per stage_item.

    Response shape:
    ```
    [
      {
        "stage_id": 1,
        "name": "Groups",
        "stage_type": "round_robin",
        "is_active": true,
        "is_completed": false,
        "total": 20,
        "completed": 18,
        "items": [
          {"stage_item_id": 10, "name": "A", "total": 10, "completed": 10,
           "is_completed": true},
          {"stage_item_id": 11, "name": "B", "total": 10, "completed": 8,
           "is_completed": false}
        ]
      }
    ]
    ```
    """
    return await stage_service.get_stage_progress(session, tournament_id)


@router.get("/{stage_id}", response_model=schemas.StageRead)
async def get_stage(
    stage_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_stage_permission("stage", "read")),
):
    """Get a single stage with items and inputs."""
    stage = await stage_service.get_stage(session, stage_id)
    return schemas.StageRead.model_validate(stage, from_attributes=True)


@router.post(
    "/tournament/{tournament_id}",
    response_model=schemas.StageRead,
)
async def create_stage(
    tournament_id: int,
    data: admin_schemas.StageCreate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_tournament_permission("stage", "create")),
):
    """Create a new stage for a tournament."""
    stage = await stage_service.create_stage(session, tournament_id, data)
    return schemas.StageRead.model_validate(stage, from_attributes=True)


@router.patch("/{stage_id}", response_model=schemas.StageRead)
async def update_stage(
    stage_id: int,
    data: admin_schemas.StageUpdate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_stage_permission("stage", "update")),
):
    """Update stage metadata."""
    if data.stage_type is not None and not user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only superusers can change stage type after creation",
        )

    stage = await stage_service.update_stage(session, stage_id, data)
    return schemas.StageRead.model_validate(stage, from_attributes=True)


@router.delete("/{stage_id}", status_code=204)
async def delete_stage(
    stage_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_stage_permission("stage", "delete")),
):
    """Delete a stage and all its items/inputs."""
    await stage_service.delete_stage(session, stage_id)


@router.post("/{stage_id}/merge-group-stages", response_model=schemas.StageRead)
async def merge_group_stages(
    stage_id: int,
    data: admin_schemas.MergeGroupStagesRequest,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_stage_permission("stage", "update")),
):
    """Merge legacy one-group stages into the selected grouped stage."""
    stage = await stage_service.merge_group_stages(
        session,
        target_stage_id=stage_id,
        source_stage_ids=data.source_stage_ids,
        target_name=data.target_name,
    )
    return schemas.StageRead.model_validate(stage, from_attributes=True)


@router.post(
    "/{stage_id}/items",
    response_model=schemas.StageItemRead,
)
async def create_stage_item(
    stage_id: int,
    data: admin_schemas.StageItemCreate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_stage_permission("stage", "update")),
):
    """Create a stage item (group, bracket) within a stage."""
    item = await stage_service.create_stage_item(session, stage_id, data)
    return schemas.StageItemRead.model_validate(item, from_attributes=True)


@router.patch(
    "/items/{stage_item_id}",
    response_model=schemas.StageItemRead,
)
async def update_stage_item(
    stage_item_id: int,
    data: admin_schemas.StageItemUpdate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_stage_item_permission("stage", "update")),
):
    """Update a stage item's name, type, or order."""
    item = await stage_service.update_stage_item(session, stage_item_id, data)
    return schemas.StageItemRead.model_validate(item, from_attributes=True)


@router.post(
    "/items/{stage_item_id}/inputs",
    response_model=schemas.StageItemInputRead,
)
async def create_stage_item_input(
    stage_item_id: int,
    data: admin_schemas.StageItemInputCreate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_stage_item_permission("stage", "update")),
):
    """Create a stage item input (team slot)."""
    inp = await stage_service.create_stage_item_input(session, stage_item_id, data)
    return schemas.StageItemInputRead.model_validate(inp, from_attributes=True)


@router.patch(
    "/items/inputs/{input_id}",
    response_model=schemas.StageItemInputRead,
)
async def update_stage_item_input(
    input_id: int,
    data: admin_schemas.StageItemInputUpdate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_stage_item_input_permission("stage", "update")),
):
    """Update a stage item input (e.g. swap the assigned team)."""
    inp = await stage_service.update_stage_item_input(session, input_id, data)
    return schemas.StageItemInputRead.model_validate(inp, from_attributes=True)


@router.post("/{stage_id}/activate", response_model=schemas.StageRead)
async def activate_stage(
    stage_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_stage_permission("stage", "update")),
):
    """Activate a stage, resolving tentative inputs from previous stage standings."""
    stage = await stage_service.activate_stage(session, stage_id)
    return schemas.StageRead.model_validate(stage, from_attributes=True)


@router.post(
    "/{stage_id}/generate",
    response_model=schemas.admin.computation.TournamentComputationJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_encounters(
    stage_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_stage_permission("stage", "update")),
):
    """Generate bracket encounters for a stage based on its type and assigned teams."""
    stage = await stage_service.get_stage(session, stage_id)
    job = await computation_jobs.request_bracket_job(
        session,
        tournament_id=stage.tournament_id,
        stage_id=stage.id,
        operation="generate_stage",
        requested_by_user_id=int(user.id),
    )
    await session.commit()
    return job


@router.post("/{stage_id}/wire-from-groups", response_model=schemas.StageRead)
async def wire_from_groups(
    stage_id: int,
    data: admin_schemas.WireFromGroupsRequest,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_stage_permission("stage", "update")),
):
    """Auto-wire TENTATIVE inputs in a playoff stage from a preceding group
    stage. Creates (num_groups × top) inputs with cross-group seeding so that
    group rematches are avoided in the first playoff round.

    Safe to call repeatedly: manually-assigned FINAL inputs are preserved,
    only TENTATIVE inputs are (re-)written.
    """
    stage = await stage_service.wire_from_groups(
        session,
        target_stage_id=stage_id,
        source_stage_id=data.source_stage_id,
        top=data.top,
        top_lb=data.top_lb,
        mode=data.mode,
    )
    return schemas.StageRead.model_validate(stage, from_attributes=True)


@router.post(
    "/{stage_id}/activate-and-generate",
    response_model=schemas.admin.computation.TournamentComputationJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def activate_and_generate(
    stage_id: int,
    force: bool = False,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_stage_permission("stage", "update")),
):
    """One-click: resolve TENTATIVE inputs from prior-stage standings, then
    generate the bracket. Equivalent to calling /activate then /generate.

    Refuses to run if upstream stages still have pending encounters (to
    prevent locking in playoff seeds prematurely). Pass ``force=true`` to
    override this safety check.
    """
    stage = await stage_service.get_stage(session, stage_id)
    job = await computation_jobs.request_bracket_job(
        session,
        tournament_id=stage.tournament_id,
        stage_id=stage.id,
        operation="activate_and_generate",
        payload={"force": force},
        requested_by_user_id=int(user.id),
    )
    await session.commit()
    return job


@router.post("/{stage_id}/seed-teams", response_model=schemas.StageRead)
async def seed_teams(
    stage_id: int,
    data: admin_schemas.SeedTeamsRequest,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_stage_permission("stage", "update")),
):
    """Auto-distribute teams into the stage's stage_items using snake-SR
    (default) or another seeding mode. Replaces all existing FINAL inputs;
    TENTATIVE/EMPTY inputs are preserved.
    """
    stage = await stage_service.seed_teams(
        session,
        stage_id=stage_id,
        team_ids=data.team_ids,
        mode=data.mode,
    )
    return schemas.StageRead.model_validate(stage, from_attributes=True)
