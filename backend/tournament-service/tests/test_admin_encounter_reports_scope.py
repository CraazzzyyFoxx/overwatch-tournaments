"""The encounter-reports inbox: aggregates scoped to the workspace, ``last_resolution`` resolved per page.

Real Postgres (``EncounterWriterCase``), two workspaces with reports and audit rows of their own: a counter, a
chip or a resolution computed over the wrong rows shows up as a wrong number here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from shared.core import enums
from shared.models.encounter import Encounter, EncounterResultAudit
from shared.models.encounter.report import EncounterTeamReport, EncounterTeamReportResult
from shared.models.identity.user import User
from shared.services.encounter import participants
from shared.tests.encounter_writer_case import EncounterWriterCase
from src import schemas
from src.services.admin.encounter_reports import encounter_reports_service

_A = enums.EncounterResultAuditAction


class ReportsInboxScopeTests(EncounterWriterCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.other = await self._seed()

    async def seat(self, ids: dict[str, int]) -> list[int]:
        """Fill both seats of the workspace's encounter; their participation ids in slot order."""
        async with self.Session() as s:
            encounter = await s.get_one(Encounter, ids["e"])
            seats = [
                await participants.place_team(
                    s, encounter, slot=slot, team_id=ids[f"team{slot - 1}"], name=f"T{slot - 1}", seed=slot, members=()
                )
                for slot in (1, 2)
            ]
            await s.commit()
            return [seat.id for seat in seats]

    async def report(self, encounter_id: int, claimant: int, scores: dict[int, float]) -> None:
        """One participation's series report: a score per participation."""
        async with self.Session() as s:
            report = EncounterTeamReport(
                encounter_id=encounter_id, encounter_team_id=claimant, games_played=2, basis_version=0
            )
            s.add(report)
            await s.flush()
            s.add_all(
                EncounterTeamReportResult(
                    report_id=report.id, encounter_id=encounter_id, encounter_team_id=seat, score=score
                )
                for seat, score in scores.items()
            )
            await s.commit()

    async def audit(self, encounter_id: int, version: int, action: _A, at: datetime, actor: int | None = None) -> None:
        async with self.Session() as s:
            s.add(
                EncounterResultAudit(
                    encounter_id=encounter_id,
                    result_version=version,
                    snapshot_scope=enums.AuditSnapshotScope.ENCOUNTER.value,
                    actor_user_id=actor,
                    action=action,
                    to_result_status=enums.EncounterResultStatus.CONFIRMED,
                    after=[],
                    source="admin",
                    created_at=at,
                )
            )
            await s.commit()

    async def page(self, ids: dict[str, int], **filters: object) -> schemas.EncounterReportsRow | None:
        """The workspace's inbox under ``filters``: its single row, or ``None`` when nothing matches."""
        async with self.Session() as s:
            result = await encounter_reports_service.list_encounter_reports(
                s, workspace_id=ids["ws"], params=schemas.EncounterReportsSearchParams(page=1, per_page=10, **filters)
            )
        self.assertEqual(len(result.results), result.total)
        self.assertLessEqual(result.total, 1)
        return result.results[0] if result.results else None

    async def chips(self, ids: dict[str, int]) -> tuple[int, int]:
        async with self.Session() as s:
            stats = await encounter_reports_service.get_reports_stats(
                s, workspace_id=ids["ws"], params=schemas.EncounterReportsSearchParams()
            )
        return stats.mismatch_count, stats.awaiting_second_count

    async def test_each_workspace_counts_only_its_own_reports(self) -> None:
        mine = await self.seat(self.ids)
        theirs = await self.seat(self.other)
        # Here one seat has reported and the other still owes its report; there both reported and disagree.
        await self.report(self.ids["e"], mine[0], {mine[0]: 2.0, mine[1]: 1.0})
        await self.report(self.other["e"], theirs[0], {theirs[0]: 2.0, theirs[1]: 1.0})
        await self.report(self.other["e"], theirs[1], {theirs[0]: 1.0, theirs[1]: 2.0})

        row = await self.page(self.ids)
        assert row is not None
        self.assertEqual((self.ids["e"], 1, None), (row.id, row.reported_count, row.standings_match))
        self.assertIsNone(await self.page(self.ids, mismatch_only=True))
        self.assertIsNotNone(await self.page(self.ids, reported_count=1))
        self.assertIsNone(await self.page(self.ids, reported_count=2))
        self.assertEqual((0, 1), await self.chips(self.ids))

        row = await self.page(self.other)
        assert row is not None
        self.assertEqual((self.other["e"], 2, False), (row.id, row.reported_count, row.standings_match))
        self.assertIsNotNone(await self.page(self.other, mismatch_only=True))
        self.assertIsNone(await self.page(self.other, reported_count=1))
        self.assertEqual((1, 0), await self.chips(self.other))

    async def test_last_resolution_is_the_newest_audit_row_of_each_page_row(self) -> None:
        at = datetime(2026, 1, 1, tzinfo=UTC)
        async with self.Session() as s:
            second, quiet = (
                Encounter(
                    workspace_id=self.ids["ws"],
                    discipline="overwatch",
                    tournament_id=self.ids["t"],
                    scoring_rule_id=self.ids["rule"],
                    name=name,
                    slot_count=2,
                    best_of=3,
                    status=enums.EncounterStatus.OPEN,
                )
                for name in ("E2", "E3")
            )
            s.add_all([second, quiet])
            await s.commit()
            names = dict((await s.execute(sa.select(User.id, User.name).where(User.id.in_(self.users)))).all())
        first = self.ids["e"]
        await self.audit(first, 1, _A.AUTO_PENDING, at)
        await self.audit(first, 2, _A.CONFIRM, at + timedelta(hours=1), self.users[0])
        # Same instant: the row written later wins.
        await self.audit(second.id, 1, _A.AUTO_DISPUTE, at)
        await self.audit(second.id, 2, _A.REOPEN, at, self.users[1])
        # Newer than everything here, but another workspace's.
        await self.audit(self.other["e"], 1, _A.IMPORT, at + timedelta(days=1))

        resolutions = {}
        for page in (1, 2, 3):
            async with self.Session() as s:
                result = await encounter_reports_service.list_encounter_reports(
                    s, workspace_id=self.ids["ws"], params=schemas.EncounterReportsSearchParams(page=page, per_page=1)
                )
            self.assertEqual(3, result.total)
            (row,) = result.results
            resolution = row.last_resolution
            resolutions[row.id] = resolution and (
                resolution.action,
                resolution.actor_user_id,
                resolution.actor_name,
                resolution.created_at,
            )

        self.assertEqual(
            {
                first: (_A.CONFIRM, self.users[0], names[self.users[0]], at + timedelta(hours=1)),
                second.id: (_A.REOPEN, self.users[1], names[self.users[1]], at),
                quiet.id: None,
            },
            resolutions,
        )
