"""Admin routes for achievement rule engine: CRUD, evaluate, overrides."""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from shared.clients import S3Client
from shared.models.achievement import (
    AchievementEvaluationResult,
    AchievementOverride,
    AchievementOverrideAction,
    AchievementRule,
    EvaluationRun,
    EvaluationRunTrigger,
)
from shared.services.achievement_effective import build_effective_achievement_rows_subquery
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.core import auth, db
from src.schemas.admin.achievement_rule import (
    AchievementLibraryImportRequest,
    AchievementLibraryRuleRead,
    AchievementLibraryWorkspaceRead,
    AchievementRuleCreate,
    AchievementRuleExportEnvelope,
    AchievementRuleImportResult,
    AchievementRulePortable,
    AchievementRuleRead,
    AchievementRuleUpdate,
    ConditionTreeValidateRequest,
    ConditionTreeValidateResponse,
    ConditionTypeInfo,
    EvaluateRequest,
    EvaluationRunRead,
    HardResetResultRead,
    OverrideCreate,
    OverrideRead,
    SeedResultRead,
)
from src.services.achievement.engine.runner import run_evaluation
from src.services.achievement.engine.seeder import hard_reset_workspace, seed_workspace
from src.services.achievement.engine.validation import (
    LEAF_GRAINS,
    infer_grain,
    validate_condition_tree,
    validate_rule_definition,
)
from src.services.achievement.import_export import (
    build_export_payload,
    import_portable_rules,
    load_rules_for_workspace,
)

router = APIRouter(
    prefix="/ws/{workspace_id}/achievements/rules",
    tags=["admin", "achievement-rules"],
)


library_router = APIRouter(
    prefix="/ws/{workspace_id}/achievements/library",
    tags=["admin", "achievement-library"],
)


def get_s3(request: Request) -> S3Client:
    return request.app.state.s3


