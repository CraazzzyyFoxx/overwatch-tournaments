"""Mix match stats stay inside the mix (D4): the player reads outside it count the tournament game only.

One rolled-back transaction. Player ``a`` played a tournament game (10 eliminations in 600 s on one hero) and a
mix game (100 eliminations, same hero and duration); player ``c`` only the mix game. Every read below would add the
mix game (or list ``c``) if it did not exclude encounters without a tournament.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from unittest import IsolatedAsyncioTestCase

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums, pagination
from shared.disciplines.overwatch.achievements.conditions import stat_threshold
from shared.disciplines.overwatch.achievements.conditions.aggregate import execute_global_stat_sum
from shared.division_grid import DEFAULT_GRID
from shared.domain.achievements.context import EvalContext
from shared.models.encounter import Encounter, EncounterTeam
from shared.testing import create_test_async_engine, ensure_test_postgres
from src.services.hero.queries import HeroQueries
from src.services.user.queries._scope import user_has_logs
from src.services.user.service import UserService
from tests.encounter_seed import add_observed_game, seed_encounter, seed_scoring_rule

OW = "overwatch"
users = UserService.of(OW)
Stat = enums.LogStatsName


class MixStatsIsolationTest(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop  # psycopg async cannot run on the Proactor loop

    async def asyncSetUp(self) -> None:
        ensure_test_postgres()
        self.engine = create_test_async_engine()
        self.connection = await self.engine.connect()
        self.transaction = await self.connection.begin()
        self.session = AsyncSession(self.connection, expire_on_commit=False, join_transaction_mode="create_savepoint")

    async def asyncTearDown(self) -> None:
        await self.session.close()
        await self.transaction.rollback()
        await self.connection.close()
        await self.engine.dispose()

    async def _entity(self, kind: str, tag: str, **columns: object) -> int:
        statement = sa.insert(models.CatalogEntity).values(
            discipline=OW, kind=kind, name=f"{kind} {tag}", slug=f"{kind}-{tag}", image_path="", **columns
        )
        return (await self.session.execute(statement.returning(models.CatalogEntity.id))).scalar_one()

    async def _game(self, encounter: Encounter, hero_id: int, map_id: int, seats: dict[int, int], eliminations: int):
        """One observed game; ``seats`` maps workspace member id to slot."""
        observations = []
        for member, slot in seats.items():
            observations += [
                (member, slot, hero_id, Stat.HeroTimePlayed, 600),
                (member, slot, hero_id, Stat.Eliminations, eliminations),
                (member, slot, None, Stat.HeroTimePlayed, 600),
            ]
        await self.session.run_sync(
            lambda sync: add_observed_game(
                sync,
                encounter_id=encounter.id,
                map_entity_id=map_id,
                position=1,
                duration_s=600,
                scores=(1, 0),
                observations=observations,
            )
        )
        await self.session.flush()

    async def test_reads_outside_the_mix_count_the_tournament_game_only(self) -> None:
        tag = uuid.uuid4().hex[:10]
        hero_id = await self._entity("character", tag, attrs={"class": "tank"})
        map_id = await self._entity("map", tag, parent_id=await self._entity("mode", tag))

        workspace = models.Workspace(slug=f"mixiso-{tag}", name=f"mixiso-{tag}")
        self.session.add(workspace)
        await self.session.flush()
        members: dict[str, models.WorkspaceMember] = {}
        for key in ("a", "c"):
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
        tournament_encounter = await seed_encounter(self.session, tournament, rule_id, [(None, 1), (None, 0)], name=tag)

        mix = models.CustomGame(workspace_id=workspace.id, name=f"Mix {tag}", scoring_rule_id=rule_id)
        self.session.add(mix)
        await self.session.flush()
        mix_encounter = Encounter(
            workspace_id=workspace.id,
            discipline=OW,
            custom_game_id=mix.id,
            scoring_rule_id=rule_id,
            name=f"Mix {tag}",
            slot_count=2,
            best_of=1,
            status=enums.EncounterStatus.OPEN,
        )
        self.session.add(mix_encounter)
        await self.session.flush()
        for slot in (1, 2):
            self.session.add(
                EncounterTeam(encounter_id=mix_encounter.id, slot=slot, team_id=None, name=f"Side {slot}", score=0)
            )
        await self.session.flush()

        a, c = members["a"], members["c"]
        await self._game(tournament_encounter, hero_id, map_id, {a.id: 1}, eliminations=10)
        await self._game(mix_encounter, hero_id, map_id, {a.id: 1, c.id: 2}, eliminations=100)

        session = self.session
        # has_logs / overview chips: ``c`` has parsed stats only inside the mix.
        self.assertTrue(await session.scalar(sa.select(user_has_logs(a.player_id, discipline=OW))))
        self.assertFalse(await session.scalar(sa.select(user_has_logs(c.player_id, discipline=OW))))

        # Overview top heroes: 600 s of the tournament game, not 1200.
        top = await users.overview.get_overview_top_heroes(session, [a.player_id, c.player_id])
        self.assertEqual([(hero.id, seconds) for hero, seconds in top[a.player_id]], [(hero_id, 600)])
        self.assertNotIn(c.player_id, top)

        # Profile hero totals.
        [(_, _, total, *_)] = await users.profile.get_statistics_by_heroes(session, a.player_id, [Stat.Eliminations])
        self.assertEqual(total, 10)
        self.assertEqual(await users.profile.get_statistics_by_heroes(session, c.player_id, [Stat.Eliminations]), [])

        # Compare: playtime and per-10 average of the tournament game alone.
        playtime, values = await users.compare.get_users_hero_compare_stats(
            session,
            user_ids=[a.player_id, c.player_id],
            hero_id=None,
            map_id=None,
            stats=[Stat.Eliminations],
            grid=DEFAULT_GRID,
        )
        self.assertEqual((playtime[a.player_id], playtime[c.player_id]), (600.0, 0.0))
        self.assertEqual(values, {(a.player_id, Stat.Eliminations): 10.0})

        # Draft card / per-map hero reads.
        [(_, games, *_)] = await users.encounters.get_user_hero_records(session, a.player_id)
        self.assertEqual(games, 1)
        self.assertEqual(await users.encounters.get_user_hero_records(session, c.player_id), [])
        [by_map] = await HeroQueries.of(OW).get_user_hero_stats_by_maps(session, [map_id], a.player_id)
        self.assertEqual(by_map.games, 1)

        # Encounter history, observed participations included.
        rows = await users.encounters.get_user_encounter_matches_unpaginated(session, a.player_id)
        self.assertEqual({encounter.id for _team, encounter, *_ in rows}, {tournament_encounter.id})
        self.assertEqual(await users.encounters.get_user_encounter_matches_unpaginated(session, c.player_id), [])
        page, total_count = await users.encounters.get_user_encounters_paginated(
            session, c.player_id, pagination.PaginationSortParams(per_page=50, sort="played_at")
        )
        self.assertEqual((list(page), total_count), ([], 0))

        # Achievements: lifetime sums and per-match thresholds never see the mix game.
        context = EvalContext(workspace_id=workspace.id, discipline=OW)
        lifetime = {"stat": "hero_time_played", "op": ">=", "value": 1000}
        self.assertEqual(await execute_global_stat_sum(session, lifetime, context), set())
        self.assertEqual(await execute_global_stat_sum(session, {**lifetime, "value": 600}, context), {(a.player_id,)})
        threshold = {"stat": "eliminations", "op": ">=", "value": 50}
        self.assertEqual(await stat_threshold.execute(session, threshold, context), set())

        # The global hero view: the mix game feeds neither the average nor the best value (and does not drop the
        # hero's row, which a mix-held best used to do).
        await session.execute(sa.text("REFRESH MATERIALIZED VIEW stats.mv_entity_global_stats"))
        rows = await users.profile.get_statistics_by_heroes_all_values(session, [Stat.Eliminations])
        [(_, _, best, average, _)] = [row for row in rows if row[1] == hero_id]
        self.assertEqual((best, average), (10, 10))
