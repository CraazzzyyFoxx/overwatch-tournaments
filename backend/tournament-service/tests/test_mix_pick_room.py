"""Hero picks in a mix room (spec §11, §11.6): every member picks their own hero, a hero taken is gone for everyone
at once, the clock picks for whoever has not, and Fearless keeps a player off the heroes they were recorded on
earlier in the mix -- until that round is undone."""

from __future__ import annotations

import asyncio
import random
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import sqlalchemy as sa

from shared import models
from shared.core import enums
from shared.core.errors import BaseAPIException
from shared.services.encounter.participants import MemberSnapshot, place_team
from src.rpc import _helpers as rpc_helpers
from src.rpc import pick_ban_admin, public_rpc
from src.services.encounter.pick_ban_action import pick_ban_action_service
from src.services.encounter.pick_ban_session import pick_ban_session_service
from tests._rpc_fakes import CapturingBroker, make_identity
from tests.test_mix_pick_ban_room import MixBanRoomCase
from tests.test_pregame_participations import FIRST_HERO, RoomCase, hero_ruleset

HERO = enums.PickBanKind.HERO
#: Who sits where in ``MixBanRoomCase``: slot 1 (``self.seats[0]``) m0 + m1, slot 2 m2 + m3.
_SIDE = {"m0": 0, "m1": 0, "m2": 1, "m3": 1}


class MixPickRoomCase(MixBanRoomCase):
    """The ban room's Deadlock match on ``deadlock_bans_pick``: the four bans, then one open pick for every member."""

    ban_preset = "deadlock_bans_pick"

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        async with self.Session() as s:
            # Six more active heroes: the four bans take the fixture's four.
            extra = [
                models.CatalogEntity(
                    discipline="deadlock",
                    kind="character",
                    slug=f"pick-{self.encounter_id}-{i}",
                    name=f"pick {i}",
                    active=True,
                )
                for i in range(6)
            ]
            s.add_all(extra)
            await s.flush()
            self.picks = [hero.id for hero in extra]
            self.hero_rows.extend(self.picks)
            await s.commit()

    async def member_seats(self) -> dict[str, int]:
        """``{"m0": encounter.team_member id, ...}`` of the current match."""
        async with self.Session() as s:
            rows = await s.execute(
                sa.select(models.EncounterTeamMember.workspace_member_id, models.EncounterTeamMember.id).where(
                    models.EncounterTeamMember.encounter_id == self.encounter_id
                )
            )
            by_member = dict(rows.all())
        return {who: by_member[self.ids[who]] for who in _SIDE}

    async def ban_through(self) -> None:
        await self.open_room()
        for who, hero in zip(("p0", "p2", "p0", "p2"), self.heroes, strict=True):
            self.assertTrue((await self.captain_ban(who, hero))["ok"])

    async def pick(self, who: str, seat: int, hero: int) -> dict:
        async with self.Session() as s:
            return await pick_ban_action_service.perform_pick_ban_action(
                s, self.encounter_id, HERO, self.seats[_SIDE[who]], item_id=hero, action="pick", member_id=seat
            )

    async def picked_for(self) -> dict[int, int]:
        """``{hero: the seat it is for}`` of the room's picks."""
        return {
            entry["item_id"]: entry["picked_for_member_id"]
            for entry in (await self.state())["pool"]
            if entry["status"] == "picked"
        }

    async def everyone_picks(self) -> dict[str, int]:
        await self.ban_through()
        seat = await self.member_seats()
        for index, who in enumerate(_SIDE):
            await self.pick(who, seat[who], self.picks[index])
        return seat

    async def run_out_the_clock(self) -> None:
        async with self.Session() as s:
            pick_ban = await pick_ban_session_service.get_pick_ban_session(s, self.encounter_id, HERO, for_update=True)
            pick_ban.current_step_started_at = datetime.now(UTC) - timedelta(minutes=5)
            await s.commit()
        async with self.Session() as s:
            self.assertTrue(await pick_ban_action_service.reconcile_room(s, self.encounter_id, skip_locked=False))


