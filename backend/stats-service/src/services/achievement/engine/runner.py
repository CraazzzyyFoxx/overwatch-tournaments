"""Evaluation runner — orchestrates achievement evaluation runs."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import sqlalchemy as sa
from loguru import logger
from sqlalchemy import exc as sa_exc
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.errors import BaseAPIException as HTTPException
from shared.division_grid import DivisionGrid
from shared.domain.achievements.context import EvalContext
from shared.domain.achievements.registry import get_specs
from shared.domain.achievements.validation import GRAIN_ARITY, requires_normalized_divisions
from shared.domain.workspace_tier import is_verified_or_trusted
from shared.messaging.config import ACHIEVEMENT_EVALUATE_DEFERRED_QUEUE
from shared.messaging.outbox import enqueue_outbox_event
from shared.models.achievements.achievement import (
    AchievementGrain,
    AchievementRule,
    EvaluationRun,
    EvaluationRunStatus,
    EvaluationRunTrigger,
)
from shared.models.tenancy.workspace import Workspace
from shared.repository.support import EvaluationRunRepository
from shared.repository.tournament import TournamentRepository
from shared.schemas.events import AchievementEvaluateEvent
from shared.services.achievements.evaluator import GrainMismatchError, evaluate
from shared.services.division_grid.access import (
    build_workspace_division_grid_normalizer,
    get_effective_division_grid,
)
from shared.services.division_grid.normalization import (
    DivisionGridNormalizationError,
    DivisionGridNormalizer,
)

from .differ import diff_and_apply, load_existing_results, persist_slice_for_grain

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
        ``achievement_evaluate.deferred``, which one low-prefetch consumer drains.
        ``parse_complete`` stays inline for every tier — it is already bounded by
        the parse that triggered it.

        Args:
            tournament_id: If set, only evaluate for this tournament.
            match_id: If set, only evaluate for this match.
            changed_tables: If set, only evaluate rules that depend on these tables.
            rule_ids: ``None`` selects every enabled rule of the trigger's discipline (every discipline for a
                workspace-wide trigger); a list selects exactly those rules, and ``[]`` selects none.
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
            # The selection is fixed now, from the trigger's owners and the rules that exist now: a seed, import or
            # create that lands before the queued message is consumed cannot widen what the caller asked for.
            trigger = await self._resolve_trigger(session, run.workspace_id, run.tournament_id, match_id)
            rules = await _select_rules(session, run.workspace_id, trigger.discipline, rule_ids, changed_tables)
            # Committed with the queued row, so there is never a queued run without its message.
            await enqueue_outbox_event(
                session,
                AchievementEvaluateEvent(
                    workspace_id=run.workspace_id,
                    tournament_id=run.tournament_id,
                    changed_tables=changed_tables or [],
                    run_id=run.id,
                    match_id=match_id,
                    rule_ids=[rule.id for rule in rules],
                    source_service="stats-service",
                ),
                exchange="",
                routing_key=ACHIEVEMENT_EVALUATE_DEFERRED_QUEUE.name,
            )
            await session.commit()
        except Exception as exc:
            # A queued row nobody will ever pick up is worse than a visible
            # failure: record why and let the caller see it.
            await _mark_run_failed(session, run, exc)
            logger.exception(f"Could not defer evaluation run {run.id}")
            raise
        logger.info(f"Evaluation run {run.id} deferred: workspace {run.workspace_id} is unverified")

    async def _resolve_trigger(
        self,
        session: AsyncSession,
        workspace_id: int,
        tournament_id: int | None,
        match_id: int | None,
    ) -> _Trigger:
        """Load the trigger's owners and verify they belong to ``workspace_id``, before any rule is selected.

        A tournament (or a match) implies exactly one discipline, so a trigger that names one never selects another
        game's rules; a trigger that names neither is workspace-wide. An owner that is missing or foreign is an error:
        silently widening to the whole workspace would evaluate every game against one game's event.
        """
        tournament = None
        discipline = None
        if tournament_id is not None:
            tournament = await self.tournaments_repo.get(session, tournament_id)
            if tournament is None or tournament.workspace_id != workspace_id:
                raise ValueError(f"tournament {tournament_id} does not belong to workspace {workspace_id}")
            discipline = tournament.discipline
        if match_id is not None:
            match = await session.get(models.StatsMatch, match_id)
            if match is None or match.workspace_id != workspace_id:
                raise ValueError(f"match {match_id} does not belong to workspace {workspace_id}")
            if discipline is not None and match.discipline != discipline:
                raise ValueError(f"match {match_id} and tournament {tournament_id} belong to different disciplines")
            if tournament_id is not None:
                owner = await session.scalar(
                    sa.select(models.Encounter.tournament_id).where(models.Encounter.id == match.encounter_id)
                )
                if owner != tournament_id:
                    raise ValueError(f"match {match_id} is not part of tournament {tournament_id}")
            discipline = match.discipline
        return _Trigger(tournament=tournament, discipline=discipline)

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
            trigger = await self._resolve_trigger(session, workspace_id, tournament_id, match_id)
            tournament = trigger.tournament
            rules = await _select_rules(session, workspace_id, trigger.discipline, rule_ids, changed_tables)

            total_created = 0
            total_removed = 0
            rules_ok = 0
            # Keyed by reason, not by rule: one grid-mapping gap fails dozens of
            # rules with the identical sentence, and one entry per rule would push
            # the real tail of the list past ``error_message``'s 1000 chars.
            failures: dict[str, list[str]] = {}
            # One memo per discipline for the whole run: per-hero rules share one query each
            # instead of one per rule, and rules of different games never share a grid,
            # a normalizer or a cached result.
            caches = _RunCaches(session, workspace_id)

            # One read per distinct persist slice for the whole run, not one per rule
            # inside its savepoint.
            persist_slices = {
                rule.id: persist_slice_for_grain(rule.grain, tournament_id=tournament_id, match_id=match_id)
                for rule in rules
            }
            existing_results = await load_existing_results(session, persist_slices)

            for rule in rules:
                # Commit the previous rule's diff before evaluating this one. ``diff_and_apply`` locks the rule
                # row (``lock_achievement_rules``) until commit: a single commit at the end of the run kept every
                # rule it had written locked through all the rules after it, so a concurrent run of the same
                # workspace queued behind those locks past ``lock_timeout``. Each rule's diff stands alone (its
                # savepoint already discards a failed rule), and the run's final status lands in the last commit.
                await session.commit()
                persist_slice = persist_slices[rule.id]
                rule_existing = existing_results.get(rule.id, {})
                # The trigger tournament narrows tournament/match-grain rules only.
                # A ``user``-grain rule is evaluated workspace-wide (within its
                # discipline): no tournament in its context, no ``min_tournament_id``
                # short-circuit, and the division normalizer whenever its tree needs one.
                eval_tournament = None if AchievementGrain(rule.grain) is AchievementGrain.user else tournament

                if not rule.enabled or not rule.condition_tree:
                    # Disabled or empty rule — remove all existing results
                    diff = await diff_and_apply(
                        session,
                        rule,
                        set(),
                        run_id,
                        evaluation_slice=persist_slice,
                        existing=rule_existing,
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
                        existing=rule_existing,
                    )
                    total_removed += len(diff.to_delete)
                    rules_ok += 1
                    continue

                if not get_specs(discipline=rule.discipline):
                    # A game with no conditions can neither evaluate nor judge its rule: report it, and leave its
                    # stored results alone instead of diffing them against an empty evaluation.
                    logger.warning(f"Skipping rule '{rule.slug}': discipline {rule.discipline!r} has no conditions")
                    failures.setdefault(f"discipline '{rule.discipline}' has no achievement conditions", []).append(
                        rule.slug
                    )
                    continue

                rule_needs_normalized_divisions = eval_tournament is None and requires_normalized_divisions(
                    rule.condition_tree, discipline=rule.discipline
                )
                normalizer: DivisionGridNormalizer | None = None
                if rule_needs_normalized_divisions:
                    try:
                        normalizer = await caches.normalizer(rule.discipline)
                    except DivisionGridNormalizationError as exc:
                        # Incomplete division grid mappings block only the rules
                        # that read divisions across grid versions. Skip them
                        # (stored results untouched), report them on the run.
                        logger.warning(f"Skipping rule '{rule.slug}': {exc}")
                        failures.setdefault(str(exc), []).append(rule.slug)
                        continue

                try:
                    async with session.begin_nested():
                        context = EvalContext(
                            workspace_id=workspace_id,
                            discipline=rule.discipline,
                            tournament=eval_tournament,
                            grid=await caches.grid(rule.discipline, eval_tournament),
                            normalizer=normalizer,
                            leaf_cache=caches.leaf_cache(rule.discipline),
                        )

                        logger.info(f"Evaluating rule '{rule.slug}' (id={rule.id})")

                        results = await evaluate(session, rule.condition_tree, context)
                        expected_arity = GRAIN_ARITY[AchievementGrain(rule.grain)]
                        if any(len(key) != expected_arity for key in results):
                            raise GrainMismatchError(
                                f"rule '{rule.slug}' grain {rule.grain} expected keys of length {expected_arity}"
                            )
                        if context.deferred_encounter_ids:
                            # The evaluator removed unknown keys after composition.
                            # Keep their exact stored awards outside reconciliation.
                            rule_existing = {
                                key: row_id
                                for key, row_id in rule_existing.items()
                                if key[2] not in context.deferred_encounter_ids
                            }
                            failures.setdefault("Incomplete series chronology; awards preserved", []).append(rule.slug)
                        diff = await diff_and_apply(
                            session,
                            rule,
                            results,
                            run_id,
                            evaluation_slice=persist_slice,
                            evidence=context.evidence,
                            existing=rule_existing,
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
                        # way, each one logging its own Sentry event. Abort the run and
                        # let the message go to the DLQ instead.
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
    ``rollback``/``commit`` raise as well. Bookkeeping must never mask or
    replace the original exception with those secondary errors, so swallow its
    failure with a warning.
    """
    try:
        await session.rollback()
        run.status = EvaluationRunStatus.failed
        run.error_message = str(exc)[:1000]
        run.finished_at = datetime.now(UTC)
        session.add(run)
        await session.commit()
    except Exception as bookkeeping_exc:
        # No ``run.id`` here: a run committed by an earlier rule is expired by the rollback above, and reading it
        # back would need the very connection that just failed. Both callers log the run id next.
        logger.warning(f"Could not persist the failed evaluation run status: {bookkeeping_exc!r}")