async def _get_workspace_or_404(session: AsyncSession, workspace_id: int) -> models.Workspace:
    workspace = await session.get(models.Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


def _get_visible_workspace_ids(user: models.AuthUser, target_workspace_id: int) -> list[int] | None:
    if user.is_superuser:
        return None
    return [workspace_id for workspace_id in user.get_workspace_ids() if workspace_id != target_workspace_id]


async def _get_source_workspace_or_404(
    session: AsyncSession,
    *,
    target_workspace_id: int,
    source_workspace_id: int,
    user: models.AuthUser,
) -> models.Workspace:
    if source_workspace_id == target_workspace_id:
        raise HTTPException(status_code=400, detail="Source and target workspace must be different")

    workspace = await session.get(models.Workspace, source_workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Source workspace not found")
    if not user.is_superuser and source_workspace_id not in user.get_workspace_ids():
        raise HTTPException(status_code=403, detail="Source workspace is not accessible")
    return workspace


# ─── Condition Types Reference ───────────────────────────────────────────────


@router.get("/condition-types", response_model=list[ConditionTypeInfo])
async def get_condition_types(
    _user: models.AuthUser = Depends(auth.require_workspace_permission("achievement", "read")),
):
    """List all available leaf condition types with param schemas."""

    type_info = []
    for name, grain in sorted(LEAF_GRAINS.items()):
        type_info.append(
            ConditionTypeInfo(
                name=name,
                grain=grain.value,
                description=f"Condition type: {name}",
                required_params=[],
                optional_params=[],
            )
        )
    return type_info


# ─── Validation ──────────────────────────────────────────────────────────────


@router.post("/validate", response_model=ConditionTreeValidateResponse)
async def validate_condition_tree_endpoint(
    body: ConditionTreeValidateRequest,
    _user: models.AuthUser = Depends(auth.require_workspace_permission("achievement", "read")),
):
    errors = validate_condition_tree(body.condition_tree)
    grain = infer_grain(body.condition_tree) if not errors else None
    return ConditionTreeValidateResponse(
        valid=len(errors) == 0,
        errors=errors,
        inferred_grain=grain.value if grain else None,
    )


# ─── Seeding ─────────────────────────────────────────────────────────────────


@router.post("/seed", response_model=SeedResultRead)
async def seed_default_rules(
    workspace_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    _user: models.AuthUser = Depends(auth.require_workspace_permission("achievement", "create")),
):
    """Seed the default achievement catalog for a workspace."""
    seeded, removed = await seed_workspace(session, workspace_id)
    await session.commit()
    return {"seeded": seeded, "removed": removed}


@router.post("/reset", response_model=HardResetResultRead)
async def hard_reset_rules(
    workspace_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    _user: models.AuthUser = Depends(auth.require_workspace_permission("achievement", "update")),
):
    """Replace the catalog, clear effective results, and re-run a full evaluation."""
    seeded, removed, cleared_results, run = await hard_reset_workspace(session, workspace_id)
    await session.commit()
    return {
        "seeded": seeded,
        "removed": removed,
        "cleared_results": cleared_results,
        "run": EvaluationRunRead.model_validate(run, from_attributes=True),
    }


# ─── Rule CRUD ───────────────────────────────────────────────────────────────


@router.get("", response_model=list[AchievementRuleRead])
async def list_rules(
    workspace_id: int,
    category: str | None = None,
    enabled: bool | None = None,
    session: AsyncSession = Depends(db.get_async_session),
    _user: models.AuthUser = Depends(auth.require_workspace_permission("achievement", "read")),
):
    query = sa.select(AchievementRule).where(
        AchievementRule.workspace_id == workspace_id
    )
    if category:
        query = query.where(AchievementRule.category == category)
    if enabled is not None:
        query = query.where(AchievementRule.enabled.is_(enabled))

    query = query.order_by(AchievementRule.category, AchievementRule.slug)
    result = await session.execute(query)
    return [AchievementRuleRead.model_validate(r, from_attributes=True) for r in result.scalars()]


@router.get("/export", response_model=AchievementRuleExportEnvelope)
async def export_rules(
    workspace_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    _user: models.AuthUser = Depends(auth.require_workspace_permission("achievement", "export")),
):
    workspace = await _get_workspace_or_404(session, workspace_id)
    rules = await load_rules_for_workspace(session, workspace_id)
    payload = build_export_payload(workspace, rules)
    filename = f"achievements-{workspace.slug}-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.json"
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import", response_model=AchievementRuleImportResult)
async def import_rules(
    workspace_id: int,
    body: AchievementRuleExportEnvelope,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_workspace_permission("achievement", "import")),
    s3: S3Client = Depends(get_s3),
):
    target_workspace = await _get_workspace_or_404(session, workspace_id)
    source_workspace = None
    if body.source_workspace is not None:
        source_workspace = await session.get(models.Workspace, body.source_workspace.id)
        if source_workspace is None and body.source_workspace.slug:
            source_workspace = await session.scalar(
                sa.select(models.Workspace).where(models.Workspace.slug == body.source_workspace.slug)
            )
        if source_workspace is not None and not user.is_superuser and source_workspace.id not in user.get_workspace_ids():
            raise HTTPException(status_code=403, detail="Source workspace is not accessible")

    try:
        result = await import_portable_rules(
            session,
            s3,
            target_workspace=target_workspace,
            rules=[AchievementRulePortable.model_validate(rule) for rule in body.rules],
            source_workspace=source_workspace,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"validation_errors": exc.args[0]}) from exc

    await session.commit()
    return result


@router.get("/{rule_id}", response_model=AchievementRuleRead)
async def get_rule(
    workspace_id: int,
    rule_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    _user: models.AuthUser = Depends(auth.require_workspace_permission("achievement", "read")),
):
    rule = await session.get(AchievementRule, rule_id)
    if not rule or rule.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Rule not found")
    return AchievementRuleRead.model_validate(rule, from_attributes=True)


