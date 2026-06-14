"""Evaluation runner — orchestrates achievement evaluation runs."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from loguru import logger
from shared.core import errors
from shared.models.achievement import (
    AchievementRule,
    EvaluationRun,
    EvaluationRunStatus,
    EvaluationRunTrigger,
)
from shared.services.division_grid_access import (
    build_workspace_division_grid_normalizer,
    get_effective_division_grid,
)
from shared.services.division_grid_normalization import (
    DivisionGridNormalizationError,
    DivisionGridNormalizer,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src import models

from .context import EvalContext
from .differ import EvaluationSlice, diff_and_apply
from .evaluator import evaluate


async def run_evaluation(
    session: AsyncSession,
    workspace_id: int,
    trigger: EvaluationRunTrigger,
    tournament_id: int | None = None,
    match_id: int | None = None,
    changed_tables: list[str] | None = None,
    rule_ids: list[int] | None = None,
) -> EvaluationRun:
    """Execute an achievement evaluation run.

    Args:
        session: Database session.
        workspace_id: Workspace to evaluate.
        trigger: What triggered this run.
        tournament_id: If set, only evaluate for this tournament.
        match_id: If set, only evaluate for this match.
        changed_tables: If set, only evaluate rules that depend on these tables.
        rule_ids: If set, only evaluate these specific rules.
    """
    run_id = str(uuid.uuid4())
    run = EvaluationRun(
        id=run_id,
        workspace_id=workspace_id,
        trigger=trigger,
        tournament_id=tournament_id,
        status=EvaluationRunStatus.running,
        started_at=datetime.now(UTC),
    )
    session.add(run)
    await session.flush()

    try:
        rules = await _get_rules(session, workspace_id, rule_ids)

        if changed_tables:
            rules = _filter_by_depends_on(rules, set(changed_tables))

        tournament = None
        if tournament_id:
            tournament = await session.get(models.Tournament, tournament_id)
        evaluation_slice = EvaluationSlice(tournament_id=tournament_id, match_id=match_id)
        has_slice = tournament_id is not None or match_id is not None

        total_created = 0
        total_removed = 0
        normalizer: DivisionGridNormalizer | None = None

        for rule in rules:
            if not rule.enabled or not rule.condition_tree:
                # Disabled or empty rule — remove all existing results
                diff = await diff_and_apply(
                    session,
                    rule,
                    set(),
                    run_id,
                    evaluation_slice=evaluation_slice if has_slice else None,
                )
                total_removed += len(diff.to_delete)
                if diff.to_delete:
                    logger.info(f"Rule '{rule.slug}' disabled/empty: removed {len(diff.to_delete)} results")
                continue

            if rule.min_tournament_id and tournament and tournament.id < rule.min_tournament_id:
                diff = await diff_and_apply(
                    session,
                    rule,
                    set(),
                    run_id,
                    evaluation_slice=evaluation_slice if has_slice else None,
                )
                total_removed += len(diff.to_delete)
                continue

            rule_needs_normalized_divisions = tournament is None and _rule_requires_normalized_divisions(rule.condition_tree)
            if rule_needs_normalized_divisions and normalizer is None:
                try:
                    normalizer = await build_workspace_division_grid_normalizer(
                        session,
                        workspace_id,
                    )
                except DivisionGridNormalizationError as exc:
                    raise errors.ApiHTTPException(
                        status_code=409,
                        detail=[
                            errors.ApiExc(
                                code="division_grid_mapping_required",
                                msg=str(exc),
                            )
                        ],
                    ) from exc

            try:
                async with session.begin_nested():
                    grid = await _resolve_grid(session, workspace_id, tournament)
                    context = EvalContext(
                        workspace_id=workspace_id,
                        tournament=tournament,
                        grid=grid,
                        normalizer=normalizer if rule_needs_normalized_divisions else None,
                    )

                    logger.info(f"Evaluating rule '{rule.slug}' (id={rule.id})")

                    results = await evaluate(session, rule.condition_tree, context)
                    diff = await diff_and_apply(
                        session,
                        rule,
                        results,
                        run_id,
                        evaluation_slice=evaluation_slice if has_slice else None,
                    )
                    total_created += len(diff.to_insert)
                    total_removed += len(diff.to_delete)

                    logger.info(
                        f"Rule '{rule.slug}': +{len(diff.to_insert)} -{len(diff.to_delete)}"
                    )
            except Exception:
                logger.exception(f"Failed to evaluate rule '{rule.slug}'")
                continue

        run.rules_evaluated = len(rules)
        run.results_created = total_created
        run.results_removed = total_removed
        run.status = EvaluationRunStatus.done
        run.finished_at = datetime.now(UTC)

        await session.commit()

    except Exception as exc:
        await session.rollback()
        run.status = EvaluationRunStatus.failed
        run.error_message = str(exc)[:1000]
        run.finished_at = datetime.now(UTC)
        session.add(run)
        await session.commit()
        logger.exception(f"Evaluation run {run_id} failed")
        raise

    logger.info(
        f"Evaluation run {run_id} done: "
        f"{run.rules_evaluated} rules, +{run.results_created} -{run.results_removed}"
    )
    return run


async def _get_rules(
    session: AsyncSession,
    workspace_id: int,
    rule_ids: list[int] | None,
) -> list[AchievementRule]:
    query = sa.select(AchievementRule).where(
        AchievementRule.workspace_id == workspace_id,
    )
    if rule_ids:
        # When specific rules requested, include disabled ones
        # so the runner can clean up their results
        query = query.where(AchievementRule.id.in_(rule_ids))
    else:
        # Bulk evaluation: only enabled rules
        query = query.where(AchievementRule.enabled.is_(True))

    result = await session.execute(query)
    return list(result.scalars().all())


def _filter_by_depends_on(
    rules: list[AchievementRule],
    changed_tables: set[str],
) -> list[AchievementRule]:
    return [r for r in rules if set(r.depends_on or []) & changed_tables]


async def _resolve_grid(
    session: AsyncSession,
    workspace_id: int,
    tournament: models.Tournament | None,
) -> object | None:
    return await get_effective_division_grid(
        session,
        workspace_id,
        tournament_id=tournament.id if tournament is not None else None,
    )


def _rule_requires_normalized_divisions(condition: dict) -> bool:
    if "AND" in condition:
        return any(_rule_requires_normalized_divisions(child) for child in condition["AND"])
    if "OR" in condition:
        return any(_rule_requires_normalized_divisions(child) for child in condition["OR"])
    if "NOT" in condition:
        return _rule_requires_normalized_divisions(condition["NOT"])

    condition_type = condition.get("type")
    params = condition.get("params", {})
    if condition_type in {"div_level", "div_change"}:
        return True
    if condition_type == "stable_streak" and "division" in params.get("fields", []):
        return True
    if condition_type == "team_players_match":
        return _rule_requires_normalized_divisions(params.get("condition", {}))
    if condition_type == "captain_property":
        return _rule_requires_normalized_divisions(params.get("condition", {}))
    if condition_type == "player_div":
        return True
    return False