async def _select_rules(
    session: AsyncSession,
    workspace_id: int,
    discipline: str | None,
    rule_ids: list[int] | None,
    changed_tables: list[str] | None,
) -> list[AchievementRule]:
    """The rules one run evaluates.

    ``discipline`` is the trigger owner's game (``None`` only for a workspace-wide trigger, which spans every stored
    rule discipline). ``rule_ids=None`` is the unrestricted selection (every *enabled* rule); ``[]`` is an empty
    selection, never "all"; explicit ids may name disabled rules so the run can clean up their results.
    """
    if rule_ids is not None and not rule_ids:
        return []
    query = sa.select(AchievementRule).where(AchievementRule.workspace_id == workspace_id)
    if discipline is not None:
        query = query.where(AchievementRule.discipline == discipline)
    if rule_ids is None:
        query = query.where(AchievementRule.enabled.is_(True))
    else:
        query = query.where(AchievementRule.id.in_(rule_ids))
    rules = list((await session.execute(query.order_by(AchievementRule.id))).scalars())
    if changed_tables:
        rules = [r for r in rules if set(r.depends_on or []) & set(changed_tables)]
    return rules


@dataclass(frozen=True)
class _Trigger:
    """What a run's trigger rows own: the narrowing tournament and the one game it implies."""

    tournament: models.Tournament | None
    discipline: str | None


