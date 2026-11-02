"""Individual Swiss rounds and the personal table against the real Postgres.

The shape is the Overwatch role queue (tank 1 / damage 2 / support 2): 20 single-role registrations (4 / 8 / 8) make
four teams per round, so two encounters. ``win_points`` / ``draw_points`` / ``loss_points`` stay at the tournament
defaults 1 / 0.5 / 0.
"""

from __future__ import annotations

import os
from collections import defaultdict

import sqlalchemy as sa

from shared import models
from shared.core import enums
from shared.core.errors import BaseAPIException
from shared.models.registration.registration import Registration, RegistrationRole
from shared.repository import CatalogRoleRepository
from shared.services.encounter.participants import active_teams
from shared.services.encounter.result import apply_result
from src import schemas
from src.services.admin.stage import stage_service
from src.services.individual_swiss import individual_swiss_rounds_service
from src.services.individual_swiss.qualification import qualification_service
from src.services.standings.service import standings_service
from tests._encounter_layer import EncounterLayerCase

ROLES = {"tank": 4, "damage": 8, "support": 8}


class IndividualSwissRoundsTests(EncounterLayerCase):
    async def _seed_pool(self, counts: dict[str, int]) -> None:
        tag = f"isw-{os.getpid()}-{self.workspace_id}"
        async with self.Session() as s:
            catalog = await CatalogRoleRepository().rated_rows(s, discipline="overwatch", workspace_id=None)
            for role, count in counts.items():
                for index in range(count):
                    user = models.User(name=f"{tag}-{role}-{index}")
                    s.add(user)
                    await s.flush()
                    member = models.WorkspaceMember(workspace_id=self.workspace_id, player_id=user.id)
                    s.add(member)
                    await s.flush()
                    registration = Registration(
                        tournament_id=self.tournament_id,
                        display_name=f"{role}{index}",
                        status="approved",
                        balancer_status="ready",
                        workspace_member_id=member.id,
                    )
                    s.add(registration)
                    await s.flush()
                    s.add(
                        RegistrationRole(
                            registration_id=registration.id,
                            catalog_role=catalog[role],
                            dimension_id=catalog[role].dimension_id,
                            is_primary=True,
                            priority=0,
                            # Distinct inside a role, so the captain and the rank tiebreak are unambiguous.
                            rank_value=2000 + 100 * index,
                            is_active=True,
                        )
                    )
            await s.commit()

    async def _start(self, **fields) -> int:
        async with self.Session() as s:
            stage = await stage_service.create_stage(
                s,
                self.tournament_id,
                schemas.StageCreate(
                    name="Swiss",
                    stage_type=enums.StageType.INDIVIDUAL_SWISS,
                    order=5,
                    max_rounds=2,
                    playoff_team_count=2,
                    **fields,
                ),
            )
            stage_id = stage.id
        async with self.Session() as s:
            await stage_service.activate_and_generate(
                s, stage_id, force=True, notify=False, commit=True, schedule_standings=False
            )
        return stage_id

    async def _round(self, stage_id: int, number: int) -> list[int]:
        async with self.Session() as s:
            return list(
                await s.scalars(
                    sa.select(models.BracketEncounter.encounter_id)
                    .where(models.BracketEncounter.stage_id == stage_id, models.BracketEncounter.round == number)
                    .order_by(models.BracketEncounter.encounter_id)
                )
            )

    async def _seats(self, encounter_id: int) -> list[tuple[int | None, str, list[tuple[int, bool]]]]:
        """``(team_id, name, [(member_id, is_captain)])`` per live seat, in slot order."""
        async with self.Session() as s:
            seats = await active_teams(s, encounter_id)
            members = defaultdict(list)
            for seat_id, member_id, is_captain in await s.execute(
                sa.select(
                    models.EncounterTeamMember.encounter_team_id,
                    models.EncounterTeamMember.workspace_member_id,
                    models.EncounterTeamMember.is_captain,
                ).where(models.EncounterTeamMember.encounter_id == encounter_id)
            ):
                members[seat_id].append((member_id, is_captain))
            return [(seat.team_id, seat.name, members[seat.id]) for seat in seats]

    async def _confirm(self, encounter_id: int, first: float, second: float) -> None:
        async with self.Session() as s:
            encounter = await s.get_one(models.Encounter, encounter_id)
            seats = await active_teams(s, encounter_id)
            scores = (first, second)
            await apply_result(
                s,
                encounter,
                source=enums.EncounterResultSource.ADMIN,
                totals={seat.id: scores[index] for index, seat in enumerate(seats)},
                placements={seat.id: 1 if scores[index] == max(scores) else 2 for index, seat in enumerate(seats)},
                action=enums.EncounterResultAuditAction.CONFIRM,
                audit_source="admin",
                actor_user_id=None,
                reason="test",
            )
            await s.commit()

    async def _recalculate_and_generate(self, stage_id: int) -> list[models.Encounter]:
        async with self.Session() as s:
            await standings_service.recalculate_for_tournament(s, self.tournament_id)
        async with self.Session() as s:
            generated = await individual_swiss_rounds_service.generate_ready_rounds(s, self.tournament_id)
            await s.commit()
            return generated

    async def _table(self, stage_id: int) -> dict[int, models.PlayerStanding]:
        async with self.Session() as s:
            rows = await s.scalars(sa.select(models.PlayerStanding).where(models.PlayerStanding.stage_id == stage_id))
            return {row.workspace_member_id: row for row in rows}

    async def test_the_flow_from_start_to_the_last_round(self) -> None:
        await self._seed_pool(ROLES)
        stage_id = await self._start()

        table = await self._table(stage_id)
        self.assertEqual(20, len(table))
        self.assertEqual(
            {"tank": 4, "damage": 8, "support": 8}, {r: sum(x.role == r for x in table.values()) for r in ROLES}
        )

        round_one = await self._round(stage_id, 1)
        self.assertEqual(2, len(round_one))
        seen: set[int] = set()
        for encounter_id in round_one:
            for team_id, name, members in await self._seats(encounter_id):
                self.assertIsNone(team_id)
                self.assertEqual(5, len(members))
                ids = [member_id for member_id, _ in members]
                seen.update(ids)
                self.assertEqual(
                    ["tank", "damage", "damage", "support", "support"],
                    sorted((table[i].role for i in ids), key=["tank", "damage", "support"].index),
                )
                captains = [member_id for member_id, is_captain in members if is_captain]
                self.assertEqual([max(ids, key=lambda i: (table[i].rank, -i))], captains)
                self.assertEqual(f"Команда {table[captains[0]].display_name}", name)
        self.assertEqual(set(table), seen)

        # 2:0 and 2:1 for the first seats.
        await self._confirm(round_one[0], 2, 0)
        await self._confirm(round_one[1], 2, 1)
        winners = {m for e in round_one for m, _ in (await self._seats(e))[0][2]}
        generated = await self._recalculate_and_generate(stage_id)

        table = await self._table(stage_id)
        diffs = {round_one[0]: 2, round_one[1]: 1}
        for encounter_id in round_one:
            for index, (_, _, members) in enumerate(await self._seats(encounter_id)):
                for member_id, _ in members:
                    row = table[member_id]
                    won = index == 0
                    self.assertEqual(
                        (1.0 if won else 0.0, int(won), int(not won), 1),
                        (row.points, row.wins, row.losses, row.matches_played),
                    )
                    self.assertEqual(diffs[encounter_id] if won else -diffs[encounter_id], row.maps_won - row.maps_lost)
                    # The opponents' mean final points: the winners met losers (0), the losers met winners (1).
                    self.assertEqual(0.0 if won else 1.0, row.buchholz)
        for role in ROLES:
            places = sorted(r.position for r in table.values() if r.role == role)
            self.assertEqual(list(range(1, ROLES[role] + 1)), places)
        # K = 2 teams of the 4: the top 2 tanks, 4 damage, 4 support, and two captains among them.
        self.assertEqual(10, sum(r.is_qualified for r in table.values()))
        self.assertEqual(2, sum(r.is_captain for r in table.values()))
        self.assertTrue(all(r.is_qualified for r in table.values() if r.is_captain))

        # Round 2 exists once; the score lobbies put both winning teams together.
        self.assertEqual(2, len(generated))
        round_two = await self._round(stage_id, 2)
        self.assertEqual(2, len(round_two))
        lobby_one = {m for _, _, members in await self._seats(round_two[0]) for m, _ in members}
        self.assertEqual(winners, lobby_one)
        self.assertEqual([], await self._recalculate_and_generate(stage_id))
        self.assertEqual(2, len(await self._round(stage_id, 2)))

        # A correction of round 1 moves the points, re-pairs nothing and creates no round.
        await self._confirm(round_one[0], 0, 2)
        self.assertEqual([], await self._recalculate_and_generate(stage_id))
        corrected = await self._table(stage_id)
        first_seat, second_seat = [{m for m, _ in members} for _, _, members in await self._seats(round_one[0])]
        self.assertEqual({0.0}, {corrected[m].points for m in first_seat})
        self.assertEqual({1.0}, {corrected[m].points for m in second_seat})
        self.assertEqual(round_two, await self._round(stage_id, 2))
        self.assertEqual([], await self._round(stage_id, 3))

        # Round 2 closes: the stage is completed and there is no round 3.
        await self._confirm(round_two[0], 2, 0)
        await self._confirm(round_two[1], 2, 0)
        self.assertEqual([], await self._recalculate_and_generate(stage_id))
        async with self.Session() as s:
            self.assertTrue((await s.get_one(models.Stage, stage_id)).is_completed)
        self.assertEqual([], await self._round(stage_id, 3))
        final = await self._table(stage_id)
        self.assertEqual({2}, {row.matches_played for row in final.values()})
        self.assertEqual(20.0, sum(row.points for row in final.values()))

    async def test_a_pool_that_does_not_split_into_teams_is_refused_without_writes(self) -> None:
        await self._seed_pool({"tank": 4, "damage": 8, "support": 7})
        with self.assertRaises(BaseAPIException) as raised:
            await self._start()
        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("role_count_mismatch", raised.exception.detail["code"])
        async with self.Session() as s:
            self.assertEqual(
                0,
                await s.scalar(
                    sa.select(sa.func.count())
                    .select_from(models.PlayerStanding)
                    .where(models.PlayerStanding.tournament_id == self.tournament_id)
                ),
            )
            self.assertEqual(
                0,
                await s.scalar(
                    sa.select(sa.func.count())
                    .select_from(models.Encounter)
                    .where(models.Encounter.tournament_id == self.tournament_id)
                ),
            )

    async def test_a_playoff_larger_than_a_round_is_refused(self) -> None:
        await self._seed_pool(ROLES)
        async with self.Session() as s:
            stage = await stage_service.create_stage(
                s,
                self.tournament_id,
                schemas.StageCreate(
                    name="Swiss", stage_type=enums.StageType.INDIVIDUAL_SWISS, order=5, playoff_team_count=5
                ),
            )
            stage_id = stage.id
        async with self.Session() as s:
            with self.assertRaises(BaseAPIException) as raised:
                await stage_service.activate_and_generate(
                    s, stage_id, force=True, notify=False, commit=True, schedule_standings=False
                )
        self.assertEqual("playoff_too_large", raised.exception.detail["code"])

    async def test_balance_mode_splits_the_whole_pool_into_four_teams(self) -> None:
        await self._seed_pool(ROLES)
        stage_id = await self._start(pairing_mode=enums.StagePairingMode.BALANCE)
        round_one = await self._round(stage_id, 1)
        self.assertEqual(2, len(round_one))
        table = await self._table(stage_id)
        members: list[int] = []
        for encounter_id in round_one:
            for team_id, _, seat_members in await self._seats(encounter_id):
                self.assertIsNone(team_id)
                ids = [member_id for member_id, _ in seat_members]
                members.extend(ids)
                self.assertEqual(
                    {"tank": 1, "damage": 2, "support": 2},
                    {r: sum(table[i].role == r for i in ids) for r in ROLES},
                )
        self.assertEqual(set(table), set(members))
        self.assertEqual(20, len(members))

    async def test_a_started_stage_starts_again_only_when_its_matches_are_gone(self) -> None:
        await self._seed_pool(ROLES)
        stage_id = await self._start()
        first_round = await self._round(stage_id, 1)
        self.assertEqual(2, len(first_round))

        async with self.Session() as s:
            with self.assertRaises(BaseAPIException) as refused:
                await stage_service.activate_and_generate(
                    s, stage_id, force=True, notify=False, commit=True, schedule_standings=False
                )
        self.assertEqual(409, refused.exception.status_code)
        self.assertEqual(first_round, await self._round(stage_id, 1))

        # "Regenerate" with the matches deleted: the pool is frozen again instead of tripping the unique index.
        async with self.Session() as s:
            await s.execute(sa.delete(models.Encounter).where(models.Encounter.id.in_(first_round)))
            await s.commit()
        async with self.Session() as s:
            await stage_service.activate_and_generate(
                s, stage_id, force=True, notify=False, commit=True, schedule_standings=False
            )
        self.assertEqual(20, len(await self._table(stage_id)))
        self.assertEqual(2, len(await self._round(stage_id, 1)))
        self.assertEqual([], await self._round(stage_id, 2))

    async def _lock(self, stage_id: int):
        async with self.Session() as s:
            stage = await s.get_one(models.Stage, stage_id)
            return await qualification_service.lock(s, stage)

    async def _set_playoff_teams(self, stage_id: int, count: int) -> None:
        async with self.Session() as s:
            await stage_service.update_stage(s, stage_id, schemas.StageUpdate(playoff_team_count=count))
        async with self.Session() as s:
            await standings_service.recalculate_for_tournament(s, self.tournament_id)

    async def _play_both_rounds(self, stage_id: int) -> list[int]:
        round_one = await self._round(stage_id, 1)
        await self._confirm(round_one[0], 2, 0)
        await self._confirm(round_one[1], 2, 1)
        await self._recalculate_and_generate(stage_id)
        round_two = await self._round(stage_id, 2)
        await self._confirm(round_two[0], 2, 0)
        await self._confirm(round_two[1], 2, 0)
        await self._recalculate_and_generate(stage_id)
        return round_two

    async def test_the_playoff_team_count_moves_the_cut_until_the_qualification_is_locked(self) -> None:
        await self._seed_pool(ROLES)
        stage_id = await self._start()
        round_two = await self._play_both_rounds(stage_id)
        table = await self._table(stage_id)
        self.assertEqual(
            (10, 2), (sum(r.is_qualified for r in table.values()), sum(r.is_captain for r in table.values()))
        )

        # K 2 -> 1: the cut is one team's worth per role (1 tank, 2 damage, 2 support) and one captain.
        await self._set_playoff_teams(stage_id, 1)
        table = await self._table(stage_id)
        self.assertEqual(
            {"tank": 1, "damage": 2, "support": 2},
            {role: sum(r.is_qualified for r in table.values() if r.role == role) for role in ROLES},
        )
        self.assertEqual(1, sum(r.is_captain for r in table.values()))

        # More teams than a round has is refused, and nothing changes.
        async with self.Session() as s:
            with self.assertRaises(BaseAPIException) as too_many:
                await stage_service.update_stage(s, stage_id, schemas.StageUpdate(playoff_team_count=5))
        self.assertEqual(409, too_many.exception.status_code)
        async with self.Session() as s:
            self.assertEqual(1, (await s.get_one(models.Stage, stage_id)).playoff_team_count)

        locked = await self._lock(stage_id)
        frozen = {member: (row.is_qualified, row.is_captain) for member, row in (await self._table(stage_id)).items()}
        self.assertEqual(5, len(locked.qualified))
        self.assertEqual(1, len(locked.captains))
        self.assertEqual(5, sum(qualified for qualified, _ in frozen.values()))

        # A result corrected after the lock moves the points, not who is a qualifier or a captain.
        before = await self._table(stage_id)
        await self._confirm(round_two[0], 0, 2)
        await self._confirm(round_two[1], 0, 2)
        async with self.Session() as s:
            await standings_service.recalculate_for_tournament(s, self.tournament_id)
        after = await self._table(stage_id)
        self.assertNotEqual({m: r.points for m, r in before.items()}, {m: r.points for m, r in after.items()})
        self.assertEqual(frozen, {m: (r.is_qualified, r.is_captain) for m, r in after.items()})

        # Frozen: the team count, a second lock and a restart are all refused.
        async with self.Session() as s:
            with self.assertRaises(BaseAPIException) as locked_count:
                await stage_service.update_stage(s, stage_id, schemas.StageUpdate(playoff_team_count=2))
        self.assertEqual(409, locked_count.exception.status_code)
        with self.assertRaises(BaseAPIException) as twice:
            await self._lock(stage_id)
        self.assertEqual(409, twice.exception.status_code)
