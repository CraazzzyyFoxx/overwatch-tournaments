"""Typed-RPC handlers for the achievement engine + rules admin.

Mirrors ``src/routes/achievement.py`` (global ``admin``-role calculate) and the
workspace-scoped rule/library/override admin in
``src/routes/admin/achievement_rule.py`` (gated by
``require_workspace_permission("achievement", <action>)``).

Achievement *reads* (a user's earned achievements) are owned by app-service; only
the rules engine + admin live here.

Parity notes:
- ``export`` returns the JSON payload as data (the HTTP route added a
  Content-Disposition filename; the frontend builds its own download).
- HTTP validation errors used ``detail={"validation_errors": [...]}``; the shared
  envelope flattens detail to a string, so structured validation errors arrive as
  a string (happy paths unaffected).
- ``/{rule_id}/debug-mvp`` is a dev-only endpoint not called by the frontend and
  is intentionally not migrated.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from faststream.rabbit import RabbitMessage

from shared.core.errors import BaseAPIException as HTTPException
from shared.models.achievements.achievement import (
    AchievementOverride,
    AchievementOverrideAction,
    AchievementRule,
    EvaluationRun,
    EvaluationRunTrigger,
)
from shared.repository.workspace import get_or_create_workspace_member
from shared.rpc.identity import ensure_workspace_permission
from shared.services.achievement_effective import build_effective_achievement_rows_subquery
from src import models, schemas
from src.core import db
from src.schemas.admin.achievement_rule import (
    AchievementLibraryImportRequest,
    AchievementLibraryRuleRead,
    AchievementLibraryWorkspaceRead,
    AchievementRuleCreate,
    AchievementRuleExportEnvelope,
    AchievementRulePortable,
    AchievementRuleRead,
    AchievementRuleUpdate,
    ConditionTreeValidateRequest,
    ConditionTreeValidateResponse,
    ConditionTypeInfo,
    EvaluateRequest,
    EvaluationRunRead,
    OverrideCreate,
    OverrideRead,
)
from src.services.achievement.admin_reads import (
    _get_source_workspace_or_404,
    _get_visible_workspace_ids,
    _get_workspace_or_404,
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

from . import _clients
from . import _common as c

_SF = db.async_session_maker


def _path_int(data: dict, key: str) -> int:
    try:
        return int(data[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"{key} is required") from exc


def _require_ws(data: dict, action: str) -> tuple[Any, int]:
    """Rehydrate identity + enforce the workspace-scoped achievement permission."""
    user = c.actor(data)
    c.require_active(user)
    workspace_id = _path_int(data, "workspace_id")
    ensure_workspace_permission(user, workspace_id, "achievement", action)
    return user, workspace_id


async def _run_calculate(session: Any, *, workspace_id: int, tournament_id: int | None, payload: Any) -> list[str]:
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
    await session.commit()
    return sorted(found_slugs) if payload.slugs else sorted(rule.slug for rule in rules)


def register(broker: Any, logger: Any) -> None:  # noqa: C901 - one subscriber per route, mechanical
    # ── achievement/calculate (global admin role) ──────────────────────────────
    @broker.subscriber("rpc.parser.ach.calculate")
    async def _calculate(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_active(user)
            if not user.has_role("admin"):
                raise HTTPException(status_code=403, detail="Role required: admin")
            payload = schemas.AchievementCalculateRequest.model_validate(c.payload(data) or {})
            if payload.workspace_id is None:
                raise HTTPException(
                    status_code=400, detail="workspace_id is required for global achievement calculation"
                )
            executed = await _run_calculate(
                session, workspace_id=payload.workspace_id, tournament_id=None, payload=payload
            )
            return schemas.AchievementCalculateResponse(
                tournament_id=None, executed=executed, message="Achievement calculation finished"
            )

        return await c.envelope(logger, "ach.calculate", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.ach.calculate_tournament")
    async def _calculate_tournament(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.actor(data)
            c.require_active(user)
            if not user.has_role("admin"):
                raise HTTPException(status_code=403, detail="Role required: admin")
            tournament_id = _path_int(data, "tournament_id")
            payload = schemas.AchievementCalculateRequest.model_validate(c.payload(data) or {})
            tournament = await session.get(models.Tournament, tournament_id)
            if tournament is None:
                raise HTTPException(status_code=404, detail="Tournament not found")
            workspace_id = payload.workspace_id or tournament.workspace_id
            if payload.workspace_id is not None and payload.workspace_id != tournament.workspace_id:
                raise HTTPException(status_code=400, detail="workspace_id does not match tournament workspace")
            executed = await _run_calculate(
                session, workspace_id=workspace_id, tournament_id=tournament_id, payload=payload
            )
            return schemas.AchievementCalculateResponse(
                tournament_id=tournament_id, executed=executed, message="Achievement calculation finished"
            )

        return await c.envelope(logger, "ach.calculate_tournament", op, session_factory=_SF)

    # ── rules: reference + validation ──────────────────────────────────────────
    @broker.subscriber("rpc.parser.ach.condition_types")
    async def _condition_types(data: dict, msg: RabbitMessage) -> dict:
        async def op(_session: Any) -> Any:
            _require_ws(data, "read")
            return [
                ConditionTypeInfo(
                    name=name,
                    grain=grain.value,
                    description=f"Condition type: {name}",
                    required_params=[],
                    optional_params=[],
                )
                for name, grain in sorted(LEAF_GRAINS.items())
            ]

        return await c.envelope(logger, "ach.condition_types", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.ach.validate")
    async def _validate(data: dict, msg: RabbitMessage) -> dict:
        async def op(_session: Any) -> Any:
            _require_ws(data, "read")
            body = ConditionTreeValidateRequest.model_validate(c.payload(data))
            errors = validate_condition_tree(body.condition_tree)
            grain = infer_grain(body.condition_tree) if not errors else None
            return ConditionTreeValidateResponse(
                valid=len(errors) == 0, errors=errors, inferred_grain=grain.value if grain else None
            )

        return await c.envelope(logger, "ach.validate", op, session_factory=_SF)

    # ── rules: seed / reset ────────────────────────────────────────────────────
    @broker.subscriber("rpc.parser.ach.seed")
    async def _seed(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            _user, workspace_id = _require_ws(data, "create")
            seeded, removed = await seed_workspace(session, workspace_id)
            await session.commit()
            return {"seeded": seeded, "removed": removed}

        return await c.envelope(logger, "ach.seed", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.ach.reset")
    async def _reset(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            _user, workspace_id = _require_ws(data, "update")
            seeded, removed, cleared_results, run = await hard_reset_workspace(session, workspace_id)
            await session.commit()
            return {
                "seeded": seeded,
                "removed": removed,
                "cleared_results": cleared_results,
                "run": EvaluationRunRead.model_validate(run, from_attributes=True),
            }

        return await c.envelope(logger, "ach.reset", op, session_factory=_SF)

    # ── rules: CRUD ────────────────────────────────────────────────────────────
    @broker.subscriber("rpc.parser.ach.list")
    async def _list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            _user, workspace_id = _require_ws(data, "read")
            query = sa.select(AchievementRule).where(AchievementRule.workspace_id == workspace_id)
            category = c.q1(data, "category")
            if category:
                query = query.where(AchievementRule.category == category)
            enabled = c.q1(data, "enabled")
            if enabled is not None:
                query = query.where(AchievementRule.enabled.is_(c.qbool(enabled)))
            query = query.order_by(AchievementRule.category, AchievementRule.slug)
            result = await session.execute(query)
            return [AchievementRuleRead.model_validate(r, from_attributes=True) for r in result.scalars()]

        return await c.envelope(logger, "ach.list", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.ach.export")
    async def _export(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            _user, workspace_id = _require_ws(data, "export")
            workspace = await _get_workspace_or_404(session, workspace_id)
            rules = await load_rules_for_workspace(session, workspace_id)
            return build_export_payload(workspace, rules)

        return await c.envelope(logger, "ach.export", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.ach.import")
    async def _import(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user, workspace_id = _require_ws(data, "import")
            body = AchievementRuleExportEnvelope.model_validate(c.payload(data))
            target_workspace = await _get_workspace_or_404(session, workspace_id)
            source_workspace = None
            if body.source_workspace is not None:
                source_workspace = await session.get(models.Workspace, body.source_workspace.id)
                if source_workspace is None and body.source_workspace.slug:
                    source_workspace = await session.scalar(
                        sa.select(models.Workspace).where(models.Workspace.slug == body.source_workspace.slug)
                    )
                if (
                    source_workspace is not None
                    and not user.is_superuser
                    and source_workspace.id not in user.get_workspace_ids()
                ):
                    raise HTTPException(status_code=403, detail="Source workspace is not accessible")
            try:
                result = await import_portable_rules(
                    session,
                    _clients.s3_client,
                    target_workspace=target_workspace,
                    rules=[AchievementRulePortable.model_validate(rule) for rule in body.rules],
                    source_workspace=source_workspace,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail={"validation_errors": exc.args[0]}) from exc
            await session.commit()
            return result

        return await c.envelope(logger, "ach.import", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.ach.get")
    async def _get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            _user, workspace_id = _require_ws(data, "read")
            rule = await session.get(AchievementRule, _path_int(data, "rule_id"))
            if not rule or rule.workspace_id != workspace_id:
                raise HTTPException(status_code=404, detail="Rule not found")
            return AchievementRuleRead.model_validate(rule, from_attributes=True)

        return await c.envelope(logger, "ach.get", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.ach.create")
    async def _create(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            _user, workspace_id = _require_ws(data, "create")
            body = AchievementRuleCreate.model_validate(c.payload(data))
            errors, _grain = validate_rule_definition(body.condition_tree, body.grain)
            if errors:
                raise HTTPException(status_code=400, detail={"validation_errors": errors})
            existing = await session.scalar(
                sa.select(AchievementRule).where(
                    AchievementRule.workspace_id == workspace_id, AchievementRule.slug == body.slug
                )
            )
            if existing:
                raise HTTPException(status_code=409, detail=f"Slug '{body.slug}' already exists in workspace")
            rule = AchievementRule(workspace_id=workspace_id, **body.model_dump())
            session.add(rule)
            await session.commit()
            await session.refresh(rule)
            return AchievementRuleRead.model_validate(rule, from_attributes=True)

        return await c.envelope(logger, "ach.create", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.ach.update")
    async def _update(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            _user, workspace_id = _require_ws(data, "update")
            rule = await session.get(AchievementRule, _path_int(data, "rule_id"))
            if not rule or rule.workspace_id != workspace_id:
                raise HTTPException(status_code=404, detail="Rule not found")
            body = AchievementRuleUpdate.model_validate(c.payload(data))
            update_data = body.model_dump(exclude_unset=True)
            condition_tree_changed = (
                "condition_tree" in update_data and update_data["condition_tree"] != rule.condition_tree
            )
            if "condition_tree" in update_data or "grain" in update_data:
                next_condition_tree = update_data.get("condition_tree", rule.condition_tree)
                next_grain = update_data.get("grain", rule.grain)
                errors, _grain = validate_rule_definition(next_condition_tree, next_grain)
                if errors:
                    raise HTTPException(status_code=400, detail={"validation_errors": errors})
            if condition_tree_changed and "rule_version" not in update_data:
                update_data["rule_version"] = rule.rule_version + 1
            for field, value in update_data.items():
                setattr(rule, field, value)
            await session.commit()
            await session.refresh(rule)
            if (condition_tree_changed or "enabled" in update_data) and rule.enabled and rule.condition_tree:
                await run_evaluation(
                    session=session,
                    workspace_id=workspace_id,
                    trigger=EvaluationRunTrigger.rule_version_bump,
                    rule_ids=[rule.id],
                )
            return AchievementRuleRead.model_validate(rule, from_attributes=True)

        return await c.envelope(logger, "ach.update", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.ach.delete")
    async def _delete(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            _user, workspace_id = _require_ws(data, "delete")
            rule = await session.get(AchievementRule, _path_int(data, "rule_id"))
            if not rule or rule.workspace_id != workspace_id:
                raise HTTPException(status_code=404, detail="Rule not found")
            await session.delete(rule)
            await session.commit()
            return None

        return await c.envelope(logger, "ach.delete", op, session_factory=_SF)

    # ── rules: evaluation ──────────────────────────────────────────────────────
    @broker.subscriber("rpc.parser.ach.evaluate")
    async def _evaluate(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            _user, workspace_id = _require_ws(data, "calculate")
            body = EvaluateRequest.model_validate(c.payload(data))
            run = await run_evaluation(
                session=session,
                workspace_id=workspace_id,
                trigger=EvaluationRunTrigger.manual,
                tournament_id=body.tournament_id,
                rule_ids=body.rule_ids,
            )
            await session.commit()
            return EvaluationRunRead.model_validate(run, from_attributes=True)

        return await c.envelope(logger, "ach.evaluate", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.ach.runs")
    async def _runs(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            _user, workspace_id = _require_ws(data, "read")
            query = (
                sa.select(EvaluationRun)
                .where(EvaluationRun.workspace_id == workspace_id)
                .order_by(EvaluationRun.created_at.desc())
                .limit(50)
            )
            result = await session.execute(query)
            return [EvaluationRunRead.model_validate(r, from_attributes=True) for r in result.scalars()]

        return await c.envelope(logger, "ach.runs", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.ach.rule_users")
    async def _rule_users(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            _user, workspace_id = _require_ws(data, "read")
            rule_id = _path_int(data, "rule_id")
            rule = await session.get(AchievementRule, rule_id)
            if not rule or rule.workspace_id != workspace_id:
                raise HTTPException(status_code=404, detail="Rule not found")
            page = c.q1(data, "page", int, 1)
            per_page = c.q1(data, "per_page", int, 30)
            tournament_id = c.q1(data, "tournament_id", int)
            sort = c.q1(data, "sort", str, "count")
            order = c.q1(data, "order", str, "desc")

            effective_rows = build_effective_achievement_rows_subquery(
                workspace_id=workspace_id,
                achievement_rule_ids=[rule_id],
                name="admin_rule_users_effective_rows",
            )
            where_clauses = [effective_rows.c.achievement_rule_id == rule_id]
            if tournament_id is not None:
                where_clauses.append(effective_rows.c.tournament_id == tournament_id)
            total = (
                await session.scalar(
                    sa.select(sa.func.count(sa.distinct(effective_rows.c.user_id))).where(*where_clauses)
                )
                or 0
            )

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
            rows = (await session.execute(query)).all()
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

        return await c.envelope(logger, "ach.rule_users", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.ach.test")
    async def _test(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            _user, workspace_id = _require_ws(data, "calculate")
            from src.core.workspace import get_division_grid
            from src.services.achievement.engine.context import EvalContext
            from src.services.achievement.engine.evaluator import evaluate

            rule_id = _path_int(data, "rule_id")
            rule = await session.get(AchievementRule, rule_id)
            if not rule or rule.workspace_id != workspace_id:
                raise HTTPException(status_code=404, detail="Rule not found")
            tournament_id = c.q1(data, "tournament_id", int)
            tournament = await session.get(models.Tournament, tournament_id) if tournament_id else None
            grid = await get_division_grid(session, workspace_id, tournament_id=tournament_id)
            context = EvalContext(workspace_id=workspace_id, tournament=tournament, grid=grid)
            results = await evaluate(session, rule.condition_tree, context)
            return {
                "rule_slug": rule.slug,
                "qualifying_count": len(results),
                "sample": [list(t) for t in sorted(results)[:20]],
            }

        return await c.envelope(logger, "ach.test", op, session_factory=_SF)

    # ── library ────────────────────────────────────────────────────────────────
    @broker.subscriber("rpc.parser.ach.lib_workspaces")
    async def _lib_workspaces(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user, workspace_id = _require_ws(data, "read")
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
                AchievementLibraryWorkspaceRead(id=row.id, slug=row.slug, name=row.name, rules_count=row.rules_count)
                for row in result
            ]

        return await c.envelope(logger, "ach.lib_workspaces", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.ach.lib_list")
    async def _lib_list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user, workspace_id = _require_ws(data, "read")
            source_workspace = await _get_source_workspace_or_404(
                session,
                target_workspace_id=workspace_id,
                source_workspace_id=c.require_query_int(data, "source_workspace_id"),
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

        return await c.envelope(logger, "ach.lib_list", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.ach.lib_import")
    async def _lib_import(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user, workspace_id = _require_ws(data, "import")
            body = AchievementLibraryImportRequest.model_validate(c.payload(data))
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
            portable_rules = [
                AchievementRulePortable.model_validate(rule, from_attributes=True) for rule in source_rules
            ]
            try:
                result = await import_portable_rules(
                    session,
                    _clients.s3_client,
                    target_workspace=target_workspace,
                    rules=portable_rules,
                    source_workspace=source_workspace,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail={"validation_errors": exc.args[0]}) from exc
            result["warnings"].extend(
                {"slug": slug, "message": f"Rule '{slug}' was not found in workspace '{source_workspace.slug}'"}
                for slug in missing_slugs
            )
            await session.commit()
            return result

        return await c.envelope(logger, "ach.lib_import", op, session_factory=_SF)

    # ── overrides ──────────────────────────────────────────────────────────────
    @broker.subscriber("rpc.parser.ach.overrides_list")
    async def _overrides_list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            _user, workspace_id = _require_ws(data, "read")
            # ``AchievementOverride`` is anchored on workspace_member_id; the
            # RPC/frontend contract (``OverrideRead.user_id``) still expects
            # the player identity, so resolve it via WorkspaceMember here
            # rather than exposing the raw FK.
            query = (
                sa.select(AchievementOverride, models.WorkspaceMember.player_id)
                .select_from(AchievementOverride)
                .join(
                    models.WorkspaceMember,
                    models.WorkspaceMember.id == AchievementOverride.workspace_member_id,
                )
                .join(AchievementRule, AchievementRule.id == AchievementOverride.achievement_rule_id)
                .where(AchievementRule.workspace_id == workspace_id)
                .order_by(AchievementOverride.created_at.desc())
            )
            result = await session.execute(query)
            return [
                OverrideRead(
                    id=override.id,
                    achievement_rule_id=override.achievement_rule_id,
                    user_id=player_id,
                    tournament_id=override.tournament_id,
                    match_id=override.match_id,
                    action=override.action,
                    reason=override.reason,
                    granted_by=override.granted_by,
                    created_at=override.created_at,
                )
                for override, player_id in result.all()
            ]

        return await c.envelope(logger, "ach.overrides_list", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.ach.override_create")
    async def _override_create(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user, workspace_id = _require_ws(data, "update")
            body = OverrideCreate.model_validate(c.payload(data))
            rule = await session.get(AchievementRule, body.achievement_rule_id)
            if not rule or rule.workspace_id != workspace_id:
                raise HTTPException(status_code=404, detail="Rule not found in workspace")
            member = await get_or_create_workspace_member(session, workspace_id=workspace_id, player_id=body.user_id)
            override = AchievementOverride(
                achievement_rule_id=body.achievement_rule_id,
                workspace_member_id=member.id,
                tournament_id=body.tournament_id,
                match_id=body.match_id,
                action=AchievementOverrideAction(body.action),
                reason=body.reason,
                granted_by=user.id,
            )
            session.add(override)
            await session.commit()
            await session.refresh(override)
            return OverrideRead(
                id=override.id,
                achievement_rule_id=override.achievement_rule_id,
                user_id=body.user_id,
                tournament_id=override.tournament_id,
                match_id=override.match_id,
                action=override.action,
                reason=override.reason,
                granted_by=override.granted_by,
                created_at=override.created_at,
            )

        return await c.envelope(logger, "ach.override_create", op, session_factory=_SF)

    @broker.subscriber("rpc.parser.ach.override_delete")
    async def _override_delete(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            _user, workspace_id = _require_ws(data, "update")
            override = await session.get(AchievementOverride, _path_int(data, "override_id"))
            if not override:
                raise HTTPException(status_code=404, detail="Override not found")
            rule = await session.get(AchievementRule, override.achievement_rule_id)
            if not rule or rule.workspace_id != workspace_id:
                raise HTTPException(status_code=404, detail="Override not found in workspace")
            await session.delete(override)
            await session.commit()
            return None

        return await c.envelope(logger, "ach.override_delete", op, session_factory=_SF)