class _RunCaches:
    """Per-run memos, every one keyed by discipline (and the tournament scope where one applies).

    A grid, a normalizer or a leaf result of one game is never handed to a rule of another, and a missing grid is
    remembered as that discipline's failure instead of failing the rules of the others.
    """

    def __init__(self, session: AsyncSession, workspace_id: int) -> None:
        self._session = session
        self._workspace_id = workspace_id
        self._leaf: dict[str, dict[tuple, object]] = {}
        self._grids: dict[tuple[str, int | None], DivisionGrid | HTTPException] = {}
        self._normalizers: dict[str, DivisionGridNormalizer | DivisionGridNormalizationError] = {}

    def leaf_cache(self, discipline: str) -> dict[tuple, object]:
        return self._leaf.setdefault(discipline, {})

    async def grid(self, discipline: str, tournament: models.Tournament | None) -> DivisionGrid:
        key = (discipline, tournament.id if tournament is not None else None)
        if key not in self._grids:
            try:
                self._grids[key] = await get_effective_division_grid(
                    self._session, self._workspace_id, tournament_id=key[1], discipline=discipline
                )
            except HTTPException as exc:
                # ``division_grid_required``: the game has no ladder and no grid of its own. Remember it; a database
                # error is not cached, it fails the rule that hit it.
                self._grids[key] = exc
        cached = self._grids[key]
        if isinstance(cached, HTTPException):
            raise cached
        return cached

    async def normalizer(self, discipline: str) -> DivisionGridNormalizer:
        if discipline not in self._normalizers:
            try:
                self._normalizers[discipline] = await build_workspace_division_grid_normalizer(
                    self._session, self._workspace_id, discipline=discipline
                )
            except DivisionGridNormalizationError as exc:
                self._normalizers[discipline] = exc
        cached = self._normalizers[discipline]
        if isinstance(cached, DivisionGridNormalizationError):
            raise cached
        return cached
