"""League merge side effects (spec §15.5, §15.6): result snapshot, evaluation and analytics queueing, grants."""

from __future__ import annotations

import asyncio
import itertools
import os
import sys
from datetime import UTC, datetime
from unittest import IsolatedAsyncioTestCase

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared import models
from shared.core import enums
from shared.models.achievements.achievement import AchievementOverride, EvaluationRun
from shared.models.platform.outbox import EventOutbox
from shared.testing import create_test_async_engine, ensure_test_postgres
from src.services.flow.league_merge import (
    GrantSnapshot,
    MergeError,
    grant_missing,
    queue_analytics,
    queue_evaluations,
    snapshot_results,
)

_TAG = itertools.count()


class LeagueMergeAchievementsCase(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    async def asyncSetUp(self) -> None:
        ensure_test_postgres()
        self.engine = create_test_async_engine()
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        tag = f"lma-{os.getpid()}-{next(_TAG)}"
        async with self.Session() as s:
            ws = models.Workspace(slug=tag, name=tag, verification_status="verified")
            other = models.Workspace(slug=f"{tag}-u", name=tag, verification_status="unverified")
            user = models.User(name=tag)
            operator = models.AuthUser(email=f"{tag}@example.test", username=tag)
            s.add_all([ws, other, user, operator])
            await s.flush()
            member = models.WorkspaceMember(workspace_id=ws.id, player_id=user.id)
            rule = models.AchievementRule(
                workspace_id=ws.id,
                slug=tag,
                name=tag,
                description_ru=tag,
                description_en=tag,
                discipline="overwatch",
                category="standing",
                scope="tournament",
                grain="user_tournament",
                condition_tree={},
            )
            a, b, c = (
                models.Tournament(
                    workspace_id=w.id,
                    discipline="overwatch",
                    name=f"{tag}-{slug}",
                    slug=f"{tag}-{slug}",
                    status=enums.TournamentStatus.COMPLETED,
                    start_date=datetime(2026, 1, day, 18, tzinfo=UTC),
                )
                for slug, day, w in (("a", 7, ws), ("b", 14, ws), ("c", 7, other))
            )
            s.add_all([member, rule, a, b, c])
            await s.flush()
            s.add(
                models.AchievementEvaluationResult(
                    achievement_rule_id=rule.id, workspace_member_id=member.id, tournament_id=b.id, rule_version=1
                )
            )
            await s.commit()
            self.ws, self.unverified_ws, self.user, self.operator = ws.id, other.id, user.id, operator.id
            self.m0, self.rule, self.a, self.b, self.c = member.id, rule.id, a.id, b.id, c.id

    async def asyncTearDown(self) -> None:
        async with self.Session() as s:
            await s.execute(sa.delete(models.Workspace).where(models.Workspace.id.in_([self.ws, self.unverified_ws])))
            await s.execute(sa.delete(models.User).where(models.User.id == self.user))
            await s.execute(sa.delete(models.AuthUser).where(models.AuthUser.id == self.operator))
            await s.execute(
                sa.delete(EventOutbox).where(EventOutbox.payload_json["workspace_id"].as_integer() == self.ws)
            )
            await s.commit()
        await self.engine.dispose()

    async def test_a_result_lost_with_its_day_is_granted_back_on_the_target(self) -> None:
        async with self.Session() as s:
            keys = await snapshot_results(s, member_ids={self.m0}, target_of={self.b: self.a})
        assert keys == [(self.rule, self.m0, self.a, None, None)]
        async with self.Session() as s:  # the merge deletes day B: its result cascades away
            await s.execute(sa.delete(models.Tournament).where(models.Tournament.id == self.b))
            run_ids = await queue_evaluations(s, {self.ws})
            await s.execute(sa.update(EvaluationRun).where(EvaluationRun.id.in_(run_ids)).values(status="done"))
            granted = await grant_missing(s, GrantSnapshot(keys, run_ids), granted_by=self.operator)
            await s.commit()
        assert granted == {self.rule: 1}
        async with self.Session() as s:
            rows = (
                await s.execute(
                    sa.select(
                        AchievementOverride.achievement_rule_id,
                        AchievementOverride.workspace_member_id,
                        AchievementOverride.tournament_id,
                        AchievementOverride.match_id,
                        AchievementOverride.action,
                        AchievementOverride.reason,
                    ).where(AchievementOverride.workspace_member_id == self.m0)
                )
            ).all()
        assert [tuple(r) for r in rows] == [(self.rule, self.m0, self.a, None, "grant", "league merge")]

    async def test_a_result_still_there_is_not_granted(self) -> None:
        async with self.Session() as s:
            keys = await snapshot_results(s, member_ids={self.m0}, target_of={})
            run_ids = await queue_evaluations(s, {self.ws})
            await s.execute(sa.update(EvaluationRun).where(EvaluationRun.id.in_(run_ids)).values(status="partial"))
            assert await grant_missing(s, GrantSnapshot(keys, run_ids), granted_by=self.operator) == {}

    async def test_grant_is_idempotent(self) -> None:
        async with self.Session() as s:
            run_ids = await queue_evaluations(s, {self.ws})
            await s.execute(sa.update(EvaluationRun).where(EvaluationRun.id.in_(run_ids)).values(status="done"))
            snapshot = GrantSnapshot([(self.rule, self.m0, self.a, None, None)], run_ids)
            assert await grant_missing(s, snapshot, granted_by=self.operator) == {self.rule: 1}
            assert await grant_missing(s, snapshot, granted_by=self.operator) == {}

    async def test_grant_refuses_a_snapshot_without_runs(self) -> None:
        async with self.Session() as s:
            with self.assertRaisesRegex(MergeError, "no evaluation run"):
                await grant_missing(s, GrantSnapshot([(self.rule, self.m0, self.a, None, None)], []), granted_by=1)

    def test_a_snapshot_union_keeps_every_key_and_run(self) -> None:
        first = GrantSnapshot([(1, 2, 3, None, None), (1, 2, 4, None, None)], ["run-a"])
        second = GrantSnapshot([(1, 2, 4, None, None), (1, 2, 5, None, None)], ["run-b"])
        merged = second.union(first)
        assert merged.keys == [(1, 2, 3, None, None), (1, 2, 4, None, None), (1, 2, 5, None, None)]
        assert merged.run_ids == ["run-a", "run-b"]

    async def test_grant_waits_for_every_queued_run(self) -> None:
        async with self.Session() as s:
            run_ids = await queue_evaluations(s, {self.ws})
            with self.assertRaisesRegex(MergeError, f"evaluation run {run_ids[0]} is queued"):
                await grant_missing(s, GrantSnapshot([], run_ids), granted_by=self.operator)

    async def test_evaluation_is_queued_as_a_deferred_workspace_run(self) -> None:
        async with self.Session() as s:
            (run_id,) = await queue_evaluations(s, {self.ws})
            run = await s.get_one(EvaluationRun, run_id)
            outbox = (
                await s.scalars(
                    sa.select(EventOutbox)
                    .where(EventOutbox.routing_key == "achievement_evaluate.deferred")
                    .order_by(EventOutbox.id.desc())
                    .limit(1)
                )
            ).one()
        assert (run.workspace_id, run.trigger, run.tournament_id, run.status) == (self.ws, "manual", None, "queued")
        payload = outbox.payload_json
        assert (payload["run_id"], payload["rule_ids"], payload["workspace_id"]) == (run_id, None, self.ws)

    async def test_analytics_recomputes_from_the_earliest_target_of_a_verified_workspace(self) -> None:
        async with self.Session() as s:
            outcome = await queue_analytics(s, {self.b, self.a, self.c})
            job = (
                await s.scalars(sa.select(models.AnalyticsJob).where(models.AnalyticsJob.workspace_id == self.ws))
            ).one()
            event = (
                await s.scalars(sa.select(EventOutbox).where(EventOutbox.event_id == f"analytics_job:{job.id}"))
            ).one()
        assert (job.tournament_id, job.kind, job.status) == (self.a, "compute", "pending")
        assert event.routing_key == "analytics_job"
        assert outcome == {self.ws: f"job {job.id}", self.unverified_ws: "skipped: workspace_not_verified"}
