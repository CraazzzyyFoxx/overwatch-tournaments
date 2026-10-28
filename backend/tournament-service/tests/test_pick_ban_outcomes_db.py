"""``GET /tournaments/{id}/pick-ban/outcomes`` against the real Postgres: through the RPC handler, gate included.

The hero room's log is seeded directly (the room's own writes are covered by ``test_pregame_participations``): what
the read must get right is which submissions an anonymous spectator may see, which steps are bans, and which round
they play.
"""

from __future__ import annotations

import asyncio
import itertools
import os
import sys
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared.core import enums
from shared.models.encounter import Encounter, ScoringRule
from shared.models.encounter.pick_ban import PickBanEntry, PickBanSession, PickBanSubmission
from shared.models.tenancy.workspace import Workspace
from shared.models.tournament.team import Team
from shared.models.tournament.tournament import Tournament
from shared.services.encounter.participants import place_team
from shared.testing import create_test_async_engine
from shared.testing.db import ensure_test_postgres
from src.rpc import _helpers, reads
from tests._rpc_fakes import CapturingBroker

_TAG = itertools.count()
SUBJECT = "rpc.tournament.pick_ban_outcomes"
REVEALED, LOCKED, DRAFT, PICKED_HERO, VOIDED_HERO = 101, 102, 103, 104, 105


def _step(index: int, round: int | None, action: str, *, blind: bool, actor: int) -> dict:
    """One ``resolved_sequence_json`` row, every inherited value filled in as the compiler writes it."""
    return {
        "index": index,
        "round": round,
        "phase_id": "main",
        "step_id": f"s{index}",
        "action": action,
        "actors": [actor],
        "count": 1,
        "min": 1,
        "blind": blind,
        "target": None,
        "lifetime": 1,
        "timer_seconds": None,
        "on_timeout": "wait",
        "dispute": {"enabled": False, "max": 0},
        "eligible": {},
        "constraints": [],
    }


class PickBanOutcomesTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    async def asyncSetUp(self) -> None:
        ensure_test_postgres()
        self.engine = create_test_async_engine()
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        tag = f"pbo-{os.getpid()}-{next(_TAG)}"
        async with self.Session() as s:
            await s.execute(
                sa.text(
                    "INSERT INTO catalog.discipline (code, name) VALUES ('overwatch', 'overwatch') ON CONFLICT DO NOTHING"
                )
            )
            workspace = Workspace(slug=tag, name=tag)
            s.add(workspace)
            await s.flush()
            self.workspace_id = workspace.id
            tournament = Tournament(
                workspace_id=workspace.id,
                discipline="overwatch",
                name=tag,
                slug=tag,
                status=enums.TournamentStatus.LIVE,
                is_hidden=False,
            )
            rule = ScoringRule(
                workspace_id=workspace.id,
                preset="wins",
                columns=[],
                game_formula="win",
                end_formula="games >= best_of or max_wins * 2 > best_of",
            )
            s.add_all([tournament, rule])
            await s.flush()
            self.tournament_id = tournament.id
            teams = [Team(tournament_id=tournament.id, name=f"T{i}", balancer_name=f"T{i}") for i in (1, 2)]
            s.add_all(teams)
            await s.flush()
            encounter = Encounter(
                workspace_id=workspace.id,
                discipline="overwatch",
                tournament_id=tournament.id,
                scoring_rule_id=rule.id,
                name="E",
                slot_count=2,
                best_of=3,
                status=enums.EncounterStatus.OPEN,
            )
            s.add(encounter)
            await s.flush()
            self.encounter_id = encounter.id
            home, away = [
                (await place_team(s, encounter, slot=slot, team_id=team.id, name=team.name, seed=slot, members=())).id
                for slot, team in enumerate(teams, start=1)
            ]

            def room(kind: enums.PickBanKind, steps: list[dict]) -> PickBanSession:
                return PickBanSession(
                    encounter_id=encounter.id,
                    kind=kind,
                    pool_json={},
                    first_team_id=home,
                    seed_source=enums.VetoSeedSource.ADMIN,
                    resolved_sequence_json=steps,
                    ruleset_json={},
                )

            hero = room(
                enums.PickBanKind.HERO,
                [
                    _step(0, 1, "ban", blind=True, actor=home),
                    _step(1, 1, "ban", blind=True, actor=away),
                    _step(2, 2, "ban", blind=False, actor=home),
                    _step(3, 2, "pick", blind=False, actor=away),
                ],
            )
            maps = room(enums.PickBanKind.MAP, [])
            s.add_all([hero, maps])
            await s.flush()

            def submission(step: int, team: int, state: str, item: int, *, attempt: int = 1, target=None):
                return PickBanSubmission(
                    session_id=hero.id,
                    encounter_id=encounter.id,
                    step_index=step,
                    encounter_team_id=team,
                    attempt=attempt,
                    state=state,
                    items_json=[{"item_id": item, "target_player_id": target}],
                )

            s.add_all(
                [
                    # A disputed first attempt, voided: only the second one counts.
                    submission(0, home, "voided", VOIDED_HERO),
                    submission(0, home, "revealed", REVEALED, attempt=2),
                    # The opponent's blind ban, locked but not revealed yet: nobody else may see it.
                    submission(1, away, "locked", LOCKED),
                    # An open step's draft is public as it is typed, a per-player ban names its target.
                    submission(2, home, "draft", DRAFT, target=77),
                    # A pick is not a ban.
                    submission(3, away, "revealed", PICKED_HERO),
                ]
            )
            s.add_all(
                [
                    PickBanEntry(session_id=maps.id, encounter_id=encounter.id, item_id=map_id, status=status)
                    for map_id, status in (
                        (31, enums.MapPoolEntryStatus.BANNED),
                        (32, enums.MapPoolEntryStatus.PICKED),
                        (33, enums.MapPoolEntryStatus.AVAILABLE),
                    )
                ]
            )
            await s.commit()

        self.broker = CapturingBroker()
        reads.register(self.broker, SimpleNamespace(exception=lambda *a, **k: None))
        self.enterContext(patch.object(_helpers.db, "async_session_maker", self.Session))

    async def asyncTearDown(self) -> None:
        async with self.Session() as s:
            await s.execute(sa.delete(Workspace).where(Workspace.id == self.workspace_id))
            await s.commit()
        await self.engine.dispose()

    async def test_lists_the_public_hero_bans_and_the_settled_maps(self) -> None:
        envelope = await self.broker.handlers[SUBJECT]({"id": self.tournament_id}, None)

        self.assertTrue(envelope["ok"], envelope)
        encounter = self.encounter_id
        self.assertEqual(
            {
                "hero_bans": [
                    {"encounter_id": encounter, "hero_id": REVEALED, "first_map": True, "target_player_id": None},
                    {"encounter_id": encounter, "hero_id": DRAFT, "first_map": False, "target_player_id": 77},
                ],
                "map_outcomes": [
                    {"encounter_id": encounter, "map_id": 31, "picked": False},
                    {"encounter_id": encounter, "map_id": 32, "picked": True},
                ],
            },
            envelope["data"],
        )

    async def test_an_unknown_tournament_is_not_found(self) -> None:
        envelope = await self.broker.handlers[SUBJECT]({"id": self.tournament_id + 1_000_000}, None)

        self.assertFalse(envelope["ok"], envelope)
        self.assertEqual("not_found", envelope["error"]["code"])
