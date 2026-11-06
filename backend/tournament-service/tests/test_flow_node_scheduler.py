"""The scheduler over ``flow_node_schedule``, the node schedule write and the archive toggle (spec §9, Decisions 4, 14)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa

from shared import models
from shared.core import enums
from shared.core.errors import ApiHTTPException
from src.schemas.flow import FlowNodeScheduleEntry
from src.services.admin.tournament import tournament_service
from src.services.flow.schedule import flow_node_schedule_service
from src.services.tournament import auto_transitions
from tests._flow_case import FlowCase

_NOW = datetime.now(UTC)


class SchedulerTests(FlowCase):
    async def due(self, node_id: int, phase: str, starts_in: timedelta = timedelta(minutes=-5)) -> None:
        async with self.Session() as s:
            s.add(models.FlowNodeSchedule(node_id=node_id, phase=phase, starts_at=datetime.now(UTC) + starts_in))
            await s.commit()

    async def tick(self, *node_ids: int) -> list[dict[str, Any]]:
        results = await auto_transitions.run_due_transitions(self.Session)
        return [r for r in results if r["node_id"] in node_ids]

    async def seated_stage(self) -> tuple[int, int]:
        stage_id, node_id = await self.stage()
        async with self.Session() as s:
            teams = [
                models.Team(tournament_id=self.tournament_id, name=f"T{i}", balancer_name=f"T{i}") for i in range(2)
            ]
            item = models.StageItem(stage_id=stage_id, name="A", type=enums.StageItemType.GROUP, order=0)
            s.add_all([*teams, item])
            await s.flush()
            s.add_all(
                models.StageItemInput(
                    stage_item_id=item.id, slot=slot, input_type=enums.StageItemInputType.FINAL, team_id=team.id
                )
                for slot, team in enumerate(teams, 1)
            )
            await s.execute(sa.update(models.FlowNode).where(models.FlowNode.id == node_id).values(status="ready"))
            await s.commit()
        return stage_id, node_id

    async def test_due_registration_open_row_opens_the_node(self) -> None:
        reg = await self.node("registration")
        await self.due(reg, "open")
        [result] = await self.tick(reg)
        self.assertEqual(("success", "draft", "open"), (result["status"], result["old_status"], result["new_status"]))
        self.assertEqual(self.tournament_id, result["tournament_id"])
        self.assertEqual("open", await self.node_status(reg))

    async def test_not_due_row_leaves_the_node(self) -> None:
        reg = await self.node("registration")
        await self.due(reg, "open", timedelta(hours=1))
        self.assertEqual([], await self.tick(reg))
        self.assertEqual("draft", await self.node_status(reg))

    async def test_due_ness_is_per_node(self) -> None:
        a = await self.node("registration", name="Day 1")
        b = await self.node("registration", name="Day 2")
        await self.due(a, "open")
        await self.due(b, "open", timedelta(hours=1))
        await self.tick(a, b)
        self.assertEqual(("open", "draft"), (await self.node_status(a), await self.node_status(b)))

    async def test_check_in_row_moves_open_to_check_in(self) -> None:
        reg = await self.node("registration", "open")
        await self.due(reg, "check_in")
        [result] = await self.tick(reg)
        self.assertEqual("success", result["status"])
        self.assertEqual("check_in", await self.node_status(reg))

    async def test_stage_start_moves_ready_to_live(self) -> None:
        stage_id, node_id = await self.seated_stage()
        await self.due(node_id, "start")
        [result] = await self.tick(node_id)
        self.assertEqual(("success", "ready", "live"), (result["status"], result["old_status"], result["new_status"]))
        self.assertEqual("live", await self.node_status(node_id))
        async with self.Session() as s:
            encounters = await s.scalar(sa.select(sa.func.count()).where(models.BracketEncounter.stage_id == stage_id))
        self.assertGreater(encounters, 0)

    async def test_formation_start_moves_draft_to_forming(self) -> None:
        reg = await self.node("registration", "closed")
        form = await self.node("formation", config={"mode": "manual"})
        await self.edge(reg, "participants", form, "players")
        await self.due(form, "start")
        [result] = await self.tick(form)
        self.assertEqual(
            ("success", "draft", "forming"), (result["status"], result["old_status"], result["new_status"])
        )
        self.assertEqual("forming", await self.node_status(form))

    async def test_scheduler_skips_node_already_past_phase_source(self) -> None:
        reg = await self.node("registration", "closed")
        await self.due(reg, "open")
        self.assertEqual([], await self.tick(reg))
        self.assertEqual("closed", await self.node_status(reg))

    async def test_paused_tournament_is_untouched(self) -> None:
        reg = await self.node("registration")
        await self.due(reg, "open")
        async with self.Session() as s:
            await s.execute(
                sa.update(models.Tournament)
                .where(models.Tournament.id == self.tournament_id)
                .values(auto_transitions_enabled=False)
            )
            await s.commit()
        self.assertEqual([], await self.tick(reg))
        self.assertEqual("draft", await self.node_status(reg))

    async def test_missing_form_is_skipped_not_failed(self) -> None:
        reg = await self.node("registration")
        await self.due(reg, "open")
        async with self.Session() as s:
            await s.execute(
                sa.delete(models.RegistrationForm).where(models.RegistrationForm.tournament_id == self.tournament_id)
            )
            await s.commit()
        [result] = await self.tick(reg)
        self.assertEqual(("skipped", "registration_form_missing"), (result["status"], result["reason"]))
        self.assertEqual("draft", await self.node_status(reg))


class SetScheduleTests(FlowCase):
    async def test_set_schedule_rejects_phase_of_another_kind(self) -> None:
        reg = await self.node("registration")
        async with self.Session() as s:
            with self.assertRaises(ApiHTTPException) as caught:
                await flow_node_schedule_service.set_schedule(
                    s, reg, [FlowNodeScheduleEntry(phase="start", starts_at=_NOW)]
                )
        self.assertEqual(422, caught.exception.status_code)
        self.assertEqual("invalid_schedule_phase", caught.exception.detail[0]["code"])


class ArchiveTests(FlowCase):
    async def set_status(self, status: enums.TournamentStatus) -> None:
        async with self.Session() as s:
            await s.execute(
                sa.update(models.Tournament).where(models.Tournament.id == self.tournament_id).values(status=status)
            )
            await s.commit()

    async def test_archive_needs_completed_and_unarchive_returns_completed(self) -> None:
        await self.set_status(enums.TournamentStatus.LIVE)
        async with self.Session() as s:
            with self.assertRaises(ApiHTTPException) as caught:
                await tournament_service.set_archived(s, self.tournament_id, True)
        self.assertEqual(
            (409, "tournament_not_completed"), (caught.exception.status_code, caught.exception.detail[0]["code"])
        )
        await self.set_status(enums.TournamentStatus.COMPLETED)
        async with self.Session() as s:
            archived = await tournament_service.set_archived(s, self.tournament_id, True)
        self.assertEqual(enums.TournamentStatus.ARCHIVED, archived.status)
        self.assertEqual(enums.TournamentStatus.ARCHIVED, await self.tournament_status())
        async with self.Session() as s:
            restored = await tournament_service.set_archived(s, self.tournament_id, False)
        self.assertEqual(enums.TournamentStatus.COMPLETED, restored.status)