@router.post("", response_model=AchievementRuleRead, status_code=status.HTTP_201_CREATED)
async def create_rule(
    workspace_id: int,
    body: AchievementRuleCreate,
    session: AsyncSession = Depends(db.get_async_session),
    _user: models.AuthUser = Depends(auth.require_workspace_permission("achievement", "create")),
):
    errors, _inferred_grain = validate_rule_definition(body.condition_tree, body.grain)
    if errors:
        raise HTTPException(status_code=400, detail={"validation_errors": errors})

    # Check slug uniqueness in workspace
    existing = await session.scalar(
        sa.select(AchievementRule).where(
            AchievementRule.workspace_id == workspace_id,
            AchievementRule.slug == body.slug,
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail=f"Slug '{body.slug}' already exists in workspace")

    rule = AchievementRule(
        workspace_id=workspace_id,
        **body.model_dump(),
    )
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    return AchievementRuleRead.model_validate(rule, from_attributes=True)


@router.patch("/{rule_id}", response_model=AchievementRuleRead)
async def update_rule(
    workspace_id: int,
    rule_id: int,
    body: AchievementRuleUpdate,
    session: AsyncSession = Depends(db.get_async_session),
    _user: models.AuthUser = Depends(auth.require_workspace_permission("achievement", "update")),
):
    rule = await session.get(AchievementRule, rule_id)
    if not rule or rule.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Rule not found")

    update_data = body.model_dump(exclude_unset=True)

    condition_tree_changed = "condition_tree" in update_data and update_data["condition_tree"] != rule.condition_tree

    if "condition_tree" in update_data or "grain" in update_data:
        next_condition_tree = update_data.get("condition_tree", rule.condition_tree)
        next_grain = update_data.get("grain", rule.grain)
        errors, _inferred_grain = validate_rule_definition(next_condition_tree, next_grain)
        if errors:
            raise HTTPException(status_code=400, detail={"validation_errors": errors})

    if condition_tree_changed and "rule_version" not in update_data:
        update_data["rule_version"] = rule.rule_version + 1

    for field, value in update_data.items():
        setattr(rule, field, value)

    await session.commit()
    await session.refresh(rule)

    # Auto re-evaluate when condition_tree or enabled changes
    if condition_tree_changed or "enabled" in update_data:
        if rule.enabled and rule.condition_tree:
            await run_evaluation(
                session=session,
                workspace_id=workspace_id,
                trigger=EvaluationRunTrigger.rule_version_bump,
                rule_ids=[rule.id],
            )

    return AchievementRuleRead.model_validate(rule, from_attributes=True)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    workspace_id: int,
    rule_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    _user: models.AuthUser = Depends(auth.require_workspace_permission("achievement", "delete")),
):
    rule = await session.get(AchievementRule, rule_id)
    if not rule or rule.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Rule not found")

    await session.delete(rule)
    await session.commit()


# ─── Evaluation ──────────────────────────────────────────────────────────────


@router.post("/evaluate", response_model=EvaluationRunRead)
async def trigger_evaluation(
    workspace_id: int,
    body: EvaluateRequest,
    session: AsyncSession = Depends(db.get_async_session),
    _user: models.AuthUser = Depends(auth.require_workspace_permission("achievement", "calculate")),
):
    """Trigger a manual achievement evaluation."""
    run = await run_evaluation(
        session=session,
        workspace_id=workspace_id,
        trigger=EvaluationRunTrigger.manual,
        tournament_id=body.tournament_id,
        rule_ids=body.rule_ids,
    )
    return EvaluationRunRead.model_validate(run, from_attributes=True)


@router.get("/runs", response_model=list[EvaluationRunRead])
async def list_runs(
    workspace_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    _user: models.AuthUser = Depends(auth.require_workspace_permission("achievement", "read")),
):
    query = (
        sa.select(EvaluationRun)
        .where(EvaluationRun.workspace_id == workspace_id)
        .order_by(EvaluationRun.created_at.desc())
        .limit(50)
    )
    result = await session.execute(query)
    return [EvaluationRunRead.model_validate(r, from_attributes=True) for r in result.scalars()]


