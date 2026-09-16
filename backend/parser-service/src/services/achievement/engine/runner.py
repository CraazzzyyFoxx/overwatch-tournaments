"""Evaluation runner — orchestrates achievement evaluation runs."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from loguru import logger
from sqlalchemy import exc as sa_exc
from sqlalchemy.ext.asyncio import AsyncSession

from shared.messaging.config import ACHIEVEMENT_EVALUATE_DEFERRED_QUEUE
from shared.models.achievements.achievement import (
    AchievementGrain,
    AchievementRule,
    EvaluationRun,
    EvaluationRunStatus,
    EvaluationRunTrigger,
)
from shared.models.tenancy.workspace import Workspace
from shared.observability import publish_message
from shared.repository.support import EvaluationRunRepository
from shared.repository.tournament import TournamentRepository
from shared.schemas.events import AchievementEvaluateEvent
from shared.services.division_grid.access import (
    build_workspace_division_grid_normalizer,
    get_effective_division_grid,
)
from shared.services.division_grid.normalization import (
    DivisionGridNormalizationError,
    DivisionGridNormalizer,
)
from shared.services.workspace_tier import is_verified_or_trusted
from src import models
from src.core.broker import require_broker
from src.domain.achievement_eval_context import EvalContext
from src.domain.achievement_validation import GRAIN_ARITY

from .differ import diff_and_apply, persist_slice_for_grain
from .evaluator import GrainMismatchError, evaluate

# A full recompute an operator asked for, on a workspace nobody has vouched for.
# ``parse_complete`` is absent on purpose: it is the bounded, already-paid-for
# follow-up to a parse and stays inline for every tier.
_DEFERRABLE_TRIGGERS = (EvaluationRunTrigger.manual, EvaluationRunTrigger.rule_version_bump)

_FINISHED_RUN_STATUSES = (EvaluationRunStatus.done, EvaluationRunStatus.partial)


class AchievementEvaluationRunnerService:
    def __init__(
        self,
        *,
        runs_repo: EvaluationRunRepository = EvaluationRunRepository(),
        tournaments_repo: TournamentRepository = TournamentRepository(),
    ) -> None:
        self.runs_repo = runs_repo
        self.tournaments_repo = tournaments_repo

    async def run_evaluation(
        self,
        session: AsyncSession,
        workspace_id: int,
        trigger: EvaluationRunTrigger,
        tournament_id: int | None = None,
        match_id: int | None = None,
        changed_tables: list[str] | None = None,
        rule_ids: list[int] | None = None,
    ) -> EvaluationRun:
        """Execute an achievement evaluation run.

        A ``manual`` / ``rule_version_bump`` run for an unverified workspace is
        not executed here: it gets a ``queued`` run row and a message on
        ``achievement_evaluate.deferred``, which one low-prefetch consumer drains
        (design §4.3). ``parse_complete`` stays inline for every tier — it is
        already bounded by the parse that triggered it.

        Args:
            session: Database session.
            workspace_id: Workspace to evaluate.
            trigger: What triggered this run.
            tournament_id: If set, only evaluate for this tournament.
            match_id: If set, only evaluate for this match.
            changed_tables: If set, only evaluate rules that depend on these tables.
            rule_ids: If set, only evaluate these specific rules.
        """
        deferred = trigger in _DEFERRABLE_TRIGGERS and not await self._may_run_inline(session, workspace_id)
        run = EvaluationRun(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            trigger=trigger,
            tournament_id=tournament_id,
            status=EvaluationRunStatus.queued if deferred else EvaluationRunStatus.running,
            started_at=datetime.now(UTC),
        )
        await self.runs_repo.create(session, run)

        if deferred:
            await self._enqueue_deferred(
                session,
                run,
                match_id=match_id,
                changed_tables=changed_tables,
                rule_ids=rule_ids,
            )
            return run

        return await self._execute_run(
            session,
            run,
            match_id=match_id,
            changed_tables=changed_tables,
            rule_ids=rule_ids,
        )

    async def resume_queued_run(self, session: AsyncSession, event: AchievementEvaluateEvent) -> EvaluationRun | None:
        """Run a deferred evaluation off ``achievement_evaluate.deferred``.

        Calls ``_execute_run`` directly, never ``run_evaluation``: the tier gate
        already fired when the run was queued, so re-entering it here would just
        re-queue the same workspace forever. The queued row is reused — the
        caller was already handed its id.
        """
        run = await self.runs_repo.get(session, event.run_id) if event.run_id else None
        if run is None:
            logger.warning(f"Deferred evaluation for a missing run {event.run_id}; dropping")
            return None
        if run.status in _FINISHED_RUN_STATUSES:
            # Redelivery after the results were already applied.
            return run

        run.status = EvaluationRunStatus.running
        run.started_at = datetime.now(UTC)
        await session.flush()
        return await self._execute_run(
            session,
            run,
            match_id=event.match_id,
            changed_tables=event.changed_tables or None,
            rule_ids=event.rule_ids,
        )

    async def _may_run_inline(self, session: AsyncSession, workspace_id: int) -> bool:
        workspace = await session.get(Workspace, workspace_id)
        # A workspace that does not exist has nothing to meter; the run fails on
        # its own terms rather than sitting in a queue nobody looks at.
        return workspace is None or is_verified_or_trusted(workspace)

    async def _enqueue_deferred(
        self,
        session: AsyncSession,
        run: EvaluationRun,
        *,
        match_id: int | None,
        changed_tables: list[str] | None,
        rule_ids: list[int] | None,
    ) -> None:
        try:
            await session.commit()
            await publish_message(
                require_broker(),
                AchievementEvaluateEvent(
                    workspace_id=run.workspace_id,
                    tournament_id=run.tournament_id,
                    changed_tables=changed_tables or [],
                    run_id=run.id,
                    match_id=match_id,
                    rule_ids=rule_ids,
                ).model_dump(),
                ACHIEVEMENT_EVALUATE_DEFERRED_QUEUE,
                logger=logger.bind(workspace_id=run.workspace_id, run_id=run.id),
            )
        except Exception as exc:
            # A queued row nobody will ever pick up is worse than a visible
            # failure: record why and let the caller see it.
            await _mark_run_failed(session, run, exc)
            logger.exception(f"Could not defer evaluation run {run.id}")
            raise
        logger.info(f"Evaluation run {run.id} deferred: workspace {run.workspace_id} is unverified")

    async def _execute_run(
        self,
        session: AsyncSession,
        run: EvaluationRun,
        *,
        match_id: int | None,
        changed_tables: list[str] | None,
        rule_ids: list[int] | None,
    ) -> EvaluationRun:
        """Evaluate every selected rule for ``run`` and close it out.

        The single evaluation body: the inline path and the deferred consumer
        both land here, so neither owns a copy of it.
        """
        run_id = run.id
        workspace_id = run.workspace_id
        tournament_id = run.tournament_id

        try:
            rules = await _get_rules(session, workspace_id, rule_ids)

            if changed_tables:
                rules = _filter_by_depends_on(rules, set(changed_tables))

            tournament = None
            if tournament_id:
                tournament = await self.tournaments_repo.get(session, tournament_id)

            total_created = 0
            total_removed = 0
            rules_ok = 0
            # Keyed by reason, not by rule: one grid-mapping gap fails dozens of
            # rules with the identical sentence, and one entry per rule pushed
            # the real tail of the list past ``error_message``'s 1000 chars.
            failures: dict[str, list[str]] = {}
            normalizer: DivisionGridNormalizer | None = None
            normalizer_error: DivisionGridNormalizationError | None = None
            grid = await _resolve_grid(session, workspace_id, tournament)
            # ``user``-grain rules evaluate across the whole workspace even on a
            # tournament-triggered run, so they resolve ranks against the
            # workspace grid, not the triggering tournament's.
            workspace_grid = grid if tournament is None else await _resolve_grid(session, workspace_id, None)

            for rule in rules:
                persist_slice = persist_slice_for_grain(
                    rule.grain,
                    tournament_id=tournament_id,
                    match_id=match_id,
                )
                # The trigger tournament narrows tournament/match-grain rules only.
                # A ``user``-grain rule is evaluated workspace-wide: no tournament
                # in its context, no ``min_tournament_id`` short-circuit, and the
                # division normalizer whenever its tree needs one.
                eval_tournament = None if AchievementGrain(rule.grain) is AchievementGrain.user else tournament

                if not rule.enabled or not rule.condition_tree:
                    # Disabled or empty rule — remove all existing results
                    diff = await diff_and_apply(
                        session,
                        rule,
                        set(),
                        run_id,
                        evaluation_slice=persist_slice,
                    )
                    total_removed += len(diff.to_delete)
                    if diff.to_delete:
                        logger.info(f"Rule '{rule.slug}' disabled/empty: removed {len(diff.to_delete)} results")
                    rules_ok += 1
                    continue

                if rule.min_tournament_id and eval_tournament and eval_tournament.id < rule.min_tournament_id:
                    diff = await diff_and_apply(
                        session,
                        rule,
                        set(),
                        run_id,
                        evaluation_slice=persist_slice,
                    )
                    total_removed += len(diff.to_delete)
                    rules_ok += 1
                    continue

                rule_needs_normalized_divisions = eval_tournament is None and _rule_requires_normalized_divisions(
                    rule.condition_tree
                )
                if rule_needs_normalized_divisions and normalizer is None:
                    if normalizer_error is None:
                        try:
                            normalizer = await build_workspace_division_grid_normalizer(session, workspace_id)
                        except DivisionGridNormalizationError as exc:
                            normalizer_error = exc
                    if normalizer is None:
                        # Incomplete division grid mappings block only the rules
                        # that read divisions across grid versions. Skip them
                        # (stored results untouched), report them on the run.
                        logger.warning(f"Skipping rule '{rule.slug}': {normalizer_error}")
                        failures.setdefault(str(normalizer_error), []).append(rule.slug)
                        continue

                try:
                    async with session.begin_nested():
                        context = EvalContext(
                            workspace_id=workspace_id,
                            tournament=eval_tournament,
                            grid=workspace_grid if eval_tournament is None else grid,
                            normalizer=normalizer if rule_needs_normalized_divisions else None,
                        )

                        logger.info(f"Evaluating rule '{rule.slug}' (id={rule.id})")

                        results = await evaluate(session, rule.condition_tree, context)
                        expected_arity = GRAIN_ARITY[AchievementGrain(rule.grain)]
                        if any(len(key) != expected_arity for key in results):
                            raise GrainMismatchError(
                                f"rule '{rule.slug}' grain {rule.grain} expected keys of length {expected_arity}"
                            )
                        diff = await diff_and_apply(
                            session,
                            rule,
                            results,
                            run_id,
                            evaluation_slice=persist_slice,
                        )
                        total_created += len(diff.to_insert)
                        total_removed += len(diff.to_delete)
                        rules_ok += 1

                        logger.info(f"Rule '{rule.slug}': +{len(diff.to_insert)} -{len(diff.to_delete)}")
                except Exception as exc:
                    if _is_connection_lost(exc):
                        # The session (or its connection) is dead: Postgres restarted,
                        # the pooler dropped us, or the outer transaction is stuck in a
                        # pending rollback. Every remaining rule would fail the same
                        # way, each one logging its own Sentry event — that is how a
                        # single dead connection turned into thousands of duplicate
                        # InterfaceError/ProgrammingError events. Abort the run and let
                        # the message go to the DLQ instead.
                        logger.error(
                            f"Aborting evaluation run {run_id}: lost the database connection "
                            f"while evaluating rule '{rule.slug}'"
                        )
                        raise
                    logger.exception(f"Failed to evaluate rule '{rule.slug}'")
                    # An exception with an empty ``str`` would otherwise write a
                    # slug with no reason at all.
                    failures.setdefault(str(exc) or type(exc).__name__, []).append(rule.slug)
                    continue

            run.rules_evaluated = rules_ok
            run.results_created = total_created
            run.results_removed = total_removed
            if failures:
                run.status = EvaluationRunStatus.partial
                # ``slug[, slug]: reason``, joined with "; " — the shape the
                # admin banner parses back into one panel per reason.
                run.error_message = "; ".join(f"{', '.join(slugs)}: {reason}" for reason, slugs in failures.items())[
                    :1000
                ]
            else:
                run.status = EvaluationRunStatus.done
                run.error_message = None
            run.finished_at = datetime.now(UTC)

            await session.commit()

        except Exception as exc:
            await _mark_run_failed(session, run, exc)
            logger.exception(f"Evaluation run {run_id} failed")
            raise

        logger.info(
            f"Evaluation run {run_id} {run.status}: {run.rules_evaluated} rules, "
            f"+{run.results_created} -{run.results_removed}"
        )
        return run


achievement_evaluation_runner_service = AchievementEvaluationRunnerService()
run_evaluation = achievement_evaluation_runner_service.run_evaluation
resume_queued_run = achievement_evaluation_runner_service.resume_queued_run


def _is_connection_lost(exc: BaseException) -> bool:
    """True when the failure means the session can no longer be used at all.

    A dead connection is not a rule-level problem: it invalidates the whole run.
    ``connection_invalidated`` covers the pool marking the connection unusable;
    ``InterfaceError`` is what asyncpg raises once the socket is gone; a
    ``PendingRollbackError`` means an earlier statement already poisoned the
    outer transaction, so every subsequent ``begin_nested`` fails too.
    """
    if isinstance(exc, sa_exc.PendingRollbackError):
        return True
    if isinstance(exc, sa_exc.DBAPIError):
        return bool(exc.connection_invalidated) or isinstance(exc, sa_exc.InterfaceError)
    return False


async def _mark_run_failed(session: AsyncSession, run: EvaluationRun, exc: BaseException) -> None:
    """Best-effort audit write recording why a run failed.

    The failure is often a lost connection, in which case the session's own
    ``rollback``/``commit`` raise as well. Those *secondary* errors are what
    actually reached Sentry (``cannot call Transaction.rollback(): the underlying
    connection is closed``), burying the real cause and inflating a single
    incident into its own top-volume issue. Bookkeeping must never mask or
    replace the original exception, so swallow its failure with a warning.
    """
    try:
        await session.rollback()
        run.status = EvaluationRunStatus.failed
        run.error_message = str(exc)[:1000]
        run.finished_at = datetime.now(UTC)
        session.add(run)
        await session.commit()
    except Exception as bookkeeping_exc:
        logger.warning(f"Could not persist failed status for evaluation run {run.id}: {bookkeeping_exc!r}")


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
    if condition_type == "div_span":
        return True
    if condition_type == "team_players_match":
        return _rule_requires_normalized_divisions(params.get("condition", {}))
    if condition_type == "captain_property":
        return _rule_requires_normalized_divisions(params.get("condition", {}))
    if condition_type == "player_div":
        return True
    return False
