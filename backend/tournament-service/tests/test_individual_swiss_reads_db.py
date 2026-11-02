"""Individual Swiss reads, pins and the qualification lock against the real test database."""

from __future__ import annotations

import itertools
from uuid import uuid4

import sqlalchemy as sa

from shared import models
from shared.core import enums
from shared.core.errors import BaseAPIException
from shared.models.identity.user import User
from shared.models.tenancy.workspace import WorkspaceMember
from shared.services.encounter.participants import MemberSnapshot, place_team
from src.schemas import individual_swiss as swiss_schemas
from src.services.individual_swiss.pins import pins_service
from src.services.individual_swiss.qualification import qualification_service
from src.services.individual_swiss.reads import reads_service
from tests._encounter_layer import EncounterLayerCase

_N = itertools.count()


class IndividualSwissReadsCase(EncounterLayerCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        async with self.Session() as s:
            stage = models.Stage(
                tournament_id=self.tournament_id,
                scoring_rule_id=self.rule_id,
                name="Swiss day",
                stage_type=enums.StageType.INDIVIDUAL_SWISS,
                order=0,
                max_rounds=2,
                pairing_mode="score",
                playoff_team_count=1,
            )
            s.add(stage)
            await s.flush()
            self.swiss_id = stage.id
            await s.commit()
        self.members: dict[str, int] = {}
        self.user_ids: list[int] = []
        self.tag = uuid4().hex[:8]

    async def player(
        self,
        name: str,
        role: str,
        rank: int,
        *,
        position: int | None = None,
        qualified: bool = False,
        captain: bool = False,
        stage_id: int | None = None,
        registered: bool = True,
        **columns,
    ) -> int:
        """One frozen-pool row (and, by default, an approved registration in the balancer pool); returns the member."""
        async with self.Session() as s:
            user = User(name=f"{name}-{self.tag}-{next(_N)}")
            s.add(user)
            await s.flush()
            self.user_ids.append(user.id)
            member = WorkspaceMember(workspace_id=self.workspace_id, player_id=user.id)
            s.add(member)
            await s.flush()
            registration_id = None
            if registered:
                registration = models.Registration(
                    tournament_id=self.tournament_id,
                    workspace_member_id=member.id,
                    display_name=name,
                    status="approved",
                    balancer_status="ready",
                )
                s.add(registration)
                await s.flush()
                registration_id = registration.id
            s.add(
                models.PlayerStanding(
                    tournament_id=self.tournament_id,
                    stage_id=stage_id or self.swiss_id,
                    registration_id=registration_id,
                    workspace_member_id=member.id,
                    display_name=name,
                    role=role,
                    rank=rank,
                    position=position,
                    is_qualified=qualified,
                    is_captain=captain,
                    **columns,
                )
            )
            await s.commit()
        self.members[name] = member.id
        return member.id

    async def asyncTearDown(self) -> None:
        await super().asyncTearDown()
        async with self.Session() as s:
            await s.execute(sa.delete(User).where(User.id.in_(self.user_ids)))
            await s.commit()

    async def stage(self) -> models.Stage:
        async with self.Session() as s:
            return await s.get_one(models.Stage, self.swiss_id)

    async def complete(self) -> None:
        async with self.Session() as s:
            await s.execute(sa.update(models.Stage).where(models.Stage.id == self.swiss_id).values(is_completed=True))
            await s.commit()

    async def balancer_statuses(self) -> dict[str, tuple[str, str | None]]:
        async with self.Session() as s:
            rows = await s.execute(
                sa.select(
                    models.Registration.display_name,
                    models.Registration.balancer_status,
                    models.Registration.exclude_reason,
                ).where(models.Registration.tournament_id == self.tournament_id)
            )
            return {name: (status, reason) for name, status, reason in rows.all()}


class PlayerStandingsReadTests(IndividualSwissReadsCase):
    async def test_rows_are_ordered_by_role_then_position_with_map_diff(self) -> None:
        # Inserted out of order on purpose; roles come in roster-shape order (tank, damage, support).
        await self.player("sup1", "support", 2500, position=1)
        await self.player("dmg2", "damage", 3000, position=2, maps_won=3, maps_lost=1)
        await self.player("tank1", "tank", 3500, position=1, points=3, maps_won=2.0, maps_lost=0.0)
        await self.player("dmg1", "damage", 3200, position=1, maps_won=4, maps_lost=1)
        await self.player("dmg3", "damage", 2800, position=None)

        async with self.Session() as s:
            rows = await reads_service.player_standings(s, self.tournament_id)

        self.assertEqual(
            ["tank1", "dmg1", "dmg2", "dmg3", "sup1"],
            [row.display_name for row in rows],
        )
        self.assertEqual([2.0, 3.0, 2.0, 0.0, 0.0], [row.map_diff for row in rows])
        self.assertEqual(self.members["tank1"], rows[0].workspace_member_id)
        self.assertEqual(self.swiss_id, rows[0].stage_id)

    async def test_the_cached_read_is_the_same_rows_as_wire_dicts(self) -> None:
        await self.player("tank1", "tank", 3500, position=1)
        async with self.Session() as s:
            wire = await reads_service.get_player_standings(s, self.tournament_id)
        self.assertEqual(["tank1"], [row["display_name"] for row in wire])
        self.assertEqual(self.members["tank1"], wire[0]["workspace_member_id"])
        self.assertEqual(1, wire[0]["position"])


class RoundsReadTests(IndividualSwissReadsCase):
    async def seat(self, session, encounter, slot: int, name: str, people: list[tuple[str, int, bool]], **columns):
        seat = await place_team(
            session,
            encounter,
            slot=slot,
            team_id=None,
            name=f"Команда {name}",
            seed=None,
            members=[
                MemberSnapshot(
                    workspace_member_id=self.members[person],
                    display_name=person,
                    rank=rank,
                    is_substitute=False,
                    roles=(),
                    is_captain=captain,
                )
                for person, rank, captain in people
            ],
        )
        for field, value in columns.items():
            setattr(seat, field, value)

    async def encounter(self, session, round_number: int) -> models.Encounter:
        encounter = models.Encounter(
            workspace_id=self.workspace_id,
            discipline=(await session.get_one(models.Tournament, self.tournament_id)).discipline,
            tournament_id=self.tournament_id,
            scoring_rule_id=self.rule_id,
            name="R",
            slot_count=2,
            best_of=3,
        )
        session.add(encounter)
        await session.flush()
        session.add(
            models.BracketEncounter(
                encounter_id=encounter.id, tournament_id=self.tournament_id, stage_id=self.swiss_id, round=round_number
            )
        )
        return encounter

    async def test_encounters_are_grouped_by_round_with_roster_roles_and_captain(self) -> None:
        for name, role, rank in (
            ("a", "damage", 3000),
            ("b", "tank", 3500),
            ("c", "support", 2500),
            ("d", "tank", 3400),
        ):
            await self.player(name, role, rank)
        async with self.Session() as s:
            first = await self.encounter(s, 1)
            await self.seat(
                s, first, 1, "b", [("a", 3000, False), ("b", 3500, True), ("c", 2500, False)], score=2, placement=1
            )
            await self.seat(s, first, 2, "d", [("d", 3400, True)], score=1, placement=2)
            second = await self.encounter(s, 2)
            await self.seat(s, second, 1, "a", [("a", 3000, True)])
            await self.seat(s, second, 2, "c", [("c", 2500, True)])
            await s.commit()

        async with self.Session() as s:
            rounds = await reads_service.rounds(s, self.tournament_id, self.swiss_id)
            wire = await reads_service.get_rounds(s, self.tournament_id, self.swiss_id)

        self.assertEqual([1, 2], [r.round for r in rounds])
        self.assertEqual([1, 1], [len(r.encounters) for r in rounds])
        encounter = rounds[0].encounters[0]
        self.assertEqual((enums.EncounterStatus.OPEN, 3), (encounter.status, encounter.best_of))
        winner, loser = encounter.seats
        self.assertEqual(("Команда b", 2.0, 1), (winner.name, winner.score, winner.placement))
        # Roster in role order (tank, damage, support), not seating order; exactly one captain.
        self.assertEqual(["b", "a", "c"], [m.display_name for m in winner.members])
        self.assertEqual(["tank", "damage", "support"], [m.role for m in winner.members])
        self.assertEqual([True, False, False], [m.is_captain for m in winner.members])
        self.assertEqual(("Команда d", 2), (loser.name, loser.placement))
        self.assertEqual(rounds[0].encounters[0].encounter_id, wire[0]["encounters"][0]["encounter_id"])

    async def test_a_stage_of_another_kind_or_tournament_is_a_404(self) -> None:
        async with self.Session() as s:
            with self.assertRaises(BaseAPIException) as other_kind:
                await reads_service.rounds(s, self.tournament_id, self.stage_id)
            with self.assertRaises(BaseAPIException) as other_tournament:
                await reads_service.rounds(s, self.tournament_id + 10_000_000, self.swiss_id)
        self.assertEqual(404, other_kind.exception.status_code)
        self.assertEqual(404, other_tournament.exception.status_code)


class PinsTests(IndividualSwissReadsCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        for name, role, rank in (("t1", "tank", 3500), ("t2", "tank", 3400), ("d1", "damage", 3000)):
            await self.player(name, role, rank)

    async def set_pins(self, pins: list[tuple[str, int]]) -> swiss_schemas.PlayerStandingPinsRead:
        data = swiss_schemas.PlayerStandingPinsUpdate(
            pins=[
                swiss_schemas.PlayerStandingPinWrite(workspace_member_id=self.members[n], position=p) for n, p in pins
            ]
        )
        stage = await self.stage()
        async with self.Session() as s:
            return await pins_service.set_pins(s, stage, data, requested_by_user_id=None)

    async def stored(self) -> dict[int, int]:
        async with self.Session() as s:
            return await pins_service.get_pins(s, self.swiss_id)

    async def test_a_position_given_twice_inside_a_role_is_422(self) -> None:
        with self.assertRaises(BaseAPIException) as raised:
            await self.set_pins([("t1", 1), ("t2", 1)])
        self.assertEqual(422, raised.exception.status_code)
        self.assertEqual({}, await self.stored())

    async def test_the_same_position_in_different_roles_is_fine(self) -> None:
        await self.set_pins([("t1", 1), ("d1", 1)])
        self.assertEqual({self.members["t1"]: 1, self.members["d1"]: 1}, await self.stored())

    async def test_a_position_past_the_role_size_is_422(self) -> None:
        with self.assertRaises(BaseAPIException) as raised:
            await self.set_pins([("d1", 2)])
        self.assertEqual(422, raised.exception.status_code)

    async def test_a_player_outside_the_stage_is_422(self) -> None:
        stranger = await self.player("far", "tank", 1000, registered=False, stage_id=await self._other_stage())
        data = swiss_schemas.PlayerStandingPinsUpdate(
            pins=[swiss_schemas.PlayerStandingPinWrite(workspace_member_id=stranger, position=1)]
        )
        async with self.Session() as s:
            with self.assertRaises(BaseAPIException) as raised:
                await pins_service.set_pins(s, await self.stage(), data)
        self.assertEqual(422, raised.exception.status_code)

    async def _other_stage(self) -> int:
        async with self.Session() as s:
            stage = models.Stage(
                tournament_id=self.tournament_id,
                scoring_rule_id=self.rule_id,
                name="Other",
                stage_type=enums.StageType.INDIVIDUAL_SWISS,
                order=9,
            )
            s.add(stage)
            await s.flush()
            await s.commit()
            return stage.id

    async def test_valid_pins_replace_the_previous_ones_and_request_a_recalculation(self) -> None:
        await self.set_pins([("t1", 2), ("t2", 1)])
        result = await self.set_pins([("d1", 1)])

        self.assertEqual([(self.members["d1"], 1)], [(p.workspace_member_id, p.position) for p in result.pins])
        self.assertEqual({self.members["d1"]: 1}, await self.stored())
        async with self.Session() as s:
            jobs = await s.scalar(
                sa.select(sa.func.count())
                .select_from(models.TournamentComputationJob)
                .where(models.TournamentComputationJob.tournament_id == self.tournament_id)
            )
        self.assertGreaterEqual(jobs, 1)

    async def test_an_empty_list_unpins_everyone(self) -> None:
        await self.set_pins([("t1", 1)])
        await self.set_pins([])
        self.assertEqual({}, await self.stored())

    async def test_pins_are_refused_once_the_qualification_is_locked(self) -> None:
        async with self.Session() as s:
            await s.execute(
                sa.update(models.Tournament)
                .where(models.Tournament.id == self.tournament_id)
                .values(status=enums.TournamentStatus.DRAFT)
            )
            await s.commit()
        with self.assertRaises(BaseAPIException) as raised:
            await self.set_pins([("t1", 1)])
        self.assertEqual(409, raised.exception.status_code)


class LockQualificationTests(IndividualSwissReadsCase):
    """Nobody is seeded as qualified: the lock must compute the table itself (K = 1: 1 tank, 2 damage, 2 support)."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await self.player("t1", "tank", 3500)
        await self.player("t2", "tank", 3400)
        await self.player("d1", "damage", 3000)
        await self.player("d2", "damage", 2900)
        await self.player("d3", "damage", 2800)

    async def lock(self) -> swiss_schemas.QualificationLockRead:
        stage = await self.stage()
        async with self.Session() as s:
            return await qualification_service.lock(s, stage, actor_user_id=None)

    async def tournament_status(self) -> enums.TournamentStatus:
        async with self.Session() as s:
            return await s.scalar(sa.select(models.Tournament.status).where(models.Tournament.id == self.tournament_id))

    async def test_a_stage_that_is_not_completed_is_refused_and_changes_nothing(self) -> None:
        with self.assertRaises(BaseAPIException) as raised:
            await self.lock()
        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual(enums.TournamentStatus.LIVE, await self.tournament_status())
        self.assertEqual({"ready"}, {status for status, _ in (await self.balancer_statuses()).values()})

    async def test_non_qualifiers_leave_the_pool_and_the_tournament_moves_to_draft(self) -> None:
        await self.complete()
        result = await self.lock()

        self.assertEqual(["t1", "d1", "d2"], [row.display_name for row in result.qualified])
        self.assertEqual(["t1"], [row.display_name for row in result.captains])
        self.assertEqual(
            {
                "t1": ("ready", None),
                "d1": ("ready", None),
                "d2": ("ready", None),
                "t2": ("excluded", "not_qualified"),
                "d3": ("excluded", "not_qualified"),
            },
            await self.balancer_statuses(),
        )
        self.assertEqual(enums.TournamentStatus.DRAFT, await self.tournament_status())
        self.assertIsNotNone((await self.stage()).qualification_locked_at)

    async def test_a_pin_saved_a_moment_ago_is_applied_before_the_cut(self) -> None:
        await self.complete()
        # No worker run between the pin and the lock: d3 pinned first displaces d2 out of the two damage places.
        await PinsTests.set_pins(self, [("d3", 1)])
        result = await self.lock()

        self.assertEqual(["t1", "d3", "d1"], [row.display_name for row in result.qualified])
        self.assertEqual("excluded", (await self.balancer_statuses())["d2"][0])
        self.assertEqual("ready", (await self.balancer_statuses())["d3"][0])

    async def test_pins_are_refused_after_the_lock(self) -> None:
        await self.complete()
        await self.lock()
        # The tournament is back in LIVE (the playoff), but the marker still freezes the table.
        async with self.Session() as s:
            await s.execute(
                sa.update(models.Tournament)
                .where(models.Tournament.id == self.tournament_id)
                .values(status=enums.TournamentStatus.LIVE)
            )
            await s.commit()
        with self.assertRaises(BaseAPIException) as raised:
            await PinsTests.set_pins(self, [("d3", 1)])
        self.assertEqual(409, raised.exception.status_code)

    async def test_a_second_lock_is_refused(self) -> None:
        await self.complete()
        await self.lock()
        with self.assertRaises(BaseAPIException) as raised:
            await self.lock()
        self.assertEqual(409, raised.exception.status_code)

    async def test_a_second_lock_is_refused_even_back_in_live(self) -> None:
        await self.complete()
        await self.lock()
        async with self.Session() as s:
            await s.execute(
                sa.update(models.Tournament)
                .where(models.Tournament.id == self.tournament_id)
                .values(status=enums.TournamentStatus.LIVE)
            )
            await s.commit()
        with self.assertRaises(BaseAPIException) as raised:
            await self.lock()
        self.assertEqual(409, raised.exception.status_code)

    async def test_a_draft_format_other_than_snake_is_refused_before_any_exclusion(self) -> None:
        await self.complete()
        async with self.Session() as s:
            await s.execute(
                sa.update(models.Tournament)
                .where(models.Tournament.id == self.tournament_id)
                .values(draft_format_json={"format": "linear", "round_rules": [], "avg_tie_seed_reverse": False})
            )
            await s.commit()
        with self.assertRaises(BaseAPIException) as raised:
            await self.lock()
        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("draft_format_not_snake", raised.exception.detail[0]["code"])
        self.assertEqual({"ready"}, {status for status, _ in (await self.balancer_statuses()).values()})
        self.assertEqual(enums.TournamentStatus.LIVE, await self.tournament_status())
        self.assertIsNone((await self.stage()).qualification_locked_at)

    async def test_another_stage_type_is_refused(self) -> None:
        async with self.Session() as s:
            stage = await s.get_one(models.Stage, self.stage_id)
            with self.assertRaises(BaseAPIException) as raised:
                await qualification_service.lock(s, stage)
        self.assertEqual(409, raised.exception.status_code)
