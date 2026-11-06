"""A Challonge import completes the formation node once the tournament has teams, so its first stage can go ready."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import sqlalchemy as sa

from shared import models
from shared.core.enums import FlowNodeStatus as S
from shared.core.enums import StageItemType, StageType
from shared.schemas.challonge import ChallongeMatch
from src.services.challonge import sync as challonge_sync
from src.services.challonge.sync import locking as sync_locking
from src.services.flow.lifecycle import flow_node_service
from tests._flow_case import FlowCase
from tests.test_challonge_sync_hardening import _Redis


class _ImportCase(FlowCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.registration = await self.node("registration", config={"check_in": False, "intake": "team"})
        self.formation = await self.node("formation", config={"mode": "balancer"})
        await self.edge(self.registration, "participants", self.formation, "players")
        stage_id, self.stage_node = await self.stage()
        async with self.Session() as s:
            s.add(models.StageItem(stage_id=stage_id, name="A", type=StageItemType.GROUP, order=0))
            source = models.ChallongeSource(tournament_id=self.tournament_id, challonge_tournament_id=5)
            s.add(source)
            await s.commit()
            self.source_id = source.id
        self.redis = _Redis()

    async def add_teams(self, *, mapped: bool = True, formation_node_id: int | None = None) -> list[int]:
        async with self.Session() as s:
            teams = [
                models.Team(
                    tournament_id=self.tournament_id,
                    name=f"T{i}",
                    balancer_name=f"T{i}",
                    formation_node_id=formation_node_id,
                )
                for i in range(2)
            ]
            s.add_all(teams)
            await s.flush()
            if mapped:
                s.add_all(
                    models.ChallongeParticipantMapping(
                        source_id=self.source_id, challonge_participant_id=i + 1, team_id=team.id
                    )
                    for i, team in enumerate(teams)
                )
            await s.commit()
            return [team.id for team in teams]

    async def sync(self, matches: list[ChallongeMatch] | None = None) -> None:
        with (
            patch.object(sync_locking, "_get_redis", AsyncMock(return_value=self.redis)),
            patch.object(challonge_sync.challonge_client, "fetch_matches", AsyncMock(return_value=matches or [])),
            patch.object(challonge_sync.challonge_client, "fetch_participants", AsyncMock(return_value=[])),
        ):
            async with self.Session() as s:
                await challonge_sync.sync_service.import_tournament(s, self.tournament_id)


class ImportedFormationTests(_ImportCase):
    async def test_import_completes_the_formation_and_the_first_stage_can_go_ready(self) -> None:
        await self.add_teams()
        await self.sync()
        self.assertEqual("completed", await self.node_status(self.formation))
        async with self.Session() as s:
            formation = await s.get_one(models.FlowNode, self.formation)
            registrations = await s.scalar(
                sa.select(sa.func.count()).where(
                    models.FlowNode.tournament_id == self.tournament_id, models.FlowNode.kind == "registration"
                )
            )
        self.assertEqual("manual", formation.config["mode"])
        self.assertEqual(0, registrations, "an import has no registration to wait for")
        async with self.Session() as s:
            await flow_node_service.transition(s, self.stage_node, S.READY, actor=self.actor)
            await s.commit()
        self.assertEqual("ready", await self.node_status(self.stage_node))

    async def test_a_resync_leaves_a_completed_formation_alone(self) -> None:
        await self.add_teams()
        await self.sync()
        await self.sync()
        self.assertEqual("completed", await self.node_status(self.formation))

    async def test_a_tournament_without_teams_keeps_its_formation(self) -> None:
        await self.sync()
        self.assertEqual("draft", await self.node_status(self.formation))
        self.assertEqual("draft", await self.node_status(self.registration))

    async def test_an_open_registration_keeps_the_formation_waiting(self) -> None:
        await self.add_teams()
        async with self.Session() as s:
            await s.execute(
                sa.update(models.FlowNode).where(models.FlowNode.id == self.registration).values(status="open")
            )
            await s.commit()
        await self.sync()
        self.assertEqual(
            ("open", "draft"), (await self.node_status(self.registration), await self.node_status(self.formation))
        )

    async def test_teams_the_organizer_made_do_not_complete_the_formation(self) -> None:
        await self.add_teams(mapped=False)
        await self.sync()
        self.assertEqual("draft", await self.node_status(self.formation))

    async def test_a_formation_with_teams_of_its_own_is_left_alone(self) -> None:
        await self.add_teams(formation_node_id=self.formation)
        await self.sync()
        self.assertEqual("draft", await self.node_status(self.formation))
        async with self.Session() as s:
            formation = await s.get_one(models.FlowNode, self.formation)
        self.assertEqual("balancer", formation.config["mode"])

    async def test_a_formation_that_left_draft_is_never_changed(self) -> None:
        await self.add_teams()
        async with self.Session() as s:
            await s.execute(
                sa.update(models.FlowNode).where(models.FlowNode.id == self.registration).values(status="closed")
            )
            await flow_node_service.transition(s, self.formation, S.FORMING, actor=self.actor)
            await s.commit()
        await self.sync()
        self.assertEqual("forming", await self.node_status(self.formation))
        async with self.Session() as s:
            formation = await s.get_one(models.FlowNode, self.formation)
        self.assertEqual("balancer", formation.config["mode"])


def _match(match_id: int, state: str) -> ChallongeMatch:
    return ChallongeMatch(
        id=match_id,
        started_at=None,
        created_at=datetime.now(UTC),
        updated_at=None,
        player1_id=1,
        player2_id=2,
        round=1,
        identifier="A",
        state=state,
        scores_csv="2-1" if state == "complete" else "",
        tournament_id=5,
        group_id=None,
    )


class ImportedStageStartTests(_ImportCase):
    async def stage_node_statuses(self) -> list[str]:
        async with self.Session() as s:
            return list(
                await s.scalars(
                    sa.select(models.FlowNode.status)
                    .where(models.FlowNode.tournament_id == self.tournament_id, models.FlowNode.kind == "stage")
                    .order_by(models.FlowNode.id)
                )
            )

    async def test_underway_matches_move_the_stage_node_to_live(self) -> None:
        await self.add_teams()
        await self.sync([_match(1, "open")])
        self.assertEqual("completed", await self.node_status(self.formation))
        self.assertIn("live", await self.stage_node_statuses())
        self.assertEqual("live", (await self.tournament_status()).value)

    async def test_a_pending_bracket_stays_draft(self) -> None:
        await self.add_teams()
        await self.sync([_match(1, "pending")])
        self.assertNotIn("live", await self.stage_node_statuses())
        self.assertNotIn("ready", await self.stage_node_statuses())

    async def test_a_stage_whose_input_is_not_final_is_skipped(self) -> None:
        # The formation has teams of its own, so the import leaves it ``draft``; the playoff stage hangs off it.
        _, playoff_node = await self.stage(StageType.SINGLE_ELIMINATION, order=2, name="P")
        await self.edge(self.formation, "teams", playoff_node, "participants")
        await self.add_teams(formation_node_id=self.formation)
        await self.sync([_match(1, "open")])
        async with self.Session() as s:
            mapped = await s.scalar(sa.select(sa.func.count()).select_from(models.ChallongeMatchMapping))
        self.assertEqual(1, mapped)
        self.assertEqual("draft", await self.node_status(playoff_node))


class AutoSyncCandidatesTests(_ImportCase):
    async def candidates(self) -> list[int]:
        async with self.Session() as s:
            return await challonge_sync.sync_service.list_active_challonge_tournament_ids(s)

    async def test_an_announced_linked_tournament_is_a_candidate_without_a_live_stage(self) -> None:
        self.assertEqual("announcement", (await self.tournament_status()).value)
        self.assertIn(self.tournament_id, await self.candidates())

    async def test_a_finished_or_archived_tournament_is_not(self) -> None:
        for status in ("completed", "archived"):
            async with self.Session() as s:
                await s.execute(
                    sa.update(models.Tournament).where(models.Tournament.id == self.tournament_id).values(status=status)
                )
                await s.commit()
            self.assertNotIn(self.tournament_id, await self.candidates())

    async def test_a_tournament_without_a_challonge_source_is_not(self) -> None:
        async with self.Session() as s:
            await s.execute(sa.delete(models.ChallongeSource).where(models.ChallongeSource.id == self.source_id))
            await s.commit()
        self.assertNotIn(self.tournament_id, await self.candidates())