# ─── Rule Users ──────────────────────────────────────────────────────────────


@router.get("/{rule_id}/users")
async def get_rule_users(
    workspace_id: int,
    rule_id: int,
    page: int = 1,
    per_page: int = 30,
    tournament_id: int | None = None,
    sort: str = "count",
    order: str = "desc",
    session: AsyncSession = Depends(db.get_async_session),
    _user: models.AuthUser = Depends(auth.require_workspace_permission("achievement", "read")),
):
    """Get users who earned a specific achievement (paginated, filterable, sortable)."""
    rule = await session.get(AchievementRule, rule_id)
    if not rule or rule.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Rule not found")

    effective_rows = build_effective_achievement_rows_subquery(
        workspace_id=workspace_id,
        achievement_rule_ids=[rule_id],
        name="admin_rule_users_effective_rows",
    )

    where_clauses = [effective_rows.c.achievement_rule_id == rule_id]
    if tournament_id is not None:
        where_clauses.append(effective_rows.c.tournament_id == tournament_id)

    total_query = sa.select(
        sa.func.count(sa.distinct(effective_rows.c.user_id))
    ).where(*where_clauses)
    total = await session.scalar(total_query) or 0

    count_col = sa.func.count().label("count")
    first_qualified_col = sa.func.min(effective_rows.c.qualified_at).label("first_qualified")
    last_tournament_col = sa.func.max(effective_rows.c.tournament_id).label("last_tournament_id")

    sort_map = {
        "count": count_col,
        "user_name": models.User.name,
        "first_qualified": first_qualified_col,
        "last_tournament_id": last_tournament_col,
    }
    sort_col = sort_map.get(sort, count_col)
    order_expr = sa.asc(sort_col) if order == "asc" else sa.desc(sort_col)

    query = (
        sa.select(
            effective_rows.c.user_id,
            models.User.name.label("user_name"),
            count_col,
            last_tournament_col,
            sa.func.max(effective_rows.c.match_id).label("last_match_id"),
            first_qualified_col,
        )
        .select_from(effective_rows)
        .join(models.User, models.User.id == effective_rows.c.user_id)
        .where(*where_clauses)
        .group_by(effective_rows.c.user_id, models.User.name)
        .order_by(order_expr)
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    result = await session.execute(query)
    rows = result.all()

    return {
        "page": page,
        "per_page": per_page,
        "total": total,
        "results": [
            {
                "user_id": row[0],
                "user_name": row[1],
                "count": row[2],
                "last_tournament_id": row[3],
                "last_match_id": row[4],
                "first_qualified": row[5].isoformat() if row[5] else None,
            }
            for row in rows
        ],
    }


# ─── Debug MVP ───────────────────────────────────────────────────────────────


@router.get("/{rule_id}/debug-mvp")
async def debug_mvp_for_match(
    workspace_id: int,
    rule_id: int,
    match_id: int,
    stat: str = "Performance",
    top_n: int = 3,
    session: AsyncSession = Depends(db.get_async_session),
    _user: models.AuthUser = Depends(auth.require_workspace_permission("achievement", "read")),
):
    """Debug endpoint: show per-player stats and ranking for a specific match."""
    # Raw stats for this match
    raw_query = sa.select(
        sa.column("user_id"),
        sa.column("team_id"),
        sa.func.sum(sa.column("value")).label("stat_value"),
    ).select_from(
        sa.text("matches.statistics")
    ).where(
        sa.text(f"match_id = {match_id} AND round = 0 AND hero_id IS NULL AND name = '{stat}'")
    ).group_by(
        sa.column("user_id"),
        sa.column("team_id"),
    ).order_by(sa.desc(sa.text("stat_value")))

    result = await session.execute(raw_query)
    players = []
    for i, row in enumerate(result, 1):
        user = await session.get(models.User, row[0])
        players.append({
            "rank": i,
            "user_id": row[0],
            "user_name": user.name if user else "?",
            "team_id": row[1],
            "stat_value": float(row[2]) if row[2] else 0,
            "in_top": i <= top_n,
        })

    # Group by team
    teams: dict[int, dict] = {}
    for p in players:
        tid = p["team_id"]
        if tid not in teams:
            teams[tid] = {"team_id": tid, "players_in_top": 0, "total_players": 0}
        teams[tid]["total_players"] += 1
        if p["in_top"]:
            teams[tid]["players_in_top"] += 1

    # Get match info
    match = await session.get(models.Match, match_id)
    match_info = None
    if match:
        match_info = {
            "match_id": match_id,
            "home_team_id": match.home_team_id,
            "away_team_id": match.away_team_id,
            "home_score": match.home_score,
            "away_score": match.away_score,
        }

    # Check if any evaluation results exist for this rule + match
    eval_results = await session.execute(
        sa.select(
            AchievementEvaluationResult.user_id,
            models.User.name.label("user_name"),
        )
        .join(models.User, models.User.id == AchievementEvaluationResult.user_id)
        .where(
            AchievementEvaluationResult.achievement_rule_id == rule_id,
            AchievementEvaluationResult.match_id == match_id,
        )
    )
    awarded_users = [{"user_id": r[0], "user_name": r[1]} for r in eval_results]

    return {
        "match": match_info,
        "stat": stat,
        "top_n": top_n,
        "players": players,
        "teams": list(teams.values()),
        "awarded_users_for_this_match": awarded_users,
    }


# ─── Dry Run (Test) ─────────────────────────────────────────────────────────


@router.post("/{rule_id}/test")
async def test_rule(
    workspace_id: int,
    rule_id: int,
    tournament_id: int | None = None,
    session: AsyncSession = Depends(db.get_async_session),
    _user: models.AuthUser = Depends(auth.require_workspace_permission("achievement", "calculate")),
):
    """Dry-run: evaluate a rule without writing results."""
    from src.core.workspace import get_division_grid
    from src.services.achievement.engine.context import EvalContext
    from src.services.achievement.engine.evaluator import evaluate

    rule = await session.get(AchievementRule, rule_id)
    if not rule or rule.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Rule not found")

    tournament = None
    if tournament_id:
        tournament = await session.get(models.Tournament, tournament_id)

    grid = await get_division_grid(session, workspace_id, tournament_id=tournament_id)

    context = EvalContext(workspace_id=workspace_id, tournament=tournament, grid=grid)
    results = await evaluate(session, rule.condition_tree, context)

    return {
        "rule_slug": rule.slug,
        "qualifying_count": len(results),
        "sample": [list(t) for t in sorted(results)[:20]],
    }


# ─── Overrides ───────────────────────────────────────────────────────────────


@library_router.get("/workspaces", response_model=list[AchievementLibraryWorkspaceRead])
async def list_library_workspaces(
    workspace_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_workspace_permission("achievement", "read")),
):
    visible_workspace_ids = _get_visible_workspace_ids(user, workspace_id)
    query = (
        sa.select(
            models.Workspace.id,
            models.Workspace.slug,
            models.Workspace.name,
            sa.func.count(AchievementRule.id).label("rules_count"),
        )
        .join(AchievementRule, AchievementRule.workspace_id == models.Workspace.id)
        .where(models.Workspace.id != workspace_id)
        .group_by(models.Workspace.id, models.Workspace.slug, models.Workspace.name)
        .having(sa.func.count(AchievementRule.id) > 0)
        .order_by(models.Workspace.name.asc())
    )
    if visible_workspace_ids is not None:
        if not visible_workspace_ids:
            return []
        query = query.where(models.Workspace.id.in_(visible_workspace_ids))

    result = await session.execute(query)
    return [
        AchievementLibraryWorkspaceRead(
            id=row.id,
            slug=row.slug,
            name=row.name,
            rules_count=row.rules_count,
        )
        for row in result
    ]


