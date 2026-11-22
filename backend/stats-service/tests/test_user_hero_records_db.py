"""The characters read's per-hero record, all-players win rate and career-best game, on real PostgreSQL.

One rolled-back transaction. A dedicated tank character (so the all-players win rate counts only these games); a on
slot 1 and b on slot 2 of one duel, four maps on it:

- 2-1: a wins, b loses
- 1-1: a draw for both — a game, never a win
- 0-1: a loses, b wins
- 3-0: a wins; b was on the hero for 30 s, which is not a game

a: 4 games, 2-1-1; b: 3 games, 1-1-1; everyone: 3 wins in 7 games.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from unittest import IsolatedAsyncioTestCase

import sqlalchemy as sa
from cashews import cache
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums, pagination
from shared.testing import create_test_async_engine, ensure_test_postgres
from src.services.user.service import UserService
from tests.encounter_seed import add_observed_game, seed_encounter, seed_scoring_rule

OW = "overwatch"
users = UserService.of(OW)


class UserHeroRecordsTest(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop  # psycopg async cannot run on the Proactor loop

    async def asyncSetUp(self) -> None:
        ensure_test_postgres()
        self.engine = create_test_async_engine()
        self.connection = await self.engine.connect()
        self.transaction = await self.connection.begin()
        self.session = AsyncSession(self.connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
        # The baseline is process-cached; another test may have cached it without this transaction's games.
        await cache.delete_match("backend:hero_win_rates_all:*")

    async def asyncTearDown(self) -> None:
        await self.session.close()
        await self.transaction.rollback()
        await self.connection.close()
        await self.engine.dispose()

    async def _entity(self, kind: str, tag: str, image_path: str | None = "", **columns: object) -> int:
        statement = sa.insert(models.CatalogEntity).values(
            discipline=OW, kind=kind, name=f"{kind} {tag}", slug=f"{kind}-{tag}", image_path=image_path, **columns
        )
        return (await self.session.execute(statement.returning(models.CatalogEntity.id))).scalar_one()

    async def test_record_win_loss_draw_and_all_players_win_rate(self) -> None:
        tag = uuid.uuid4().hex[:10]
        hero_id = await self._entity("character", tag, attrs={"class": "tank"})
        # A map with no picture: its best games still read, with a null image.
        map_id = await self._entity("map", tag, image_path=None, parent_id=await self._entity("mode", tag))

        workspace = models.Workspace(slug=f"hero-{tag}", name=f"hero-{tag}")
        self.session.add(workspace)
        await self.session.flush()
        members: dict[str, models.WorkspaceMember] = {}
        for key in ("a", "b"):
            user = models.User(name=f"zz{tag}-{key}")
            self.session.add(user)
            await self.session.flush()
            members[key] = models.WorkspaceMember(workspace_id=workspace.id, player_id=user.id)
            self.session.add(members[key])
        tournament = models.Tournament(
            workspace_id=workspace.id, discipline=OW, name=f"T {tag}", slug=f"t-{tag}", is_finished=True
        )
        self.session.add(tournament)
        await self.session.flush()
        rule_id = await seed_scoring_rule(self.session, workspace.id)
        encounter = await seed_encounter(self.session, tournament, rule_id, [(None, 3), (None, 1)], name=f"E {tag}")

        a, b = members["a"].id, members["b"].id
        for position, scores, blocked, b_seconds in (
            (1, (2, 1), 1000, 600),
            (2, (1, 1), 5000, 600),
            (3, (0, 1), 2000, 600),
            (4, (3, 0), 3000, 30),
        ):
            observations = [
                (a, 1, hero_id, enums.LogStatsName.HeroTimePlayed, 600),
                (a, 1, hero_id, enums.LogStatsName.DamageBlocked, blocked),
                (b, 2, hero_id, enums.LogStatsName.HeroTimePlayed, b_seconds),
            ]
            await self.session.run_sync(
                lambda sync, position=position, scores=scores, observations=observations: add_observed_game(
                    sync,
                    encounter_id=encounter.id,
                    map_entity_id=map_id,
                    position=position,
                    duration_s=600,
                    scores=scores,
                    observations=observations,
                )
            )
        await self.session.flush()

        params = pagination.PaginationParams(per_page=10)
        [row_a] = (
            await users.get_heroes(self.session, members["a"].player_id, params, workspace_id=workspace.id)
        ).results
        [row_b] = (await users.get_heroes(self.session, members["b"].player_id, params)).results

        self.assertEqual(row_a.character.id, hero_id)
        self.assertEqual((row_a.games, row_a.win, row_a.loss, row_a.draw), (4, 2, 1, 1))
        self.assertEqual((row_b.games, row_b.win, row_b.loss, row_b.draw), (3, 1, 1, 1))
        self.assertEqual((row_a.win_rate_all, row_b.win_rate_all), (0.4286, 0.4286))

        # A tank is judged by damage blocked: a's best game is the drawn one; b never blocked anything.
        assert row_a.record is not None
        self.assertEqual(
            (row_a.record.stat, row_a.record.value, row_a.record.encounter_id),
            ("damage_blocked", 5000.0, encounter.id),
        )
        self.assertEqual((row_a.record.map_name, row_a.record.tournament_name), (f"map {tag}", f"T {tag}"))
        [blocked] = [stat for stat in row_a.stats if stat.name == enums.LogStatsName.DamageBlocked]
        self.assertEqual((blocked.best.value, blocked.best.map_name), (5000.0, f"map {tag}"))
        self.assertIsNone(blocked.best.map_image_path)
        self.assertIsNone(row_b.record)
