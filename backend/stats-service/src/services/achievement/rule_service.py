"""Achievement rule + override admin: workspace-scoped CRUD, manual runs and their read models."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.errors import BaseAPIException as HTTPException
from shared.core.pagination import PaginationParams, paginated_dict
from shared.domain.achievements.context import EvalContext
from shared.domain.achievements.registry import get_specs
from shared.domain.achievements.validation import (
    derive_depends_on,
    infer_grain,
    validate_condition_tree,
    validate_rule_definition,
)
from shared.models.achievements.achievement import (
    AchievementEvalMode,
    AchievementOverride,
    AchievementOverrideAction,
    AchievementRule,
    EvaluationRun,
    EvaluationRunTrigger,
)
from shared.repository import TournamentRepository
from shared.repository.support import AchievementOverrideRepository, AchievementRuleRepository
from shared.repository.workspace import get_or_create_workspace_member
from shared.services.achievement_effective import build_effective_achievement_rows_subquery
from shared.services.achievements.evaluator import evaluate
from src import schemas
from src.core.workspace import get_division_grid
from src.services.achievement.admin_reads import (
    get_workspace_for_discipline,
    require_character,
    require_scope_refs,
    require_tournament,
    resolve_rule_ids,
    validation_failure,
)

from .engine.runner import AchievementEvaluationRunnerService, achievement_evaluation_runner_service
from .engine.seeder import achievement_seeder_service


def _override_read(override: AchievementOverride, user_id: int) -> schemas.OverrideRead:
    return schemas.OverrideRead(
        id=override.id,
        achievement_rule_id=override.achievement_rule_id,
        user_id=user_id,
        tournament_id=override.tournament_id,
        match_id=override.match_id,
        action=override.action,
        reason=override.reason,
        granted_by=override.granted_by,
        created_at=override.created_at,
    )


class AchievementRuleService:
    def __init__(
        self,
        *,
        rule_repo: AchievementRuleRepository = AchievementRuleRepository(),
        override_repo: AchievementOverrideRepository = AchievementOverrideRepository(),
        runner: AchievementEvaluationRunnerService = achievement_evaluation_runner_service,
    ) -> None:
        self.rule_repo = rule_repo
        self.override_repo = override_repo
        self.runner = runner

    async def condition_types(
        self, session: AsyncSession, *, workspace_id: int, discipline: str
    ) -> list[schemas.ConditionTypeInfo]:
        await get_workspace_for_discipline(session, workspace_id, discipline)
        return [
            schemas.ConditionTypeInfo(
                name=spec.name,
                grain=spec.grain.value,
                description=spec.description,
                required_params=list(spec.required),
                optional_params=list(spec.optional),
                depends_on=list(spec.depends_on),
                subcondition_only=spec.subcondition_only,
                subcondition_ok=spec.subcondition_ok,
            )
            for _name, spec in sorted(get_specs(discipline=discipline).items())
        ]

    async def validate_tree(
        self, session: AsyncSession, *, workspace_id: int, body: schemas.ConditionTreeValidateRequest
    ) -> schemas.ConditionTreeValidateResponse:
        await get_workspace_for_discipline(session, workspace_id, body.discipline)
        errors = validate_condition_tree(body.condition_tree, discipline=body.discipline)
        grain = infer_grain(body.condition_tree, discipline=body.discipline) if not errors else None
        return schemas.ConditionTreeValidateResponse(
            valid=len(errors) == 0, errors=errors, inferred_grain=grain.value if grain else None
        )

    async def seed(self, session: AsyncSession, *, workspace_id: int, discipline: str) -> dict[str, int]:
        await get_workspace_for_discipline(session, workspace_id, discipline)
        seeded, removed = await achievement_seeder_service.seed_workspace(session, workspace_id, discipline=discipline)
        return {"seeded": seeded, "removed": removed}

    async def reset(self, session: AsyncSession, *, workspace_id: int, discipline: str) -> dict[str, Any]:
        await get_workspace_for_discipline(session, workspace_id, discipline)
        seeded, removed, cleared_results, run = await achievement_seeder_service.hard_reset_workspace(
            session, workspace_id, discipline=discipline
        )
        return {
            "seeded": seeded,
            "removed": removed,
            "cleared_results": cleared_results,
            "run": schemas.EvaluationRunRead.model_validate(run, from_attributes=True),
        }

    async def list_rules(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        params: schemas.AchievementRuleListParams,
    ) -> dict[str, Any]:
        # No game is every game of the workspace (spec §8.1); each row names its own `discipline`.
        scope = (
            AchievementRule.workspace_id == workspace_id,
            *([AchievementRule.discipline == params.discipline] if params.discipline is not None else []),
        )
        query = sa.select(AchievementRule).where(*scope)
        count_query = sa.select(sa.func.count()).select_from(AchievementRule).where(*scope)
        if params.search:
            term = f"%{params.search}%"
            match = sa.or_(AchievementRule.name.ilike(term), AchievementRule.slug.ilike(term))
            query = query.where(match)
            count_query = count_query.where(match)
        if params.category:
            query = query.where(AchievementRule.category == params.category)
            count_query = count_query.where(AchievementRule.category == params.category)
        if params.enabled is not None:
            query = query.where(AchievementRule.enabled.is_(params.enabled))
            count_query = count_query.where(AchievementRule.enabled.is_(params.enabled))
        query = params.apply_pagination_sort(query, AchievementRule)
        rules = (await session.execute(query)).scalars().all()
        total = (await session.execute(count_query)).scalar_one()
        return paginated_dict(
            [schemas.AchievementRuleRead.model_validate(rule, from_attributes=True) for rule in rules],
            int(total or 0),
            params,
        )

    async def get_rule(
        self, session: AsyncSession, *, workspace_id: int, rule_id: int, missing: str = "Rule not found"
    ) -> AchievementRule:
        """The workspace's rule; another workspace's id is the same 404 as an absent one."""
        rule = await self.rule_repo.get(session, rule_id)
        if not rule or rule.workspace_id != workspace_id:
            raise HTTPException(status_code=404, detail=missing)
        return rule

    async def _require_free_slug(
        self, session: AsyncSession, *, workspace_id: int, slug: str, except_rule_id: int | None = None
    ) -> None:
        """``UNIQUE(workspace_id, slug)`` is the identity across games: a taken slug is a 409, whichever game owns it,
        and the rule that owns it is left exactly as it was."""
        existing = await session.scalar(
            sa.select(AchievementRule).where(AchievementRule.workspace_id == workspace_id, AchievementRule.slug == slug)
        )
        if existing is not None and existing.id != except_rule_id:
            raise HTTPException(status_code=409, detail=f"Slug '{slug}' already exists in workspace")

    async def create_rule(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        rule_data: dict[str, Any],
    ) -> AchievementRule:
        discipline = rule_data["discipline"]
        await get_workspace_for_discipline(session, workspace_id, discipline)
        errors, _grain = validate_rule_definition(
            rule_data["condition_tree"], rule_data["grain"], discipline=discipline
        )
        if errors:
            raise validation_failure(errors)
        await self._require_free_slug(session, workspace_id=workspace_id, slug=rule_data["slug"])
        await require_character(session, discipline=discipline, entity_id=rule_data.get("entity_id"))
        await require_tournament(
            session,
            workspace_id=workspace_id,
            discipline=discipline,
            tournament_id=rule_data.get("min_tournament_id"),
        )
        # Derived, never taken from the caller: a hand-written ``depends_on`` that
        # misses a table is a rule that silently stops re-evaluating.
        rule_data["depends_on"] = derive_depends_on(rule_data.get("condition_tree") or {}, discipline=discipline)
        rule = AchievementRule(workspace_id=workspace_id, **rule_data)
        await self.rule_repo.create(session, rule)
        await session.commit()
        await session.refresh(rule)
        return rule

    async def update_rule(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        rule_id: int,
        update_data: dict[str, Any],
    ) -> AchievementRule:
        """Apply ``update_data`` (the fields the caller actually sent; the discipline is never one of them).

        An omitted field is untouched; an explicit empty ``condition_tree`` replaces the tree with an empty one and an
        explicit ``entity_id: null`` clears the link.
        """
        rule = await self.get_rule(session, workspace_id=workspace_id, rule_id=rule_id)
        condition_tree_changed = (
            "condition_tree" in update_data and update_data["condition_tree"] != rule.condition_tree
        )
        if "condition_tree" in update_data or "grain" in update_data:
            errors, _grain = validate_rule_definition(
                update_data.get("condition_tree", rule.condition_tree),
                update_data.get("grain", rule.grain),
                discipline=rule.discipline,
            )
            if errors:
                raise validation_failure(errors)
        # A workspace can drop a discipline without deleting its rules; those rules are frozen until it is re-enabled.
        workspace = await get_workspace_for_discipline(session, workspace_id, rule.discipline)
        if "slug" in update_data:
            await self._require_free_slug(
                session, workspace_id=workspace_id, slug=update_data["slug"], except_rule_id=rule.id
            )
        await require_character(session, discipline=rule.discipline, entity_id=update_data.get("entity_id"))
        await require_tournament(
            session,
            workspace_id=workspace_id,
            discipline=rule.discipline,
            tournament_id=update_data.get("min_tournament_id"),
        )
        if condition_tree_changed and "rule_version" not in update_data:
            update_data["rule_version"] = rule.rule_version + 1
        if condition_tree_changed:
            update_data["depends_on"] = derive_depends_on(update_data["condition_tree"], discipline=rule.discipline)
        else:
            update_data.pop("depends_on", None)
        await self.rule_repo.update_fields(session, rule, update_data)
        await session.refresh(rule)
        # ``manual`` means only an admin's run recomputes, a rule edit included.
        if (
            (condition_tree_changed or "enabled" in update_data)
            and rule.enabled
            and rule.condition_tree
            and workspace.achievement_eval_mode != AchievementEvalMode.manual
        ):
            # ``run_evaluation`` owns the commit for this path.
            await self.runner.run_evaluation(
                session,
                workspace_id,
                EvaluationRunTrigger.rule_version_bump,
                rule_ids=[rule.id],
            )
        else:
            await session.commit()
        return rule

    async def delete_rule(self, session: AsyncSession, *, workspace_id: int, rule_id: int) -> None:
        rule = await self.get_rule(session, workspace_id=workspace_id, rule_id=rule_id)
        await self.rule_repo.delete(session, rule)
        await session.commit()

    async def calculation_workspace(
        self, session: AsyncSession, *, tournament_id: int, workspace_id: int | None
    ) -> int:
        """The workspace a tournament-scoped calculation runs in; a payload workspace must be the tournament's."""
        tournament = await TournamentRepository().get(session, tournament_id)
        if tournament is None:
            raise HTTPException(status_code=404, detail="Tournament not found")
        if workspace_id is not None and workspace_id != tournament.workspace_id:
            raise HTTPException(status_code=400, detail="workspace_id does not match tournament workspace")
        return tournament.workspace_id

    async def calculate(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        tournament_id: int | None,
        payload: schemas.AchievementCalculateRequest,
    ) -> schemas.AchievementCalculateResponse:
        """Run the named rules (or every enabled one) of the payload's discipline; unknown slugs are a 400."""
        discipline = payload.discipline
        await get_workspace_for_discipline(session, workspace_id, discipline)
        await require_scope_refs(session, workspace_id=workspace_id, discipline=discipline, tournament_id=tournament_id)
        if payload.ensure_created:
            await achievement_seeder_service.seed_workspace(session, workspace_id, discipline=discipline)
        query = sa.select(AchievementRule).where(
            AchievementRule.workspace_id == workspace_id, AchievementRule.discipline == discipline
        )
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
        await self.runner.run_evaluation(
            session,
            workspace_id,
            EvaluationRunTrigger.manual,
            tournament_id=tournament_id,
            rule_ids=[rule.id for rule in rules],
        )
        return schemas.AchievementCalculateResponse(
            tournament_id=tournament_id,
            executed=sorted(found_slugs) if payload.slugs else sorted(rule.slug for rule in rules),
            message="Achievement calculation finished",
        )

    async def evaluate(
        self, session: AsyncSession, *, workspace_id: int, body: schemas.EvaluateRequest
    ) -> schemas.EvaluationRunRead:
        await get_workspace_for_discipline(session, workspace_id, body.discipline)
        await require_scope_refs(
            session, workspace_id=workspace_id, discipline=body.discipline, tournament_id=body.tournament_id
        )
        run = await self.runner.run_evaluation(
            session,
            workspace_id,
            EvaluationRunTrigger.manual,
            tournament_id=body.tournament_id,
            rule_ids=await resolve_rule_ids(
                session, workspace_id=workspace_id, discipline=body.discipline, rule_ids=body.rule_ids
            ),
        )
        return schemas.EvaluationRunRead.model_validate(run, from_attributes=True)

    async def list_runs(self, session: AsyncSession, *, workspace_id: int) -> list[schemas.EvaluationRunRead]:
        result = await session.execute(
            sa.select(EvaluationRun)
            .where(EvaluationRun.workspace_id == workspace_id)
            .order_by(EvaluationRun.created_at.desc())
            .limit(50)
        )
        return [schemas.EvaluationRunRead.model_validate(r, from_attributes=True) for r in result.scalars()]

    async def rule_users(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        rule_id: int,
        page: int,
        per_page: int,
        tournament_id: int | None,
        sort: str,
        order: str,
    ) -> dict[str, Any]:
        """The players holding a rule's effective awards, one row per player, paged and sorted."""
        await self.get_rule(session, workspace_id=workspace_id, rule_id=rule_id)
        effective_rows = build_effective_achievement_rows_subquery(
            workspace_id=workspace_id,
            achievement_rule_ids=[rule_id],
            name="admin_rule_users_effective_rows",
        )
        where_clauses = [effective_rows.c.achievement_rule_id == rule_id]
        if tournament_id is not None:
            where_clauses.append(effective_rows.c.tournament_id == tournament_id)
        total = (
            await session.scalar(sa.select(sa.func.count(sa.distinct(effective_rows.c.user_id))).where(*where_clauses))
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
        return paginated_dict(
            [
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
            total,
            PaginationParams(page=page, per_page=per_page),
        )

    async def test_rule(
        self, session: AsyncSession, *, workspace_id: int, rule_id: int, tournament_id: int | None
    ) -> dict[str, Any]:
        """Evaluate a rule's tree without storing anything; the first 20 qualifying tuples are the sample."""
        rule = await self.get_rule(session, workspace_id=workspace_id, rule_id=rule_id)
        tournament = await require_tournament(
            session, workspace_id=workspace_id, discipline=rule.discipline, tournament_id=tournament_id
        )
        grid = await get_division_grid(session, workspace_id, tournament_id=tournament_id, discipline=rule.discipline)
        context = EvalContext(workspace_id=workspace_id, discipline=rule.discipline, tournament=tournament, grid=grid)
        results = await evaluate(session, rule.condition_tree, context)
        return {
            "rule_slug": rule.slug,
            "qualifying_count": len(results),
            "sample": [list(t) for t in sorted(results)[:20]],
        }

    async def list_overrides(
        self, session: AsyncSession, *, workspace_id: int, discipline: str
    ) -> list[schemas.OverrideRead]:
        # An override is anchored on workspace_member_id; the wire contract carries the player id.
        result = await session.execute(
            sa.select(AchievementOverride, models.WorkspaceMember.player_id)
            .select_from(AchievementOverride)
            .join(models.WorkspaceMember, models.WorkspaceMember.id == AchievementOverride.workspace_member_id)
            .join(AchievementRule, AchievementRule.id == AchievementOverride.achievement_rule_id)
            .where(AchievementRule.workspace_id == workspace_id, AchievementRule.discipline == discipline)
            .order_by(AchievementOverride.created_at.desc())
        )
        return [_override_read(override, player_id) for override, player_id in result.all()]

    async def create_rule_override(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        rule_id: int,
        user_id: int,
        granted_by: int,
        tournament_id: int | None,
        match_id: int | None,
        action: AchievementOverrideAction,
        reason: str,
    ) -> schemas.OverrideRead:
        """A manual grant/revoke on a rule: its discipline must still be enabled for the workspace, and the
        tournament/match it names are the rule's game's (same workspace, same discipline, agreeing)."""
        rule = await self.get_rule(
            session, workspace_id=workspace_id, rule_id=rule_id, missing="Rule not found in workspace"
        )
        await get_workspace_for_discipline(session, workspace_id, rule.discipline)
        await require_scope_refs(
            session,
            workspace_id=workspace_id,
            discipline=rule.discipline,
            tournament_id=tournament_id,
            match_id=match_id,
        )
        member = await get_or_create_workspace_member(session, workspace_id=workspace_id, player_id=user_id)
        override = AchievementOverride(
            achievement_rule_id=rule.id,
            workspace_member_id=member.id,
            tournament_id=tournament_id,
            match_id=match_id,
            action=action,
            reason=reason,
            granted_by=granted_by,
        )
        return _override_read(await self.create_override(session, override), user_id)

    async def create_override(self, session: AsyncSession, override: AchievementOverride) -> AchievementOverride:
        await self.override_repo.create(session, override)
        await session.commit()
        await session.refresh(override)
        return override

    async def delete_workspace_override(self, session: AsyncSession, *, workspace_id: int, override_id: int) -> None:
        override = await self.override_repo.get(session, override_id)
        if not override:
            raise HTTPException(status_code=404, detail="Override not found")
        await self.get_rule(
            session,
            workspace_id=workspace_id,
            rule_id=override.achievement_rule_id,
            missing="Override not found in workspace",
        )
        await self.delete_override(session, override)

    async def delete_override(self, session: AsyncSession, override: AchievementOverride) -> None:
        await self.override_repo.delete(session, override)
        await session.commit()


achievement_rule_service = AchievementRuleService()
