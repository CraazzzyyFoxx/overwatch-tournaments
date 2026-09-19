"""Workspace seeder for the achievement engine.

Default rule metadata (the canonical catalog + pure rule-builder functions)
lives in ``src.domain.achievement_catalog``; this module keeps only the
DB-touching ``seed_workspace``/``hard_reset_workspace`` orchestration, wrapped
in one class + singleton per ``backend/ARCHITECTURE.md``.
"""

from __future__ import annotations

import sqlalchemy as sa
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.achievements.achievement import (
    AchievementRule,
    EvaluationRun,
    EvaluationRunTrigger,
)
from shared.models.catalog.hero import Hero
from shared.repository.support import AchievementEvaluationResultRepository, AchievementRuleRepository
from src.domain.achievement_catalog import _all_default_rules
from src.domain.achievement_validation import derive_depends_on, infer_grain

from .runner import AchievementEvaluationRunnerService, achievement_evaluation_runner_service


class AchievementSeederService:
    def __init__(
        self,
        *,
        rule_repo: AchievementRuleRepository = AchievementRuleRepository(),
        results_repo: AchievementEvaluationResultRepository = AchievementEvaluationResultRepository(),
        runner: AchievementEvaluationRunnerService = achievement_evaluation_runner_service,
    ) -> None:
        self.rule_repo = rule_repo
        self.results_repo = results_repo
        self.runner = runner

    async def seed_workspace(
        self,
        session: AsyncSession,
        workspace_id: int,
        *,
        replace_catalog: bool = False,
    ) -> tuple[int, int]:
        """Seed the default achievement catalog for a workspace (upsert).

        If a rule with the same slug already exists in the workspace, its metadata
        and engine definition are updated in place. Legacy engine-only slugs are
        normalized to the canonical legacy slugs before upsert.

        When `replace_catalog=True`, unsupported rules are removed from the
        workspace after alias normalization.

        Hero K/D rules are generated from the live `overwatch.hero` table, so heroes
        synced from OW automatically get an achievement on the next seed.
        """

        heroes = list((await session.execute(sa.select(Hero))).scalars())
        all_rules = _all_default_rules(workspace_id, heroes)
        count = 0
        removed = 0
        supported_slugs = {rule.slug for rule in all_rules}

        existing_rules = list(
            (
                await session.execute(
                    sa.select(AchievementRule).where(
                        AchievementRule.workspace_id == workspace_id,
                    )
                )
            ).scalars()
        )
        existing_by_slug = {rule.slug: rule for rule in existing_rules}

        if replace_catalog:
            for existing in existing_rules:
                if existing.slug in supported_slugs:
                    continue
                await self.rule_repo.delete(session, existing)
                removed += 1

        for rule in all_rules:
            rule.depends_on = derive_depends_on(rule.condition_tree)
            if rule.condition_tree:
                inferred_grain = infer_grain(rule.condition_tree)
                if inferred_grain != rule.grain:
                    raise ValueError(
                        f"Seed rule '{rule.slug}' has grain '{rule.grain}' but infers '{inferred_grain.value}'"
                    )

            existing = existing_by_slug.get(rule.slug)

            if existing:
                existing.condition_tree = rule.condition_tree
                existing.category = rule.category
                existing.scope = rule.scope
                existing.grain = rule.grain
                existing.depends_on = rule.depends_on
                existing.name = rule.name
                existing.description_ru = rule.description_ru
                existing.description_en = rule.description_en
                existing.min_tournament_id = rule.min_tournament_id
                # Only refresh hero linkage when the seed provides it (hero rules),
                # so admin-customised images on other rules are preserved.
                if rule.hero_id is not None:
                    existing.hero_id = rule.hero_id
                if rule.image_url is not None:
                    existing.image_url = rule.image_url
            else:
                await self.rule_repo.create(session, rule)

            count += 1

        await session.commit()
        logger.info("Seeded workspace {} with {} achievement rules (upsert), removed {}", workspace_id, count, removed)
        return count, removed

    async def hard_reset_workspace(
        self,
        session: AsyncSession,
        workspace_id: int,
    ) -> tuple[int, int, int, EvaluationRun]:
        seeded, removed = await self.seed_workspace(
            session,
            workspace_id,
            replace_catalog=True,
        )

        workspace_rule_ids = sa.select(AchievementRule.id).where(AchievementRule.workspace_id == workspace_id)
        cleared_results = await self.results_repo.delete_for_rules(session, workspace_rule_ids)

        run = await self.runner.run_evaluation(
            session=session,
            workspace_id=workspace_id,
            trigger=EvaluationRunTrigger.manual,
        )
        logger.info(
            "Hard-reset workspace {}: seeded={}, removed={}, cleared_results={}, run={}",
            workspace_id,
            seeded,
            removed,
            cleared_results,
            run.id,
        )
        return seeded, removed, cleared_results, run


achievement_seeder_service = AchievementSeederService()
seed_workspace = achievement_seeder_service.seed_workspace
hard_reset_workspace = achievement_seeder_service.hard_reset_workspace
