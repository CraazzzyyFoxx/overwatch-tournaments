import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from shared.models.achievement import AchievementRule, EvaluationRunTrigger

from src import models, schemas
from src.core import auth, db, enums
from src.services.achievement.engine.runner import run_evaluation
from src.services.achievement.engine.seeder import seed_workspace

router = APIRouter(
    prefix="/achievement",
    tags=[enums.RouteTag.ACHIEVEMENT],
    dependencies=[Depends(auth.require_role("admin"))],
)


@router.post(path="/calculate", response_model=schemas.AchievementCalculateResponse)
async def calculate_achievements(
    payload: schemas.AchievementCalculateRequest | None = None,
    session=Depends(db.get_async_session),
):
    payload = payload or schemas.AchievementCalculateRequest()
    if payload.workspace_id is None:
        raise HTTPException(status_code=400, detail="workspace_id is required for global achievement calculation")

    workspace_id = payload.workspace_id
    if payload.ensure_created:
        await seed_workspace(session, workspace_id)

    query = sa.select(AchievementRule).where(AchievementRule.workspace_id == workspace_id)
    if payload.slugs:
        query = query.where(AchievementRule.slug.in_(payload.slugs))
    else:
        query = query.where(AchievementRule.enabled.is_(True))
    rules = list((await session.execute(query)).scalars())
    found_slugs = {rule.slug for rule in rules}

    if payload.slugs:
        missing_slugs = sorted(set(payload.slugs) - found_slugs)
        if missing_slugs:
            raise HTTPException(status_code=400, detail=f"Unknown achievement slugs: {', '.join(missing_slugs)}")

    await run_evaluation(
        session=session,
        workspace_id=workspace_id,
        trigger=EvaluationRunTrigger.manual,
        rule_ids=[rule.id for rule in rules] if payload.slugs else None,
    )

    executed = sorted(found_slugs) if payload.slugs else sorted(rule.slug for rule in rules)
    return schemas.AchievementCalculateResponse(
        tournament_id=None,
        executed=executed,
        message="Achievement calculation finished",
    )


@router.post(path="/calculate/{tournament_id}", response_model=schemas.AchievementCalculateResponse)
async def calculate_achievements_for_tournament(
    tournament_id: int,
    payload: schemas.AchievementCalculateRequest | None = None,
    session=Depends(db.get_async_session),
):
    payload = payload or schemas.AchievementCalculateRequest()
    tournament = await session.get(models.Tournament, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Tournament not found")

    workspace_id = payload.workspace_id or tournament.workspace_id
    if payload.workspace_id is not None and payload.workspace_id != tournament.workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id does not match tournament workspace")

    if payload.ensure_created:
        await seed_workspace(session, workspace_id)

    query = sa.select(AchievementRule).where(AchievementRule.workspace_id == workspace_id)
    if payload.slugs:
        query = query.where(AchievementRule.slug.in_(payload.slugs))
    else:
        query = query.where(AchievementRule.enabled.is_(True))
    rules = list((await session.execute(query)).scalars())
    found_slugs = {rule.slug for rule in rules}

    if payload.slugs:
        missing_slugs = sorted(set(payload.slugs) - found_slugs)
        if missing_slugs:
            raise HTTPException(status_code=400, detail=f"Unknown achievement slugs: {', '.join(missing_slugs)}")

    await run_evaluation(
        session=session,
        workspace_id=workspace_id,
        trigger=EvaluationRunTrigger.manual,
        tournament_id=tournament_id,
        rule_ids=[rule.id for rule in rules] if payload.slugs else None,
    )

    executed = sorted(found_slugs) if payload.slugs else sorted(rule.slug for rule in rules)
    return schemas.AchievementCalculateResponse(
        tournament_id=tournament_id,
        executed=executed,
        message="Achievement calculation finished",
    )