@library_router.get("", response_model=list[AchievementLibraryRuleRead])
async def list_library_rules(
    workspace_id: int,
    source_workspace_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_workspace_permission("achievement", "read")),
):
    source_workspace = await _get_source_workspace_or_404(
        session,
        target_workspace_id=workspace_id,
        source_workspace_id=source_workspace_id,
        user=user,
    )
    rules = await load_rules_for_workspace(session, source_workspace.id)
    return [
        AchievementLibraryRuleRead(
            slug=rule.slug,
            name=rule.name,
            category=str(rule.category),
            enabled=bool(rule.enabled),
            image_url=rule.image_url,
        )
        for rule in rules
    ]


@library_router.post("/import", response_model=AchievementRuleImportResult)
async def import_library_rules(
    workspace_id: int,
    body: AchievementLibraryImportRequest,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_workspace_permission("achievement", "import")),
    s3: S3Client = Depends(get_s3),
):
    target_workspace = await _get_workspace_or_404(session, workspace_id)
    source_workspace = await _get_source_workspace_or_404(
        session,
        target_workspace_id=workspace_id,
        source_workspace_id=body.source_workspace_id,
        user=user,
    )

    source_rules = await load_rules_for_workspace(session, source_workspace.id, slugs=body.slugs)
    found_slugs = {rule.slug for rule in source_rules}
    missing_slugs = sorted(set(body.slugs) - found_slugs)
    portable_rules = [AchievementRulePortable.model_validate(rule, from_attributes=True) for rule in source_rules]

    try:
        result = await import_portable_rules(
            session,
            s3,
            target_workspace=target_workspace,
            rules=portable_rules,
            source_workspace=source_workspace,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"validation_errors": exc.args[0]}) from exc

    result["warnings"].extend(
        {
            "slug": slug,
            "message": f"Rule '{slug}' was not found in workspace '{source_workspace.slug}'",
        }
        for slug in missing_slugs
    )
    await session.commit()
    return result