class MixPickRoomTests(MixPickRoomCase):
    async def test_every_member_picks_their_own_hero_and_the_room_records_whose_it_is(self) -> None:
        seat = await self.everyone_picks()

        self.assertEqual({self.picks[i]: seat[who] for i, who in enumerate(_SIDE)}, await self.picked_for())
        self.assertEqual(enums.MapVetoSessionStatus.COMPLETED, (await self.hero_session()).status)

    async def test_a_hero_one_member_took_is_gone_for_everyone_at_once(self) -> None:
        await self.ban_through()
        seat = await self.member_seats()
        await self.pick("m2", seat["m2"], self.picks[0])

        with self.assertRaises(BaseAPIException) as refused:
            await self.pick("m0", seat["m0"], self.picks[0])

        self.assertEqual((400, "item_not_available"), (refused.exception.status_code, refused.exception.detail))

    async def test_two_members_racing_for_one_hero_the_first_lock_wins(self) -> None:
        await self.ban_through()
        seat = await self.member_seats()
        async with self.Session() as blocker:
            # Both requests are in flight together: each waits on the room lock this session holds.
            await blocker.execute(
                sa.select(models.Encounter.id).where(models.Encounter.id == self.encounter_id).with_for_update()
            )
            racing = [asyncio.create_task(self.pick(who, seat[who], self.picks[0])) for who in ("m0", "m2")]
            await asyncio.sleep(0.2)
            self.assertFalse(any(task.done() for task in racing))
            await blocker.commit()
        results = await asyncio.gather(*racing, return_exceptions=True)

        refused = [result for result in results if isinstance(result, BaseAPIException)]
        self.assertEqual([(400, "item_not_available")], [(error.status_code, error.detail) for error in refused])
        winner = "m0" if not isinstance(results[0], BaseException) else "m2"
        self.assertEqual({self.picks[0]: seat[winner]}, await self.picked_for())

    async def test_the_clock_picks_for_every_member_who_has_not(self) -> None:
        await self.ban_through()
        seat = await self.member_seats()
        await self.pick("m0", seat["m0"], self.picks[0])

        await self.run_out_the_clock()

        picked = await self.picked_for()
        self.assertEqual(sorted(seat.values()), sorted(picked.values()))
        self.assertEqual(seat["m0"], picked[self.picks[0]])
        self.assertEqual(enums.MapVetoSessionStatus.COMPLETED, (await self.hero_session()).status)


class MixTurnPickTests(MixPickRoomCase):
    """``deadlock_bans_pick_turns`` on the host's clocks: the four bans, then one player at a time in snake order."""

    ban_preset = "deadlock_bans_pick_turns"

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        async with self.Session() as s:
            mix = await s.get_one(models.CustomGame, self.mix_id)
            mix.hero_ban_seconds, mix.hero_pick_seconds = 20, 45
            await s.commit()

    async def test_the_players_pick_one_at_a_time_in_snake_order_on_the_hosts_clocks(self) -> None:
        await self.ban_through()
        seat = await self.member_seats()

        self.assertEqual([20] * 4 + [45] * 12, [step["timer_seconds"] for step in (await self.state())["sequence"]])
        # Two a side: A-BB-A seats everyone, and a team out of players owes its later turns nothing.
        turns = ("m0", "m2", "m3", "m1")
        for hero, who in zip(self.picks, turns, strict=False):
            self.assertEqual([seat[who]], (await self.state())["acting_member_ids"])
            await self.pick(who, seat[who], hero)

        self.assertEqual(
            {hero: seat[who] for hero, who in zip(self.picks, turns, strict=False)}, await self.picked_for()
        )
        self.assertEqual(enums.MapVetoSessionStatus.COMPLETED, (await self.hero_session()).status)


class MixTwoPhaseDraftTests(MixPickRoomCase):
    """``deadlock_two_phase_draft``: a ban each, the first picks in turn, a ban each, the rest."""

    ban_preset = "deadlock_two_phase_draft"

    async def test_the_second_bans_wait_for_the_first_picks_and_open_on_the_team_that_picked_second(self) -> None:
        await self.open_room()
        for who, hero in zip(("p0", "p2"), self.heroes, strict=False):
            self.assertTrue((await self.captain_ban(who, hero))["ok"])
        seat = await self.member_seats()
        # Two a side: the first half's A-BB-A seats everyone, and its last two turns are owed by nobody.
        for hero, who in zip(self.picks, ("m0", "m2", "m3", "m1"), strict=False):
            self.assertEqual([seat[who]], (await self.state())["acting_member_ids"])
            await self.pick(who, seat[who], hero)

        state = await self.state()
        self.assertEqual(("ban", [self.seats[1]]), (state["expected_action"], state["acting_team_ids"]))
        self.assertTrue((await self.captain_ban("p2", self.heroes[2]))["ok"])
        self.assertTrue((await self.captain_ban("p0", self.heroes[3]))["ok"])

        self.assertEqual(enums.MapVetoSessionStatus.COMPLETED, (await self.hero_session()).status)


