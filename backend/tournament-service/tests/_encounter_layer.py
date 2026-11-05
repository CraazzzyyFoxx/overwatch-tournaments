"""Seeds for the suites that need real encounter rows on the test Postgres.

Not a ``test_*`` module. An encounter is a row, its seats in ``encounter.team``,
its bracket coordinate in ``tournament.bracket_encounter``, and a decided result
a write through the result writer -- the constraints between them
(``ck_encounter_confirmed_completed``, the one-active-seat index) are why these
suites run against the database and not a stub.
"""

from __future__ import annotations

import asyncio
import itertools
import os
import sys
from collections.abc import Sequence
from unittest import IsolatedAsyncioTestCase

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared.core import enums
from shared.core.enums import FlowNodeStatus
from shared.models.encounter import Encounter, ScoringRule
from shared.models.tenancy.workspace import Workspace
from shared.models.tournament.bracket_encounter import BracketEncounter
from shared.models.tournament.flow import FlowNode
from shared.models.tournament.stage import Stage, StageItem
from shared.models.tournament.team import Team
from shared.models.tournament.tournament import Tournament
from shared.services.encounter.participants import active_teams, place_team
from shared.services.encounter.result import apply_result
from shared.testing import create_test_async_engine
from shared.testing.db import ensure_test_postgres
from src.services.flow.lifecycle import flow_node_service

__all__ = ("EncounterLayerCase", "add_encounter", "add_scoring_rule", "add_stage_node", "move_stage")

_TAG = itertools.count()


async def add_scoring_rule(session, workspace_id: int) -> ScoringRule:
    """The ``wins`` preset, as ``enclayer01`` writes it into every row."""
    rule = ScoringRule(
        workspace_id=workspace_id,
        preset="wins",
        game_formula="win",
        end_formula="games >= best_of or max_wins * 2 > best_of",
    )
    session.add(rule)
    await session.flush()
    return rule


def add_stage_node(session, stage: Stage, status: str = "draft") -> FlowNode:
    """The node every stage read carries (``Stage.node_id`` / ``status``); a stage built as a bare row has none."""
    node = FlowNode(tournament_id=stage.tournament_id, kind="stage", name=stage.name, status=status, stage_id=stage.id)
    session.add(node)
    return node


async def move_stage(session_maker, stage_id: int, *targets: FlowNodeStatus) -> None:
    """Move the stage's node through ``targets`` (e.g. ``READY, LIVE``) the way an admin does, and commit."""
    async with session_maker() as s:
        node_id = await s.scalar(sa.select(FlowNode.id).where(FlowNode.stage_id == stage_id))
        for target in targets:
            await flow_node_service.transition(s, node_id, target, actor=None)
        await s.commit()


async def add_encounter(
    session,
    tournament: Tournament,
    scoring_rule_id: int,
    *,
    teams: Sequence[int | None],
    scores: Sequence[float] | None = None,
    stage_id: int | None = None,
    stage_item_id: int | None = None,
    round_number: int = 1,
    name: str | None = None,
    **columns,
) -> Encounter:
    """One encounter seating ``teams`` in slots ``1..n`` (``None`` leaves a seat empty).

    ``scores`` (one per team) confirms an admin result: the highest score takes
    first place and equal scores share a place, like a drawn duel.
    """
    encounter = Encounter(
        workspace_id=tournament.workspace_id,
        discipline=tournament.discipline,
        tournament_id=tournament.id,
        scoring_rule_id=scoring_rule_id,
        name=name or "E",
        slot_count=len(teams),
        **columns,
    )
    session.add(encounter)
    await session.flush()
    if stage_id is not None:
        session.add(
            BracketEncounter(
                encounter_id=encounter.id,
                tournament_id=tournament.id,
                stage_id=stage_id,
                stage_item_id=stage_item_id,
                round=round_number,
            )
        )
    for slot, team_id in enumerate(teams, 1):
        if team_id is None:
            continue
        team = await session.get_one(Team, team_id)
        await place_team(session, encounter, slot=slot, team_id=team_id, name=team.name, seed=None, members=())
    if scores is not None:
        seats = {seat.slot: seat for seat in await active_teams(session, encounter.id)}
        ranked = sorted(set(scores), reverse=True)
        await apply_result(
            session,
            encounter,
            source=enums.EncounterResultSource.ADMIN,
            totals={seats[slot].id: float(score) for slot, score in enumerate(scores, 1)},
            placements={seats[slot].id: ranked.index(score) + 1 for slot, score in enumerate(scores, 1)},
            action=enums.EncounterResultAuditAction.CONFIRM,
            audit_source="admin",
            actor_user_id=None,
            reason="test",
        )
    await session.flush()
    return encounter


class EncounterLayerCase(IsolatedAsyncioTestCase):
    """A workspace with one stage, one item and four teams named ``t0``..``t3``."""

    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop  # psycopg/asyncpg cannot run on the Proactor loop

    async def asyncSetUp(self) -> None:
        ensure_test_postgres()
        self.engine = create_test_async_engine()
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        tag = f"encl-{os.getpid()}-{next(_TAG)}"
        async with self.Session() as s:
            workspace = Workspace(slug=tag, name=tag)
            s.add(workspace)
            await s.flush()
            self.workspace_id = workspace.id
            tournament = Tournament(workspace_id=workspace.id, name=tag, slug=tag, status=enums.TournamentStatus.LIVE)
            s.add(tournament)
            await s.flush()
            self.tournament_id = tournament.id
            rule = await add_scoring_rule(s, workspace.id)
            stage = Stage(
                tournament_id=tournament.id,
                scoring_rule_id=rule.id,
                name="Playoff",
                stage_type=enums.StageType.SINGLE_ELIMINATION,
                order=1,
            )
            s.add(stage)
            await s.flush()
            add_stage_node(s, stage)
            item = StageItem(stage_id=stage.id, name="A", type=enums.StageItemType.SINGLE_BRACKET, order=0)
            s.add(item)
            teams = [Team(tournament_id=tournament.id, name=f"t{i}", balancer_name=f"{tag}-{i}") for i in range(4)]
            s.add_all(teams)
            await s.flush()
            self.rule_id, self.stage_id, self.item_id = rule.id, stage.id, item.id
            self.teams = [team.id for team in teams]
            await s.commit()

    async def asyncTearDown(self) -> None:
        async with self.Session() as s:
            await s.execute(sa.delete(Workspace).where(Workspace.id == self.workspace_id))
            await s.commit()
        await self.engine.dispose()

    async def encounter(
        self, *teams: int | None, stage_id: int | None = None, item_id: int | None = None, **columns
    ) -> int:
        async with self.Session() as s:
            tournament = await s.get_one(Tournament, self.tournament_id)
            encounter = await add_encounter(
                s,
                tournament,
                self.rule_id,
                teams=[None if index is None else self.teams[index] for index in teams],
                stage_id=self.stage_id if stage_id is None else stage_id,
                stage_item_id=self.item_id if item_id is None else item_id,
                **columns,
            )
            await s.commit()
            return encounter.id

    async def seats(self, encounter_id: int) -> list[tuple[int, str]]:
        """``(slot, name)`` of the live seats."""
        async with self.Session() as s:
            return [(seat.slot, seat.name) for seat in await active_teams(s, encounter_id)]