override_router = APIRouter(
    prefix="/ws/{workspace_id}/achievements/overrides",
    tags=["admin", "achievement-overrides"],
)


@override_router.get("", response_model=list[OverrideRead])
async def list_overrides(
    workspace_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    _user: models.AuthUser = Depends(auth.require_workspace_permission("achievement", "read")),
):
    query = (
        sa.select(AchievementOverride)
        .join(AchievementRule, AchievementRule.id == AchievementOverride.achievement_rule_id)
        .where(AchievementRule.workspace_id == workspace_id)
        .order_by(AchievementOverride.created_at.desc())
    )
    result = await session.execute(query)
    return [OverrideRead.model_validate(r, from_attributes=True) for r in result.scalars()]


@override_router.post("", response_model=OverrideRead, status_code=status.HTTP_201_CREATED)
async def create_override(
    workspace_id: int,
    body: OverrideCreate,
    session: AsyncSession = Depends(db.get_async_session),
    user: models.AuthUser = Depends(auth.require_workspace_permission("achievement", "update")),
):
    rule = await session.get(AchievementRule, body.achievement_rule_id)
    if not rule or rule.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Rule not found in workspace")

    override = AchievementOverride(
        achievement_rule_id=body.achievement_rule_id,
        user_id=body.user_id,
        tournament_id=body.tournament_id,
        match_id=body.match_id,
        action=AchievementOverrideAction(body.action),
        reason=body.reason,
        granted_by=user.id,
    )
    session.add(override)
    await session.commit()
    await session.refresh(override)
    return OverrideRead.model_validate(override, from_attributes=True)


@override_router.delete("/{override_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_override(
    workspace_id: int,
    override_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    _user: models.AuthUser = Depends(auth.require_workspace_permission("achievement", "update")),
):
    override = await session.get(AchievementOverride, override_id)
    if not override:
        raise HTTPException(status_code=404, detail="Override not found")

    # Verify workspace ownership
    rule = await session.get(AchievementRule, override.achievement_rule_id)
    if not rule or rule.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Override not found in workspace")

    await session.delete(override)
    await session.commit()
