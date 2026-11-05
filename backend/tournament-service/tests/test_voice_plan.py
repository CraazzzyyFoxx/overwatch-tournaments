"""``build_voice_plan`` against the real test database: which channels a tournament wants, for whom, and when."""

from __future__ import annotations

import itertools
import os

import sqlalchemy as sa

from shared import models
from shared.core import enums
from shared.core.errors import BaseAPIException as HTTPException
from shared.messaging.config import TOURNAMENT_VOICE_SYNC_ROUTING_KEY
from shared.models.encounter import Encounter, EncounterTeam, EncounterTeamMember
from shared.models.tournament.bracket_encounter import BracketEncounter
from shared.models.tournament.stage import Stage, StageItem, StageItemInput
from src.schemas import voice as voice_schemas
from src.services.voice import admin as voice_admin
from src.services.voice.plan import build_voice_plan
from tests._encounter_layer import EncounterLayerCase, add_stage_node

_COUNTER = itertools.count(1)
SE = enums.StageType.SINGLE_ELIMINATION
IS = enums.StageType.INDIVIDUAL_SWISS


class VoicePlanCase(EncounterLayerCase):
    """The base tournament (LIVE, four teams ``t0``..``t3``, stage 1 = ``self.stage_id``) with voice enabled."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.users: list[int] = []
        self.auth_users: list[int] = []
        #: ``workspace_member_id -> Discord id`` of the members seeded with a link.
        self.discord: dict[int, str] = {}
        async with self.Session() as s:
            await s.execute(
                sa.update(models.Workspace)
                .where(models.Workspace.id == self.workspace_id)
                .values(discord_guild_id=str(800_000_000_000_000_000 + self.workspace_id))
            )
            s.add(models.TournamentVoiceSettings(tournament_id=self.tournament_id, enabled=True))
            await s.commit()

    async def asyncTearDown(self) -> None:
        await super().asyncTearDown()
        async with self.Session() as s:
            await s.execute(sa.delete(models.User).where(models.User.id.in_(self.users)))
            await s.execute(sa.delete(models.AuthUser).where(models.AuthUser.id.in_(self.auth_users)))
            await s.commit()

    # ── seeds ──────────────────────────────────────────────────────────────

    async def member(self, name: str, *, discord: bool = True) -> int:
        """A workspace member; with ``discord`` its account has a Discord linked (see ``self.discord``)."""
        n = next(_COUNTER)
        async with self.Session() as s:
            user = models.User(name=f"{name}-{n}")
            s.add(user)
            await s.flush()
            self.users.append(user.id)
            member = models.WorkspaceMember(workspace_id=self.workspace_id, player_id=user.id)
            s.add(member)
            await s.flush()
            if discord:
                account = models.AuthUser(username=f"voice-{os.getpid()}-{n}", email=f"voice-{os.getpid()}-{n}@x.test")
                s.add(account)
                await s.flush()
                self.auth_users.append(account.id)
                user.auth_user_id = account.id
                discord_id = str(600_000_000_000_000_000 + os.getpid() * 1000 + n)
                s.add(
                    models.OAuthConnection(
                        auth_user_id=account.id, provider="discord", provider_user_id=discord_id, username=f"d{n}"
                    )
                )
                self.discord[member.id] = discord_id
            await s.commit()
            return member.id

    async def player(self, team: int, member_id: int, *, substitution: bool = False) -> int:
        async with self.Session() as s:
            player = models.Player(
                name=f"p{member_id}",
                team_id=self.teams[team],
                tournament_id=self.tournament_id,
                workspace_member_id=member_id,
                is_substitution=substitution,
            )
            s.add(player)
            await s.commit()
            return player.id

    async def stage(
        self,
        order: int,
        *,
        kind: enums.StageType = SE,
        teams: tuple[int, ...] = (),
        status: str = "draft",
        is_published: bool = False,
    ) -> int:
        """A stage (its node at ``status``) whose single item seats ``teams`` (indexes into ``self.teams``) as FINAL inputs."""
        async with self.Session() as s:
            stage = Stage(
                tournament_id=self.tournament_id,
                scoring_rule_id=self.rule_id,
                name=f"S{order}",
                stage_type=kind,
                order=order,
                is_published=is_published,
            )
            s.add(stage)
            await s.flush()
            add_stage_node(s, stage, status)
            item = StageItem(stage_id=stage.id, name="A", type=enums.StageItemType.GROUP, order=0)
            s.add(item)
            await s.flush()
            s.add_all(
                StageItemInput(
                    stage_item_id=item.id,
                    slot=slot,
                    input_type=enums.StageItemInputType.FINAL,
                    team_id=self.teams[index],
                )
                for slot, index in enumerate(teams, 1)
            )
            await s.commit()
            return stage.id

    async def flag(self, stage_id: int, *, status: str | None = None, is_published: bool | None = None) -> None:
        async with self.Session() as s:
            if status is not None:
                await s.execute(
                    sa.update(models.FlowNode).where(models.FlowNode.stage_id == stage_id).values(status=status)
                )
            if is_published is not None:
                await s.execute(sa.update(Stage).where(Stage.id == stage_id).values(is_published=is_published))
            await s.commit()

    async def seat_round(self, stage_id: int, round_: int, encounters: list[tuple[list[int], list[int]]]) -> None:
        """One individual Swiss round: per encounter, the member ids of side 1 and side 2 (team-less seats)."""
        async with self.Session() as s:
            tournament = await s.get_one(models.Tournament, self.tournament_id)
            for sides in encounters:
                encounter = Encounter(
                    workspace_id=tournament.workspace_id,
                    discipline=tournament.discipline,
                    tournament_id=tournament.id,
                    scoring_rule_id=self.rule_id,
                    name="E",
                    slot_count=2,
                )
                s.add(encounter)
                await s.flush()
                s.add(
                    BracketEncounter(
                        encounter_id=encounter.id, tournament_id=tournament.id, stage_id=stage_id, round=round_
                    )
                )
                for slot, members in enumerate(sides, 1):
                    seat = EncounterTeam(
                        encounter_id=encounter.id, tournament_id=tournament.id, slot=slot, name=f"Seat {slot}"
                    )
                    s.add(seat)
                    await s.flush()
                    s.add_all(
                        EncounterTeamMember(
                            encounter_id=encounter.id,
                            encounter_team_id=seat.id,
                            active=True,
                            workspace_member_id=member_id,
                            display_name_snapshot=f"m{member_id}",
                        )
                        for member_id in members
                    )
            await s.commit()

    async def plan(self):
        async with self.Session() as s:
            return await build_voice_plan(s, self.tournament_id)

    async def keys(self) -> list[str]:
        return [channel.slot_key for channel in (await self.plan()).channels]

    def team_key(self, index: int) -> str:
        return f"team:{self.teams[index]}"


class VoicePlanTeamTests(VoicePlanCase):
    async def test_a_team_drops_out_when_its_stage_is_deactivated_and_everything_goes_after_the_final(self) -> None:
        groups = await self.stage(1, teams=(0, 1), status="live", is_published=True)
        final = await self.stage(2, teams=(0,))
        self.assertEqual(["hub", self.team_key(0), self.team_key(1)], await self.keys())

        # The groups finished and the final went live: t1 did not advance.
        await self.flag(groups, status="completed")
        await self.flag(final, status="live", is_published=True)
        plan = await self.plan()
        self.assertEqual(["hub", self.team_key(0)], [c.slot_key for c in plan.channels])
        self.assertEqual([0, 1], [c.position for c in plan.channels])

        await self.flag(final, status="completed")
        plan = await self.plan()
        self.assertEqual(([], {}), (plan.channels, plan.routes))
        self.assertTrue(plan.enabled)

    async def test_nothing_exists_when_disabled_without_a_guild_or_after_the_tournament(self) -> None:
        await self.stage(1, teams=(0, 1), status="live", is_published=True)
        self.assertEqual(3, len(await self.keys()))
        async with self.Session() as s:
            await s.execute(sa.update(models.TournamentVoiceSettings).values(enabled=False))
            await s.commit()
        self.assertEqual([], await self.keys())
        async with self.Session() as s:
            await s.execute(sa.update(models.TournamentVoiceSettings).values(enabled=True))
            await s.execute(
                sa.update(models.Workspace)
                .where(models.Workspace.id == self.workspace_id)
                .values(discord_guild_id=None)
            )
            await s.commit()
        plan = await self.plan()
        self.assertEqual(([], None), (plan.channels, plan.guild_id))
        async with self.Session() as s:
            await s.execute(
                sa.update(models.Workspace)
                .where(models.Workspace.id == self.workspace_id)
                .values(discord_guild_id=str(800_000_000_000_000_000 + self.workspace_id))
            )
            await s.execute(
                sa.update(models.Tournament)
                .where(models.Tournament.id == self.tournament_id)
                .values(status=enums.TournamentStatus.COMPLETED)
            )
            await s.commit()
        self.assertEqual([], await self.keys())

    async def test_early_teams_make_every_team_voice_only_before_any_stage_was_activated(self) -> None:
        self.assertEqual([], await self.keys())
        async with self.Session() as s:
            await s.execute(sa.update(models.TournamentVoiceSettings).values(early_teams=True))
            await s.commit()
        self.assertEqual(["hub", *(self.team_key(i) for i in range(4))], await self.keys())

        # A stage that was activated once ends "early": the plan follows the live stages alone.
        await self.flag(self.stage_id, is_published=True)
        self.assertEqual([], await self.keys())

    async def test_a_team_voice_admits_the_substitute_and_the_replaced_player_but_not_a_removed_one(self) -> None:
        await self.stage(1, teams=(0,), status="live", is_published=True)
        replaced, substitute, removed = await self.member("a"), await self.member("b"), await self.member("c")
        await self.player(0, replaced)
        await self.player(0, substitute, substitution=True)
        removed_player = await self.player(0, removed)
        async with self.Session() as s:
            await s.execute(sa.delete(models.Player).where(models.Player.id == removed_player))
            await s.commit()

        plan = await self.plan()
        team = plan.channels[1]
        self.assertEqual(sorted([self.discord[replaced], self.discord[substitute]]), team.member_discord_ids)
        self.assertEqual(
            {self.discord[replaced]: self.team_key(0), self.discord[substitute]: self.team_key(0)}, plan.routes
        )
        self.assertEqual([], plan.warnings)

    async def test_a_player_without_discord_is_a_warning_not_a_member(self) -> None:
        await self.stage(1, teams=(0,), status="live", is_published=True)
        linked, unlinked = await self.member("a"), await self.member("b", discord=False)
        await self.player(0, linked)
        await self.player(0, unlinked)

        plan = await self.plan()
        self.assertEqual([self.discord[linked]], plan.channels[1].member_discord_ids)
        self.assertEqual(
            [("player_without_discord", unlinked, self.teams[0])],
            [(w.code, w.workspace_member_id, w.team_id) for w in plan.warnings],
        )


class VoicePlanSwissTests(VoicePlanCase):
    async def test_a_swiss_stage_with_a_playoff_has_team_voices_and_no_round_slots(self) -> None:
        await self.stage(1, kind=IS, status="completed", is_published=True)
        await self.stage(2, teams=(0, 1), status="live", is_published=True)
        self.assertEqual(["hub", self.team_key(0), self.team_key(1)], await self.keys())

    async def test_the_latest_round_fills_the_slots_and_a_slot_beats_the_team_voice(self) -> None:
        swiss = await self.stage(1, kind=IS, status="live", is_published=True)
        # A parallel stage of the same order keeps a team voice beside the slots.
        await self.stage(1, teams=(0,), status="live", is_published=True)
        m1, m2, m3, m4, m5, m6 = [await self.member(f"m{i}", discord=i != 6) for i in range(1, 7)]
        await self.player(0, m1)
        await self.seat_round(swiss, 1, [([m1, m2], [m3, m4]), ([m5], [m6])])
        await self.seat_round(swiss, 2, [([m5], [m1, m2]), ([m3, m4], [m6])])

        plan = await self.plan()
        slots = {c.slot_key: c for c in plan.channels if c.kind == "swiss_slot"}
        self.assertEqual([f"slot:{swiss}:{i}" for i in range(4)], list(slots))
        self.assertEqual(["Лобби 1 · A", "Лобби 1 · B", "Лобби 2 · A", "Лобби 2 · B"], [c.name for c in slots.values()])
        # Round 2 laid out to keep 1, 2 and 6 where round 1 put them.
        self.assertEqual(f"slot:{swiss}:0", plan.routes[self.discord[m1]])
        self.assertEqual(f"slot:{swiss}:0", plan.routes[self.discord[m2]])
        self.assertEqual(f"slot:{swiss}:1", plan.routes[self.discord[m5]])
        self.assertEqual(sorted([self.discord[m1], self.discord[m2]]), slots[f"slot:{swiss}:0"].member_discord_ids)
        self.assertNotIn(self.team_key(0), plan.routes.values())
        self.assertIn(self.team_key(0), [c.slot_key for c in plan.channels])
        self.assertEqual([("player_without_discord", m6)], [(w.code, w.workspace_member_id) for w in plan.warnings])
        self.assertEqual(list(range(len(plan.channels))), [c.position for c in plan.channels])

    async def test_a_completed_swiss_stage_has_no_slots(self) -> None:
        swiss = await self.stage(1, kind=IS, status="live", is_published=True)
        a, b = await self.member("a"), await self.member("b")
        await self.seat_round(swiss, 1, [([a], [b])])
        self.assertEqual(3, len(await self.keys()))
        await self.flag(swiss, status="completed")
        self.assertEqual([], await self.keys())


class VoiceAdminTests(VoicePlanCase):
    async def test_status_joins_the_plan_with_the_bots_rows_and_lists_the_dropped_ones(self) -> None:
        await self.stage(1, teams=(0, 1), status="live", is_published=True)
        async with self.Session() as s:
            s.add_all(
                [
                    models.TournamentVoiceChannel(
                        tournament_id=self.tournament_id,
                        kind="hub",
                        slot_key="hub",
                        discord_channel_id=111,
                        status="active",
                    ),
                    models.TournamentVoiceChannel(
                        tournament_id=self.tournament_id,
                        kind="team",
                        slot_key=self.team_key(3),
                        discord_channel_id=333,
                        status="deleting",
                    ),
                    models.TournamentVoiceChannel(
                        tournament_id=self.tournament_id, kind="category", slot_key="category:1", discord_channel_id=999
                    ),
                ]
            )
            await s.commit()
        async with self.Session() as s:
            result = await voice_admin.status_of(s, self.tournament_id)

        self.assertEqual(
            [
                ("hub", "active", "111"),
                (self.team_key(0), "planned", None),
                (self.team_key(1), "planned", None),
                (self.team_key(3), "deleting", "333"),
                ("category:1", "pending", "999"),
            ],
            [(c.slot_key, c.status, c.discord_channel_id) for c in result.channels],
        )
        self.assertTrue(result.guild_linked)

    async def test_saving_checks_a_new_category_and_requests_a_sync(self) -> None:
        async def channels(_guild: str) -> list[dict]:
            return [{"id": "10", "type": "category"}, {"id": "11", "type": "voice"}]

        async def roles(_guild: str) -> list[dict]:
            return [{"id": "20"}]

        async def save(**values):
            async with self.Session() as s:
                body = voice_schemas.VoiceSettings(enabled=True, **values)
                return await voice_admin.save_settings(
                    s, self.tournament_id, body, list_channels=channels, list_roles=roles
                )

        for values, detail in (
            ({"category_id": "11"}, "discord_category_not_in_guild"),
            ({"category_id": "12"}, "discord_category_not_in_guild"),
            ({"staff_role_ids": ["21"]}, "discord_role_not_in_guild"),
        ):
            with self.assertRaises(HTTPException) as caught:
                await save(**values)
            self.assertEqual(detail, caught.exception.detail)

        saved = await save(category_id="10", staff_role_ids=["20", "20"])
        self.assertEqual(("10", ["20"]), (saved.settings.category_id, saved.settings.staff_role_ids))
        async with self.Session() as s:
            queued = await s.scalars(
                sa.select(models.EventOutbox.routing_key).where(
                    models.EventOutbox.payload_json["tournament_id"].as_integer() == self.tournament_id
                )
            )
            self.assertEqual([TOURNAMENT_VOICE_SYNC_ROUTING_KEY], list(queued))
            # The outbox is not tied to the workspace the teardown deletes.
            await s.execute(
                sa.delete(models.EventOutbox).where(
                    models.EventOutbox.payload_json["tournament_id"].as_integer() == self.tournament_id
                )
            )
            await s.commit()
