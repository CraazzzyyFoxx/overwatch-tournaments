"""Achievement rule + override admin CRUD.

Absorbs the raw ``AchievementRule``/``AchievementOverride`` writes that used to
live inline in ``src/rpc/achievements.py``'s ``_create``/``_update``/``_delete``/
``_override_create``/``_override_delete`` handlers, routing them through the
existing ``AchievementRuleRepository``/``AchievementOverrideRepository``
(``shared/repository/support.py``).
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.errors import BaseAPIException as HTTPException
from shared.core.pagination import paginated_dict
from shared.models.achievements.achievement import (
    AchievementOverride,
    AchievementRule,
    EvaluationRunTrigger,
)
from shared.repository.support import AchievementOverrideRepository, AchievementRuleRepository
from src import schemas

from .engine.runner import AchievementEvaluationRunnerService, achievement_evaluation_runner_service


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

    async def list_rules(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        params: schemas.AchievementRuleListParams,
    ) -> dict[str, Any]:
        query = sa.select(AchievementRule).where(AchievementRule.workspace_id == workspace_id)
        count_query = sa.select(sa.func.count()).select_from(AchievementRule).where(
            AchievementRule.workspace_id == workspace_id
        )
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

    async def create_rule(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        rule_data: dict[str, Any],
    ) -> AchievementRule:
        existing = await session.scalar(
            sa.select(AchievementRule).where(
                AchievementRule.workspace_id == workspace_id, AchievementRule.slug == rule_data["slug"]
            )
        )
        if existing:
            raise HTTPException(status_code=409, detail=f"Slug '{rule_data['slug']}' already exists in workspace")
        rule = AchievementRule(workspace_id=workspace_id, **rule_data)
        await self.rule_repo.create(session, rule)
        await session.commit()
        await session.refresh(rule)
        return rule

    async def update_rule(
        self,
        session: AsyncSession,
        rule: AchievementRule,
        *,
        workspace_id: int,
        update_data: dict[str, Any],
        condition_tree_changed: bool,
    ) -> AchievementRule:
        if condition_tree_changed and "rule_version" not in update_data:
            update_data["rule_version"] = rule.rule_version + 1
        await self.rule_repo.update_fields(session, rule, update_data)
        await session.refresh(rule)
        if (condition_tree_changed or "enabled" in update_data) and rule.enabled and rule.condition_tree:
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

    async def delete_rule(self, session: AsyncSession, rule: AchievementRule) -> None:
        await self.rule_repo.delete(session, rule)
        await session.commit()

    async def create_override(self, session: AsyncSession, override: AchievementOverride) -> AchievementOverride:
        await self.override_repo.create(session, override)
        await session.commit()
        await session.refresh(override)
        return override

    async def delete_override(self, session: AsyncSession, override: AchievementOverride) -> None:
        await self.override_repo.delete(session, override)
        await session.commit()


achievement_rule_service = AchievementRuleService()