class MixFearlessTests(MixPickRoomCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        async with self.Session() as s:
            (await s.get_one(models.CustomGame, self.mix_id)).hero_fearless = True
            await s.commit()

    async def record_and_start_again(self) -> int:
        """Record this match (``mix.round``) and start the next one on the same lineup; returns the recorded one."""
        recorded = self.encounter_id
        async with self.Session() as s:
            s.add(models.CustomGameRound(encounter_id=recorded, lobby_index=0))
            encounter = models.Encounter(
                workspace_id=self.ids["ws"],
                discipline="deadlock",
                custom_game_id=self.mix_id,
                scoring_rule_id=self.ids["rule"],
                name="T1 vs T2",
                slot_count=2,
                best_of=1,
                status=enums.EncounterStatus.OPEN,
            )
            s.add(encounter)
            await s.flush()
            self.seats = []
            for slot, (captain, player) in enumerate(((0, 1), (2, 3)), start=1):
                seat = await place_team(
                    s,
                    encounter,
                    slot=slot,
                    team_id=None,
                    name=f"T{slot}",
                    seed=None,
                    members=[
                        MemberSnapshot(self.ids[f"m{captain}"], f"P{captain}", 3000, False, (), is_captain=True),
                        MemberSnapshot(self.ids[f"m{player}"], f"P{player}", 2000, False, (), is_captain=False),
                    ],
                )
                s.add(models.EncounterReadiness(encounter_id=encounter.id, encounter_team_id=seat.id))
                self.seats.append(seat.id)
            s.add(
                models.EncounterGame(
                    encounter_id=encounter.id, position=1, state=enums.EncounterGameState.AWAITING_RESULT
                )
            )
            (await s.get_one(models.CustomGameLobby, (self.mix_id, 0))).live_encounter_id = encounter.id
            await s.commit()
            self.encounter_id = encounter.id
        return recorded

    async def test_a_player_cannot_pick_a_hero_they_played_earlier_in_the_mix(self) -> None:
        await self.everyone_picks()
        await self.record_and_start_again()
        await self.ban_through()
        seat = await self.member_seats()

        with self.assertRaises(BaseAPIException) as refused:
            await self.pick("m0", seat["m0"], self.picks[0])
        # Teams reshuffle: the hero is only m0's to lose.
        await self.pick("m2", seat["m2"], self.picks[0])

        self.assertEqual((400, "item_not_eligible"), (refused.exception.status_code, refused.exception.detail))
        self.assertEqual(seat["m2"], (await self.picked_for())[self.picks[0]])

    async def test_an_undone_round_gives_its_heroes_back(self) -> None:
        await self.everyone_picks()
        recorded = await self.record_and_start_again()
        async with self.Session() as s:
            # What Undo does (``CustomGameRoundRepository.delete_round``): the round's encounter goes, with its picks.
            await s.execute(sa.delete(models.Encounter).where(models.Encounter.id == recorded))
            await s.commit()
        await self.ban_through()
        seat = await self.member_seats()

        await self.pick("m0", seat["m0"], self.picks[0])

        self.assertEqual(seat["m0"], (await self.picked_for())[self.picks[0]])

    async def test_the_clock_gives_every_owing_member_a_hero_they_may_play_when_one_exists(self) -> None:
        # Round 1: m0..m3 play picks 0..3, so Fearless takes each off the one they played.
        await self.everyone_picks()
        await self.record_and_start_again()
        async with self.Session() as s:
            # Round 2's pool after the bans is picks 0..3 alone.
            await s.execute(
                sa.update(models.CatalogEntity).where(models.CatalogEntity.id.in_(self.picks[4:])).values(active=False)
            )
            await s.commit()
        await self.ban_through()
        seat = await self.member_seats()
        await self.pick("m0", seat["m0"], self.picks[1])
        await self.pick("m1", seat["m1"], self.picks[2])

        # Left: picks 0 and 3. m2 may play either; m3 only pick 0 -- a stand-in giving m2 pick 0 would strand m3.
        # Seed 4 is an order in which filling m2 on its own takes pick 0: only a joint fill gets this right every time.
        with patch("shared.domain.pick_ban_rules.runtime.secrets.SystemRandom", lambda: random.Random(4)):
            await self.run_out_the_clock()

        self.assertEqual(
            {
                self.picks[1]: seat["m0"],
                self.picks[2]: seat["m1"],
                self.picks[3]: seat["m2"],
                self.picks[0]: seat["m3"],
            },
            await self.picked_for(),
        )


class MixPickPermissionTests(MixPickRoomCase):
    async def act(self, who: str, seat: int, hero: int) -> dict:
        return await self.rpc(
            public_rpc.register,
            "rpc.tournament.captain_pick_ban_act",
            {
                "identity": make_identity(user_id=self.auth[who]),
                "id": self.encounter_id,
                "kind": "hero",
                "payload": {"action": "pick", "item_id": hero, "member_id": seat},
            },
        )

    async def read(self, who: str | None) -> dict:
        data = {"id": self.encounter_id, "kind": "hero"}
        if who is not None:
            data["identity"] = make_identity(user_id=self.auth[who])
        return (await self.rpc(public_rpc.register, "rpc.tournament.captain_pick_ban_state", data))["data"]

    async def test_a_player_picks_for_themselves_and_not_for_a_teammate(self) -> None:
        await self.ban_through()
        seat = await self.member_seats()

        refused = await self.act("p1", seat["m0"], self.picks[0])
        done = await self.act("p1", seat["m1"], self.picks[1])

        self.assertEqual("forbidden", refused["error"]["code"])
        self.assertTrue(done["ok"], done)
        self.assertEqual({self.picks[1]: seat["m1"]}, await self.picked_for())

    async def test_a_captain_picks_for_their_own_team_and_a_host_for_anyone(self) -> None:
        await self.ban_through()
        seat = await self.member_seats()

        across = await self.act("p0", seat["m3"], self.picks[0])
        teammate = await self.act("p0", seat["m1"], self.picks[1])
        host = await self.rpc(
            pick_ban_admin.register,
            "rpc.tournament.admin_pick_ban_act",
            {
                "identity": make_identity(user_id=self.auth["host"]),
                "id": self.encounter_id,
                "payload": {
                    "kind": "hero",
                    "encounter_team_id": self.seats[1],
                    "action": "pick",
                    "item_id": self.picks[2],
                    "member_id": seat["m3"],
                },
            },
        )

        self.assertEqual("forbidden", across["error"]["code"])
        self.assertTrue(teammate["ok"], teammate)
        self.assertTrue(host["ok"], host)
        self.assertEqual({self.picks[1]: seat["m1"], self.picks[2]: seat["m3"]}, await self.picked_for())

    async def test_the_room_tells_a_member_and_their_captain_it_is_their_turn(self) -> None:
        await self.ban_through()
        seat = await self.member_seats()
        await self.act("p1", seat["m1"], self.picks[0])

        picked = await self.read("p1")
        captain = await self.read("p0")
        player = await self.read("p3")
        spectator = await self.read(None)

        # p1 has picked; their captain still owes their own; p3 owes theirs; a spectator owes nothing.
        self.assertEqual((False, []), (picked["viewer_can_act"], picked["viewer_member_ids"]))
        self.assertEqual((True, [seat["m0"]]), (captain["viewer_can_act"], captain["viewer_member_ids"]))
        self.assertEqual((True, [seat["m3"]]), (player["viewer_can_act"], player["viewer_member_ids"]))
        self.assertFalse(spectator["viewer_can_act"])
        self.assertEqual(sorted((seat["m0"], seat["m2"], seat["m3"])), sorted(spectator["acting_member_ids"]))
        self.assertEqual(["P0", "P1", "P2", "P3"], [member["name"] for member in spectator["members"]])
        # Each member names the workspace member in the seat, so the room ties it to the lineup and the viewer.
        self.assertEqual(
            {seat[who]: self.ids[who] for who in _SIDE},
            {member["id"]: member["workspace_member_id"] for member in spectator["members"]},
        )
        self.assertNotIn(self.picks[0], spectator["member_eligible"][str(seat["m0"])])

    async def test_a_captain_late_in_pick_order_is_answered_with_their_own_seat_first(self) -> None:
        async with self.Session() as s:
            # Slot 2's crown moves to m3, who picks after m2.
            await s.execute(
                sa.update(models.EncounterTeamMember)
                .where(models.EncounterTeamMember.encounter_team_id == self.seats[1])
                .values(is_captain=models.EncounterTeamMember.workspace_member_id == self.ids["m3"])
            )
            await s.commit()
        await self.open_room()
        for who, hero in zip(("p0", "p3", "p0"), self.heroes[:3], strict=True):
            self.assertTrue((await self.captain_ban(who, hero))["ok"])
        seat = await self.member_seats()

        # The last team ban opens the members' pick: the captain's answer already reads it as the room does.
        answer = await self.captain_ban("p3", self.heroes[3])

        self.assertEqual([seat["m3"], seat["m2"]], answer["data"]["viewer_member_ids"])
        self.assertEqual(answer["data"]["viewer_member_ids"], (await self.read("p3"))["viewer_member_ids"])


class TournamentMemberIdTests(RoomCase):
    """A tournament seat names no members (R-F5): ``member_id`` is a 422 for its captain and its organizer alike,
    on act and submit, before any turn is read."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        async with self.Session() as s:
            account = models.AuthUser(email=f"{self.tag}@example.test", username=self.tag, is_active=True)
            player = models.User(name=self.tag)
            s.add_all([account, player])
            await s.flush()
            player.auth_user_id = account.id
            seat = await s.get_one(models.EncounterTeam, self.slot1)
            (await s.get_one(models.Team, seat.team_id)).captain_id = player.id
            await s.commit()
            self.account_id, self.player_id = account.id, player.id
        await self.configure(hero_ruleset())
        await self.ready_all()
        await self.open_room()

    async def asyncTearDown(self) -> None:
        async with self.Session() as s:
            await s.execute(sa.delete(models.Workspace).where(models.Workspace.id == self.workspace_id))
            await s.execute(sa.delete(models.User).where(models.User.id == self.player_id))
            await s.execute(sa.delete(models.AuthUser).where(models.AuthUser.id == self.account_id))
            await s.commit()
        await super().asyncTearDown()

    async def rpc(self, register, subject: str, identity: dict, payload: dict) -> dict:
        broker = CapturingBroker()
        register(broker, SimpleNamespace(exception=lambda *a, **k: None))
        data = {"identity": identity, "id": self.encounter_id, "kind": "hero", "payload": payload}
        with patch.object(rpc_helpers.db, "async_session_maker", self.Session):
            return await broker.handlers[subject](data, None)

    async def test_a_member_id_is_a_422_for_the_captain_and_the_organizer_alike(self) -> None:
        captain = make_identity(user_id=self.account_id)
        organizer = make_identity(user_id=self.account_id, is_superuser=True)
        act = {"action": "ban", "item_id": FIRST_HERO, "member_id": 1}
        submit = {"items": [{"item_id": FIRST_HERO, "member_id": 1}], "lock": True}
        seat = {"kind": "hero", "encounter_team_id": self.slot1}

        refused = [
            await self.rpc(public_rpc.register, "rpc.tournament.captain_pick_ban_act", captain, act),
            await self.rpc(public_rpc.register, "rpc.tournament.captain_pick_ban_submit", captain, submit),
            await self.rpc(pick_ban_admin.register, "rpc.tournament.admin_pick_ban_act", organizer, {**seat, **act}),
            await self.rpc(
                pick_ban_admin.register, "rpc.tournament.admin_pick_ban_submit", organizer, {**seat, **submit}
            ),
        ]
        done = await self.rpc(
            public_rpc.register,
            "rpc.tournament.captain_pick_ban_act",
            captain,
            {"action": "ban", "item_id": FIRST_HERO},
        )

        self.assertEqual(
            [("unprocessable", "member_id names a mix match's seat")] * 4,
            [(reply["error"]["code"], reply["error"]["message"]) for reply in refused],
        )
        # The same captain, naming no member, bans: the refusals were the member_id's alone.
        self.assertTrue(done["ok"], done)
