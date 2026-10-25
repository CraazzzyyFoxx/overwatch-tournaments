"""One mix match on the encounter layer -- started, then recorded or thrown away -- and the reads every mix screen
makes of it (D74-D76)."""

from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_BACKEND_ROOT), str(REPO_BACKEND_ROOT / "balancer-service")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import sqlalchemy as sa  # noqa: E402

from shared import models  # noqa: E402
from shared.core.enums import (  # noqa: E402
    MapPoolEntryStatus,
    MapVetoSessionStatus,
    PickBanActorKind,
    PickBanKind,
    VetoSeedSource,
)
from shared.core.errors import BaseAPIException as HTTPException  # noqa: E402
from shared.disciplines import DISCIPLINES  # noqa: E402
from shared.domain.custom_game_round import winner_slot  # noqa: E402
from shared.models.platform.notification import Notification  # noqa: E402
from shared.repository import CatalogRoleRepository, CustomGamePlayerRepository, CustomGameRoundRepository  # noqa: E402
from shared.services.discord_messages import mix_subject  # noqa: E402
from shared.tests.encounter_writer_case import EncounterWriterCase  # noqa: E402
from src.domain.balancer.result_serializer import lobby_document  # noqa: E402
from src.rpc import custom  # noqa: E402
from src.services.custom_game import CustomGameService  # noqa: E402
from src.services.mix_ranker import mix_ranker_service  # noqa: E402
from src.services.mix_rounds import (  # noqa: E402
    MixMatchDraft,
    MixMatchSeat,
    MixResultDraft,
    record_mix_result,
    start_mix_match,
)


class _Broker:
    """Collects the RPC handlers ``custom.register`` subscribes, so a test can call one the way the broker would."""

    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}

    def subscriber(self, subject: str):
        def decorator(function):
            self.handlers[subject] = function
            return function

        return decorator


class CustomGameRoundStoreTests(EncounterWriterCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        async with self.Session() as s:
            mix = await self.mix_encounter(s)  # brings the custom game and its rule
            self.cg = await s.get_one(models.CustomGame, mix.custom_game_id)
            await s.execute(sa.delete(models.Encounter).where(models.Encounter.id == mix.id))
            await s.commit()
        self.rounds = CustomGameRoundRepository()
        #: Every live match a test saw: a Start with bans leaves its room request in the outbox.
        self.started: set[int] = set()
        self.accounts: list[int] = []

    async def asyncTearDown(self) -> None:
        # Nothing drains the outbox here, and the encounter a room request names goes with the workspace.
        async with self.Session() as s:
            await s.execute(
                sa.delete(models.EventOutbox).where(
                    models.EventOutbox.event_id.in_([f"pick_ban_room_open:{live}" for live in self.started])
                )
            )
            # Notification rows carry no FK, and their delivery events name only the row.
            await s.execute(
                sa.text(
                    "DELETE FROM event_outbox WHERE routing_key = 'notification.created'"
                    " AND (payload_json->>'notification_id')::bigint IN"
                    " (SELECT id FROM notification WHERE source_workspace_id = :ws)"
                ),
                {"ws": self.ids["ws"]},
            )
            await s.execute(sa.delete(Notification).where(Notification.source_workspace_id == self.ids["ws"]))
            await s.execute(sa.delete(models.AuthUser).where(models.AuthUser.id.in_(self.accounts)))
            await s.commit()
        await super().asyncTearDown()

    def _draft(self, *, lobby=0, winner=1, busy=frozenset(), deltas=(None, None), points=25, map_id=None):
        """One match of this mix as Start and Record are handed it: ``(MixMatchDraft, the result's fields)``."""
        m0, m1, m2 = (self.ids[f"m{i}"] for i in range(3))
        match = MixMatchDraft(
            custom_game_id=self.cg.id,
            workspace_id=self.ids["ws"],
            discipline="overwatch",
            scoring_rule_id=self.cg.scoring_rule_id,
            map_id=map_id,
            names=("Wolves", "Team 2"),
            seats=(
                (MixMatchSeat(m0, "Alpha", "tank", 3200, is_captain=True), MixMatchSeat(m1, "Bravo", None, 2900)),
                (MixMatchSeat(m2, "Charlie", "tank", 2600, is_captain=True),),
            ),
        )
        result = {
            "lobby_index": lobby,
            "names": ("Wolves", "Team 2"),
            "lineup_first_team": frozenset({m0, m1}),
            "winner": winner,
            "points_per_win_applied": points,
            "rank_deltas": {member: delta for member, delta in ((m0, deltas[0]), (m2, deltas[1])) if delta is not None},
            "busy": busy,
            "recorder_player_id": self.users[0],
        }
        return match, result

    async def _record(self, draft) -> int:
        """Start, then Record: what one played match of a lobby writes."""
        match, result = draft
        async with self.Session() as s:
            encounter = await start_mix_match(s, match)
            await record_mix_result(s, MixResultDraft(encounter_id=encounter.id, **result))
            await s.commit()
            return encounter.id

    async def _rows(self, sql: str, **params):
        async with self.Session() as s:
            return (await s.execute(sa.text(sql), params)).all()

    async def test_a_round_is_a_completed_host_encounter_of_its_mix(self) -> None:
        encounter_id = await self._record(self._draft())
        [row] = await self._rows(
            "SELECT tournament_id, custom_game_id, slot_count, best_of, name, status::text, result_status::text,"
            " result_source, result_version FROM encounter.encounter WHERE id = :id",
            id=encounter_id,
        )
        self.assertEqual((None, self.cg.id, 2, 1, "Wolves vs Team 2", "COMPLETED", "confirmed", "host", 1), tuple(row))
        self.assertEqual(
            [(1, "Wolves", 1.0, 1), (2, "Team 2", 0.0, 2)],
            [
                tuple(r)
                for r in await self._rows(
                    "SELECT slot, name, score, placement FROM encounter.team WHERE encounter_id = :id ORDER BY slot",
                    id=encounter_id,
                )
            ],
        )
        self.assertEqual(
            [("confirmed", "host", 1, 1, 0)],
            [
                tuple(r)
                for r in await self._rows(
                    "SELECT g.state::text, g.result_source::text, g.position, max(gt.score), min(gt.score)"
                    " FROM encounter.game g JOIN encounter.game_team gt ON gt.game_id = g.id WHERE g.encounter_id = :id"
                    " GROUP BY g.id",
                    id=encounter_id,
                )
            ],
        )
        self.assertEqual(
            [(1, self.users[0], "confirm", "host")],
            [
                tuple(r)
                for r in await self._rows(
                    "SELECT result_version, actor_user_id, action::text, source FROM encounter.result_audit"
                    " WHERE encounter_id = :id",
                    id=encounter_id,
                )
            ],
        )

    async def test_a_started_match_is_open_captained_and_invisible_to_every_round_read(self) -> None:
        match, _result = self._draft()
        async with self.Session() as s:
            encounter = await start_mix_match(s, match)
            await s.commit()

        [row] = await self._rows(
            "SELECT status::text, result_status::text, started_at IS NOT NULL FROM encounter.encounter WHERE id = :id",
            id=encounter.id,
        )
        self.assertEqual(("OPEN", "none", True), tuple(row))
        self.assertEqual(
            [("awaiting_result",)],
            [
                tuple(r)
                for r in await self._rows(
                    "SELECT state::text FROM encounter.game WHERE encounter_id = :id", id=encounter.id
                )
            ],
        )
        self.assertEqual(
            [(self.ids["m0"], True), (self.ids["m1"], False), (self.ids["m2"], True)],
            [
                tuple(r)
                for r in await self._rows(
                    "SELECT workspace_member_id, is_captain FROM encounter.team_member WHERE encounter_id = :id"
                    " ORDER BY workspace_member_id",
                    id=encounter.id,
                )
            ],
        )
        async with self.Session() as s:
            self.assertEqual([], list(await self.rounds.list_for_custom_game(s, self.cg.id)))
            self.assertEqual([], list(await self.rounds.seats(s, workspace_id=self.ids["ws"])))
            self.assertIsNone(await self.rounds.newest_id_for_lobby(s, self.cg.id, 0))

    async def test_seats_keep_their_role_rank_and_frozen_delta(self) -> None:
        encounter_id = await self._record(self._draft(deltas=(31, -28), points=None))
        seats = await self._rows(
            "SELECT tm.workspace_member_id, tm.display_name_snapshot, tm.rank, cr.code, rm.busy, rm.rank_delta_applied"
            " FROM encounter.team_member tm LEFT JOIN encounter.team_member_role r ON r.team_member_id = tm.id"
            " LEFT JOIN catalog.role cr ON cr.id = r.role_id"
            " JOIN mix.round_member rm ON rm.encounter_id = tm.encounter_id"
            " AND rm.workspace_member_id = tm.workspace_member_id WHERE tm.encounter_id = :id"
            " ORDER BY tm.workspace_member_id",
            id=encounter_id,
        )
        self.assertEqual(
            [
                (self.ids["m0"], "Alpha", 3200, "tank", False, 31),
                (self.ids["m1"], "Bravo", 2900, None, False, None),
                (self.ids["m2"], "Charlie", 2600, "tank", False, -28),
            ],
            [tuple(r) for r in seats],
        )

    async def test_seat_reads_use_the_encounters_rated_dimension_without_fanning_out(self) -> None:
        async with self.Session() as s:
            catalog = CatalogRoleRepository()
            await catalog.project_module(s, DISCIPLINES["lol"])
            mix = await s.get_one(models.CustomGame, self.cg.id)
            mix.discipline = "lol"
            # Persist the setup first: unit-of-work order between unrelated mappers is not a contract.
            await s.flush()
            match, result = self._draft()
            match = replace(
                match,
                discipline="lol",
                seats=(
                    (
                        MixMatchSeat(self.ids["m0"], "Alpha", "support", 3200),
                        MixMatchSeat(self.ids["m1"], "Bravo", "flex", 2900),
                    ),
                    (MixMatchSeat(self.ids["m2"], "Charlie", None, 2600),),
                ),
            )
            encounter = await start_mix_match(s, match)
            await record_mix_result(s, MixResultDraft(encounter_id=encounter.id, **result))
            trait = models.RoleDimension(discipline="lol", code="trait", name="Trait", selection_mode="single")
            s.add(trait)
            await s.flush()
            role = models.CatalogRole(dimension_id=trait.id, code="caller", name="Caller")
            s.add(role)
            await s.flush()
            ow = await catalog.resolve(s, discipline="overwatch", workspace_id=None, dimension=None, code="tank")
            members = (
                await s.scalars(
                    sa.select(models.EncounterTeamMember).where(models.EncounterTeamMember.encounter_id == encounter.id)
                )
            ).all()
            for member in members:
                s.add(models.EncounterTeamMemberRole(team_member_id=member.id, dimension_id=trait.id, role_id=role.id))
                s.add(
                    models.EncounterTeamMemberRole(
                        team_member_id=member.id, dimension_id=ow.dimension_id, role_id=ow.id
                    )
                )
            await s.flush()
            rows = await self.rounds.seats(s, workspace_id=self.ids["ws"], encounter_id=encounter.id)
            assert [(row.workspace_member_id, row.role) for row in rows] == [
                (self.ids["m0"], "support"),
                (self.ids["m1"], None),
                (self.ids["m2"], None),
            ]

    async def test_a_busy_member_who_is_seated_counts_as_seated(self) -> None:
        encounter_id = await self._record(self._draft(busy=frozenset({self.ids["m3"], self.ids["m1"]})))
        self.assertEqual(
            [(self.ids["m0"], False), (self.ids["m1"], False), (self.ids["m2"], False), (self.ids["m3"], True)],
            [
                tuple(r)
                for r in await self._rows(
                    "SELECT workspace_member_id, busy FROM mix.round_member WHERE encounter_id = :id"
                    " ORDER BY workspace_member_id",
                    id=encounter_id,
                )
            ],
        )

    async def test_a_draw_is_nil_nil_and_both_teams_share_first_place(self) -> None:
        encounter_id = await self._record(self._draft(winner=None, points=None))
        self.assertEqual(
            [(0.0, 1), (0.0, 1)],
            [
                tuple(r)
                for r in await self._rows(
                    "SELECT score, placement FROM encounter.team WHERE encounter_id = :id ORDER BY slot",
                    id=encounter_id,
                )
            ],
        )

    async def test_lobby_reads_go_newest_first_and_count_per_lobby(self) -> None:
        first = await self._record(self._draft(lobby=0))
        second = await self._record(self._draft(lobby=0))
        other = await self._record(self._draft(lobby=1))
        async with self.Session() as s:
            listed = await self.rounds.list_for_custom_game(s, self.cg.id)
            self.assertEqual([other, second, first], [r.encounter_id for r in listed])
            self.assertEqual(["Wolves", "Team 2"], [team.name for team in listed[0].encounter.teams])
            self.assertEqual(self.users[0], listed[0].encounter.result_audit[0].actor_user_id)
            self.assertEqual(second, await self.rounds.newest_id_for_lobby(s, self.cg.id, 0))
            self.assertEqual(
                {0: 2, 1: 1}, {k: v[0] for k, v in (await self.rounds.activity_for_lobbies(s, self.cg.id)).items()}
            )
            self.assertEqual(3, (await self.rounds.activity_for_games(s, [self.cg.id]))[self.cg.id][0])
            self.assertIsNone(await self.rounds.get_for_game(s, self.cg.id + 1000, first))
            self.assertEqual(first, (await self.rounds.get_for_game(s, self.cg.id, first)).encounter_id)

    async def test_the_list_reads_group_lobbies_seats_maps_and_roster_per_mix(self) -> None:
        tag = f"cgr-{self.ids['ws']}"
        async with self.Session() as s:
            oasis, ilios = (
                models.CatalogEntity(
                    discipline="overwatch",
                    kind="map",
                    slug=f"{tag}-{name}",
                    name=f"{tag} {name}",
                    image_path=f"{name}.png",
                )
                for name in ("oasis", "ilios")
            )
            s.add_all([oasis, ilios])
            s.add_all(
                [
                    models.CustomGamePlayer(custom_game_id=self.cg.id, workspace_member_id=self.ids[f"m{i}"])
                    for i in range(4)
                ]
            )
            await s.commit()
        # The game rows hold the maps (RESTRICT): they go with the workspace in asyncTearDown, the maps after it.
        self.addAsyncCleanup(self._drop_maps, [oasis.id, ilios.id])

        await self._record(self._draft(lobby=0, map_id=oasis.id))
        await self._record(self._draft(lobby=0, busy=frozenset({self.ids["m3"]}), map_id=ilios.id))
        await self._record(self._draft(lobby=1, map_id=oasis.id))
        await self._record(self._draft(lobby=1))  # no map rolled
        async with self.Session() as s:
            lobbies = await self.rounds.lobby_activity_for_games(s, [self.cg.id, self.cg.id + 1000])
            self.assertEqual(
                {self.cg.id: {0: 2, 1: 2}}, {g: {k: v[0] for k, v in by.items()} for g, by in lobbies.items()}
            )
            # m0, m1, m2 sat; m3 was only ever busy next door.
            self.assertEqual({self.cg.id: 3}, await self.rounds.player_counts_for_games(s, [self.cg.id]))
            # Distinct maps, the most recently played first -- not first-played, not alphabetical.
            self.assertEqual(
                {self.cg.id: [(oasis.name, "oasis.png"), (ilios.name, "ilios.png")]},
                await self.rounds.maps_for_games(s, [self.cg.id]),
            )
            self.assertEqual({self.cg.id: 4}, await CustomGamePlayerRepository().counts_for_games(s, [self.cg.id]))
            for read in (
                self.rounds.lobby_activity_for_games,
                self.rounds.player_counts_for_games,
                self.rounds.maps_for_games,
            ):
                self.assertEqual({}, await read(s, []))

    async def _drop_maps(self, map_ids: list[int]) -> None:
        async with self.Session() as s:
            await s.execute(sa.delete(models.CatalogEntity).where(models.CatalogEntity.id.in_(map_ids)))
            await s.commit()
        await self.engine.dispose()

    async def test_seat_rows_carry_both_sides_of_the_result(self) -> None:
        encounter_id = await self._record(self._draft(deltas=(5, None)))
        async with self.Session() as s:
            rows = await self.rounds.seats(s, workspace_id=self.ids["ws"], encounter_id=encounter_id)
        self.assertEqual(
            [
                (1, self.ids["m0"], "tank", 3200, 5, 1.0, 0.0),
                (1, self.ids["m1"], None, 2900, None, 1.0, 0.0),
                (2, self.ids["m2"], "tank", 2600, None, 0.0, 1.0),
            ],
            [
                (r.slot, r.workspace_member_id, r.role, r.rank, r.rank_delta_applied, r.own_score, r.other_score)
                for r in rows
            ],
        )

    async def test_the_winner_slot_is_read_off_the_seat_scores(self) -> None:
        for winner in (1, 2, None):
            encounter_id = await self._record(self._draft(winner=winner, points=None))
            async with self.Session() as s:
                rows = await self.rounds.seats(s, workspace_id=self.ids["ws"], encounter_id=encounter_id)
            self.assertEqual({winner}, {winner_slot(r.slot, r.own_score, r.other_score) for r in rows})

    async def test_deleting_a_round_removes_everything_it_wrote(self) -> None:
        encounter_id = await self._record(self._draft(busy=frozenset({self.ids["m3"]})))
        async with self.Session() as s:
            await self.rounds.delete_round(s, encounter_id)
            await s.commit()
        for table, column in (
            ("encounter.encounter", "id"),
            ("encounter.team_member", "encounter_id"),
            ("encounter.game", "encounter_id"),
            ("encounter.result_audit", "encounter_id"),
            ("mix.round", "encounter_id"),
            ("mix.round_member", "encounter_id"),
        ):
            [(count,)] = await self._rows(f"SELECT count(*) FROM {table} WHERE {column} = :id", id=encounter_id)
            self.assertEqual(0, count, table)

    async def _new_mix(self) -> int:
        """Another mix of this workspace, on this mix's rule."""
        async with self.Session() as s:
            mix = models.CustomGame(
                workspace_id=self.ids["ws"], name="Next door", scoring_rule_id=self.cg.scoring_rule_id
            )
            s.add(mix)
            await s.commit()
            return mix.id

    async def _lobbies(self, *pairings: tuple[str, str], game_id: int | None = None) -> None:
        """Give a mix -- this one unless ``game_id`` names another -- one lobby per pairing: lobby ``i`` shows a 1v1
        of its two members (``"m0"``..``"m3"``)."""
        game_id = self.cg.id if game_id is None else game_id
        async with self.Session() as s:
            mix = await s.get_one(models.CustomGame, game_id)
            mix.lobby_count = len(pairings)
            for index, pairing in enumerate(pairings):
                teams = [
                    {"roster": {"tank": [{"uuid": str(self.ids[member]), "assigned_rating": 2500}]}}
                    for member in pairing
                ]
                s.add(
                    models.CustomGameLobby(
                        custom_game_id=game_id,
                        lobby_index=index,
                        balance_result_json=lobby_document([{"teams": teams}]),
                    )
                )
            await s.commit()

    def _host(self, lobby_index: int | None = None, *, game_id: int | None = None) -> dict[str, object]:
        """A write of a mix (this one unless ``game_id`` names another) by a superuser -- no co-host grant to seed --
        on one lobby when ``lobby_index`` is given."""
        args: dict[str, object] = {
            "workspace_id": self.ids["ws"],
            "custom_game_id": self.cg.id if game_id is None else game_id,
            "actor_user_id": 0,
            "actor_is_superuser": True,
        }
        return args if lobby_index is None else {**args, "lobby_index": lobby_index}

    async def _write(self, write, lobby_index: int, *, game_id: int | None = None, **extra: object) -> None:
        """One host write of a lobby in its own committed transaction, the way an RPC runs it."""
        async with self.Session() as s:
            await write(s, **self._host(lobby_index, game_id=game_id), **extra)
            await s.commit()

    async def _live_ids(self, game_id: int | None = None) -> list[int | None]:
        rows = await self._rows(
            "SELECT live_encounter_id FROM mix.lobby WHERE custom_game_id = :id ORDER BY lobby_index",
            id=self.cg.id if game_id is None else game_id,
        )
        lives = [live for (live,) in rows]
        self.started.update(live for live in lives if live is not None)
        return lives

    async def _hidden_book(self) -> list[tuple]:
        rows = await self._rows(
            "SELECT workspace_member_id, role_id, mu, sigma FROM balancer.member_hidden_rating"
            " WHERE workspace_id = :ws ORDER BY workspace_member_id, role_id",
            ws=self.ids["ws"],
        )
        return [tuple(row) for row in rows]

    async def test_rounds_read_in_the_order_they_were_recorded_not_started(self) -> None:
        await self._lobbies(("m0", "m1"), ("m2", "m3"))
        service = CustomGameService()
        await self._write(service.start_match, 0)
        await self._write(service.start_match, 1)
        a, b = await self._live_ids()
        await self._write(service.record_outcome, 1, winner=1)
        await self._write(service.record_outcome, 0, winner=1)

        self.assertLess(a, b)  # A started first ...
        async with self.Session() as s:
            # ... and was recorded last: the history (and the rotation reading it) has it as the newest round,
            history = await self.rounds.list_for_custom_game(s, self.cg.id)
            self.assertEqual([a, b], [round_.encounter_id for round_ in history])
            # and the replay, the leaderboard and undo read B before it.
            seats = await self.rounds.seats(s, workspace_id=self.ids["ws"])
            self.assertEqual([b, a], list(dict.fromkeys(row.encounter_id for row in seats)))

    async def test_a_rebuild_replays_rounds_in_the_order_they_were_recorded(self) -> None:
        # m0 is on the floor of two mixes at once: A here (against m1), B next door (against m2). B is recorded first.
        other = await self._new_mix()
        await self._lobbies(("m0", "m1"))
        await self._lobbies(("m0", "m2"), game_id=other)
        service = CustomGameService()
        await self._write(service.start_match, 0)
        await self._write(service.start_match, 0, game_id=other)
        [a], [b] = await self._live_ids(), await self._live_ids(other)
        await self._write(service.record_outcome, 0, game_id=other, winner=2)  # m2 beats m0 ...
        await self._write(service.record_outcome, 0, winner=1)  # ... then m0 beats m1
        incremental = await self._hidden_book()

        async with self.Session() as s:
            await mix_ranker_service.rebuild(s, self.ids["ws"])
            await s.commit()

        self.assertLess(a, b)
        self.assertEqual(3, len(incremental))
        self.assertEqual(incremental, await self._hidden_book())
        async with self.Session() as s:
            stats = await service.mix_stats(s, workspace_id=self.ids["ws"], discipline="overwatch", since=None)
        [m0] = [row for row in stats["members"] if row["workspace_member_id"] == self.ids["m0"]]
        # A, recorded last, is m0's newest result: a win on top of B's loss.
        self.assertEqual(([a, b], 1), ([entry["match_id"] for entry in m0["form"]], m0["streak"]))

    async def test_a_second_start_of_a_live_lobby_waits_for_the_first_and_is_refused(self) -> None:
        await self._lobbies(("m0", "m1"))
        service = CustomGameService()
        async with self.Session() as first, self.Session() as second:
            await service.start_match(first, **self._host(0))
            racing = asyncio.create_task(service.start_match(second, **self._host(0)))
            await asyncio.sleep(0.2)
            # The mix row is the first Start's until it commits: the second one waits, it does not race past.
            self.assertFalse(racing.done())
            await first.commit()
            with self.assertRaises(HTTPException) as ctx:
                await racing
            await second.rollback()

        self.assertEqual((409, "match_live"), (ctx.exception.status_code, ctx.exception.detail))
        [(count,)] = await self._rows(
            "SELECT count(*) FROM encounter.encounter WHERE custom_game_id = :id", id=self.cg.id
        )
        self.assertEqual(1, count)
        [live] = await self._live_ids()
        self.assertIsNotNone(live)

    async def test_a_reshape_racing_a_start_waits_for_it_and_is_refused(self) -> None:
        await self._lobbies(("m0", "m1"))
        service = CustomGameService()
        m0, m1 = str(self.ids["m0"]), str(self.ids["m1"])
        reshapes = {
            "swap": (service.swap_seats, {"variant_index": 0, "first_uuid": m0, "second_uuid": m1}),
            "page": (service.set_variant_index, {"variant_index": 0}),
            "balance": (service.balance, {}),
        }
        lineup = "SELECT balance_result_json, selected_variant_index FROM mix.lobby WHERE custom_game_id = :id"
        before = await self._rows(lineup, id=self.cg.id)
        for name, (write, extra) in reshapes.items():
            with self.subTest(name):
                async with self.Session() as first, self.Session() as second:
                    await service.start_match(first, **self._host(0))
                    racing = asyncio.create_task(write(second, **self._host(0), **extra))
                    await asyncio.sleep(0.2)
                    # Start holds the mix row until it commits: the reshape waits, then reads the lobby live.
                    self.assertFalse(racing.done())
                    await first.commit()
                    with self.assertRaises(HTTPException) as ctx:
                        await racing
                    await second.rollback()

                self.assertEqual((409, "match_live"), (ctx.exception.status_code, ctx.exception.detail))
                self.assertEqual(before, await self._rows(lineup, id=self.cg.id))
                await self._write(service.cancel_match, 0)

    async def test_cancel_and_close_leave_no_live_match_and_no_encounter_behind(self) -> None:
        await self._lobbies(("m0", "m1"), ("m2", "m3"))
        service = CustomGameService()
        for lobby_index in (0, 1):
            await self._write(service.start_match, lobby_index)
        started = await self._live_ids()
        self.assertTrue(all(started), started)

        await self._write(service.cancel_match, 0)
        self.assertEqual([None, started[1]], await self._live_ids())
        async with self.Session() as s:
            await service.close(s, **self._host())
            await s.commit()

        self.assertEqual([None, None], await self._live_ids())
        [(status,)] = await self._rows("SELECT status FROM mix.custom_game WHERE id = :id", id=self.cg.id)
        self.assertEqual("completed", status)
        for table, column in (
            ("encounter.encounter", "id"),
            ("encounter.team", "encounter_id"),
            ("encounter.team_member", "encounter_id"),
            ("encounter.game", "encounter_id"),
        ):
            [(count,)] = await self._rows(f"SELECT count(*) FROM {table} WHERE {column} = ANY(:ids)", ids=list(started))
            self.assertEqual(0, count, table)

    async def test_start_freezes_the_shown_lineup_on_the_next_map_and_goes_live(self) -> None:
        tag = f"cgs-{self.ids['ws']}"
        async with self.Session() as s:
            kings_row = models.CatalogEntity(discipline="overwatch", kind="map", slug=f"{tag}-kr", name=f"{tag} KR")
            s.add(kings_row)
            await s.commit()
        self.addAsyncCleanup(self._drop_maps, [kings_row.id])

        def seat(member: str, name: str, rating: int) -> dict[str, object]:
            return {"uuid": str(self.ids[member]), "name": name, "assigned_rating": rating}

        option = {
            "teams": [
                {"roster": {"tank": [seat("m0", "Alpha", 3200)], "damage": [seat("m1", "Bravo", 2900)]}},
                {"roster": {"tank": [seat("m2", "Charlie", 2600)], "damage": [seat("m3", "Delta", 3000)]}},
            ]
        }
        async with self.Session() as s:
            s.add(
                models.CustomGameLobby(
                    custom_game_id=self.cg.id,
                    lobby_index=0,
                    balance_result_json=lobby_document([option]),
                    next_map_id=kings_row.id,
                )
            )
            s.add(models.CustomGameTeamName(custom_game_id=self.cg.id, team_index=0, name="Wolves"))
            await s.commit()

        await self._write(CustomGameService().start_match, 0)

        # Live on the encounter Start opened; the map is the match's now and stays on the card.
        [live] = await self._live_ids()
        [(next_map,)] = await self._rows("SELECT next_map_id FROM mix.lobby WHERE custom_game_id = :id", id=self.cg.id)
        self.assertEqual(kings_row.id, next_map)
        encounters = await self._rows(
            "SELECT id, status::text FROM encounter.encounter WHERE custom_game_id = :id", id=self.cg.id
        )
        self.assertEqual([(live, "OPEN")], [tuple(r) for r in encounters])
        games = await self._rows("SELECT map_id, state::text FROM encounter.game WHERE encounter_id = :id", id=live)
        self.assertEqual([(kings_row.id, "awaiting_result")], [tuple(r) for r in games])
        # The snapshot: each team's name and every seat as the lineup stood -- role, rating, name, and the captain,
        # the team's strongest seat.
        seats = await self._rows(
            "SELECT et.slot, et.name, tm.workspace_member_id, cr.code, tm.rank, tm.display_name_snapshot, tm.is_captain"
            " FROM encounter.team et JOIN encounter.team_member tm ON tm.encounter_team_id = et.id"
            " LEFT JOIN encounter.team_member_role r ON r.team_member_id = tm.id"
            " LEFT JOIN catalog.role cr ON cr.id = r.role_id"
            " WHERE et.encounter_id = :id ORDER BY et.slot, tm.display_name_snapshot",
            id=live,
        )
        m0, m1, m2, m3 = (self.ids[f"m{i}"] for i in range(4))
        self.assertEqual(
            [
                (1, "Wolves", m0, "tank", 3200, "Alpha", True),
                (1, "Wolves", m1, "damage", 2900, "Bravo", False),
                (2, "Team 2", m2, "tank", 2600, "Charlie", False),
                (2, "Team 2", m3, "damage", 3000, "Delta", True),
            ],
            [tuple(r) for r in seats],
        )
        # Started, not recorded: no round yet.
        async with self.Session() as s:
            self.assertEqual([], list(await self.rounds.list_for_custom_game(s, self.cg.id)))

    async def test_a_failed_voice_split_leaves_the_started_match_committed(self) -> None:
        await self._lobbies(("m0", "m1"))
        async with self.Session() as s:
            await s.execute(
                sa.update(models.CustomGameLobby)
                .where(models.CustomGameLobby.custom_game_id == self.cg.id)
                .values(team1_voice_channel_id=101, team2_voice_channel_id=102)
            )
            await s.commit()
        broker = _Broker()
        custom.register(broker, logging.getLogger(__name__))

        async def unannounced(*_args, **_kwargs) -> None:
            """The realtime and outbox signal is not what this test is about."""

        identity = {
            "user_id": 1,
            "is_superuser": True,
            "is_active": True,
            "roles": [],
            "permissions": [],
            "workspaces": [{"workspace_id": self.ids["ws"], "role": "owner", "rbac_roles": [], "rbac_permissions": []}],
        }
        with (
            patch.object(custom, "_SF", self.Session),
            patch.object(custom, "emit_pickup_mix_changed", unannounced),
            self.assertLogs(__name__, "WARNING") as logs,
        ):
            result = await broker.handlers["rpc.balancer.custom.start_match"](
                {
                    "identity": identity,
                    "workspace_id": self.ids["ws"],
                    "custom_game_id": self.cg.id,
                    "payload": {"lobby_index": 0},
                },
                None,
            )

        # The lobby has both team voices, but the workspace has no voice category: the split fails after the commit,
        # and Start still answers with the mix ...
        self.assertIn("voice split skipped (voice_not_configured)", "\n".join(logs.output))
        self.assertTrue(result["ok"], result)
        # ... whose match is committed and live.
        [live] = await self._live_ids()
        self.assertIsNotNone(live)
        rows = await self._rows("SELECT status::text FROM encounter.encounter WHERE id = :id", id=live)
        self.assertEqual([("OPEN",)], [tuple(r) for r in rows])

    async def test_hard_delete_waits_for_the_mix_lock_before_it_touches_the_mix_posts(self) -> None:
        async with self.Session() as s:
            post = models.DiscordMessage(
                channel="discord_channel",
                target="1",
                subject=mix_subject(self.cg.id),
                slot="signup",
                kind="mix_signup",
                workspace_id=self.ids["ws"],
                status="posted",
            )
            s.add(post)
            await s.commit()
        service = CustomGameService()
        try:
            async with self.Session() as host, self.Session() as admin:
                # A host write holds the mix row, the way every `_writable` write does ...
                await service.rename(host, **self._host(), name="Night")
                deleting = asyncio.create_task(
                    service.hard_delete(admin, workspace_id=self.ids["ws"], custom_game_id=self.cg.id)
                )
                await asyncio.sleep(0.2)
                self.assertFalse(deleting.done())
                # ... then goes on to the mix's post (mix -> message). The delete must be queued on the mix, not
                # holding the post: otherwise the two wait on each other and Postgres aborts one as a deadlock.
                _game, taken_down = await service.delete_discord_post(host, **self._host(), post_id=post.id)
                await host.commit()
                left_over = await deleting
                await admin.commit()

            # The host's delete went out; the hard delete found the post already on its way out.
            self.assertEqual(([post.id], []), ([command.message_ref for command in taken_down], left_over))
            self.assertEqual([], await self._rows("SELECT id FROM mix.custom_game WHERE id = :id", id=self.cg.id))
            self.assertEqual(
                [("deleting",)], await self._rows("SELECT status FROM discord_message WHERE id = :id", id=post.id)
            )
        finally:
            async with self.Session() as s:
                await s.execute(sa.delete(models.DiscordMessage).where(models.DiscordMessage.id == post.id))
                await s.commit()

    async def test_a_round_spent_away_drops_out_of_the_rotation_history(self) -> None:
        # Two matches of m0 against m1. m2 waits through both; m3 waits through the first and is away for the second.
        await self._lobbies(("m0", "m1"))
        async with self.Session() as s:
            s.add_all(
                [
                    models.CustomGamePlayer(custom_game_id=self.cg.id, workspace_member_id=self.ids[f"m{i}"])
                    for i in range(4)
                ]
            )
            await s.commit()
        service = CustomGameService()

        async def set_away(member: str, away: bool) -> None:
            async with self.Session() as s:
                await service.update_player(
                    s, **self._host(), workspace_member_id=self.ids[member], patch={"away": away}
                )
                await s.commit()

        await self._write(service.start_match, 0)
        await self._write(service.record_outcome, 0, winner=1)
        await set_away("m3", True)
        # Started anyway with m0 away in the lineup: the seat beats the away mark.
        await set_away("m0", True)
        await self._write(service.start_match, 0)
        await self._write(service.record_outcome, 0, winner=1)
        await set_away("m3", False)
        await set_away("m0", False)

        async with self.Session() as s:
            rotation = await service.rotation(s, workspace_id=self.ids["ws"], custom_game_id=self.cg.id)
        # (sat-out streak, played streak, games played): the three keys of the rotation priority.
        self.assertEqual(
            {
                self.ids["m0"]: (0, 2, 2),
                self.ids["m1"]: (0, 2, 2),
                self.ids["m2"]: (2, 0, 0),
                # One wait, exactly as if the away match had never been recorded -- not two, and not a reset.
                self.ids["m3"]: (1, 0, 0),
            },
            {rec.member_id: (rec.consecutive_sat, rec.consecutive_played, rec.games_played) for rec in rotation},
        )

    async def test_a_host_sets_and_clears_the_ban_preset_of_the_mixs_own_game(self) -> None:
        service = CustomGameService()

        async def stored() -> str | None:
            [(value,)] = await self._rows("SELECT hero_ban_preset FROM mix.custom_game WHERE id = :id", id=self.cg.id)
            return value

        async with self.Session() as s:
            await service.set_ban_preset(s, **self._host(), hero_ban_preset="hero_classic")
            await s.commit()
        self.assertEqual("hero_classic", await stored())

        async with self.Session() as s:
            with self.assertRaises(HTTPException) as refused:
                await service.set_ban_preset(s, **self._host(), hero_ban_preset="deadlock_hero_bans")
        self.assertEqual((422, "unknown_ban_preset"), (refused.exception.status_code, refused.exception.detail))

        async with self.Session() as s:
            await service.set_ban_preset(s, **self._host(), hero_ban_preset=None)
            await s.commit()
        self.assertIsNone(await stored())

    async def test_the_header_keeps_the_rooms_clocks_and_pickers_until_it_sends_them(self) -> None:
        """The preset select and the Fearless switch send no clocks or pickers and leave them; ``null`` hands a clock
        back to the preset."""
        broker = _Broker()
        custom.register(broker, logging.getLogger(__name__))
        identity = {
            "user_id": 1,
            "is_superuser": True,
            "is_active": True,
            "roles": [],
            "permissions": [],
            "workspaces": [{"workspace_id": self.ids["ws"], "role": "owner", "rbac_roles": [], "rbac_permissions": []}],
        }

        async def unannounced(*_args, **_kwargs) -> None:
            """The realtime and outbox signal is not what this test is about."""

        async def put(payload: dict[str, object]) -> tuple[object, ...]:
            with (
                patch.object(custom, "_SF", self.Session),
                patch.object(custom, "emit_pickup_mix_changed", unannounced),
            ):
                result = await broker.handlers["rpc.balancer.custom.set_ban_preset"](
                    {
                        "identity": identity,
                        "workspace_id": self.ids["ws"],
                        "custom_game_id": self.cg.id,
                        "payload": payload,
                    },
                    None,
                )
            self.assertTrue(result["ok"], result)
            data = result["data"]
            return tuple(
                data[key] for key in ("hero_ban_seconds", "hero_pick_seconds", "hero_free_order", "hero_captains_only")
            )

        self.assertEqual(
            (20, 45, True, True),
            await put(
                {
                    "hero_ban_preset": "hero_classic",
                    "hero_ban_seconds": 20,
                    "hero_pick_seconds": 45,
                    "hero_free_order": True,
                    "hero_captains_only": True,
                }
            ),
        )
        self.assertEqual((20, 45, True, True), await put({"hero_ban_preset": None}))
        self.assertEqual((20, 45, True, True), await put({"hero_ban_preset": "hero_classic", "hero_fearless": True}))
        self.assertEqual(
            (20, None, False, True),
            await put({"hero_ban_preset": "hero_classic", "hero_pick_seconds": None, "hero_free_order": False}),
        )

    async def _rated_lobby(self, first: int, second: int, *, preset: str | None = "hero_classic") -> None:
        """Lobby A: m0 (rated ``first``) against m1 (rated ``second``), on a mix playing ``preset``."""

        def team(member: str, rating: int) -> dict[str, object]:
            return {
                "roster": {"tank": [{"uuid": str(self.ids[member]), "name": member.upper(), "assigned_rating": rating}]}
            }

        async with self.Session() as s:
            (await s.get_one(models.CustomGame, self.cg.id)).hero_ban_preset = preset
            s.add(
                models.CustomGameLobby(
                    custom_game_id=self.cg.id,
                    lobby_index=0,
                    balance_result_json=lobby_document([{"teams": [team("m0", first), team("m1", second)]}]),
                )
            )
            await s.commit()

    async def _set_preset(self, preset: str | None) -> None:
        """The host's header edit."""
        async with self.Session() as s:
            await CustomGameService().set_ban_preset(s, **self._host(), hero_ban_preset=preset)
            await s.commit()

    async def _slots(self, encounter_id: int) -> list[tuple[int, int]]:
        rows = await self._rows(
            "SELECT et.slot, tm.workspace_member_id FROM encounter.team et"
            " JOIN encounter.team_member tm ON tm.encounter_team_id = et.id"
            " WHERE et.encounter_id = :id ORDER BY et.slot",
            id=encounter_id,
        )
        return [tuple(row) for row in rows]

    async def _ready(self, encounter_id: int) -> int:
        [(count,)] = await self._rows(
            "SELECT count(*) FROM encounter.readiness WHERE encounter_id = :id", id=encounter_id
        )
        return count

    async def _room_requests(self, encounter_id: int) -> list[tuple[str, int]]:
        rows = await self._rows(
            "SELECT routing_key, (payload_json->>'encounter_id')::bigint FROM event_outbox WHERE event_id = :id",
            id=f"pick_ban_room_open:{encounter_id}",
        )
        return [tuple(row) for row in rows]

    async def _frozen_preset(self) -> str | None:
        [(preset,)] = await self._rows(
            "SELECT live_ban_preset FROM mix.lobby WHERE custom_game_id = :id", id=self.cg.id
        )
        return preset

    async def _pregame(self, *encounter_ids: int) -> frozenset[int]:
        async with self.Session() as s:
            return await CustomGameService().lobbies.pregame_ids(s, list(encounter_ids))

    async def _hero_room(self, encounter_id: int, status: MapVetoSessionStatus = MapVetoSessionStatus.ACTIVE) -> int:
        """The hero room tournament-service opens on the match; its id."""
        async with self.Session() as s:
            room = models.PickBanSession(
                encounter_id=encounter_id,
                kind=PickBanKind.HERO,
                pool_json={},
                seed_source=VetoSeedSource.FALLBACK_FIRST_SLOT,
                resolved_sequence_json=[],
                ruleset_json={},
                status=status,
            )
            s.add(room)
            await s.commit()
            return room.id

    async def test_a_start_with_bans_seats_the_weaker_team_first_and_asks_for_the_room(self) -> None:
        await self._rated_lobby(3000, 2000)

        await self._write(CustomGameService().start_match, 0)

        [live] = await self._live_ids()
        m0, m1 = self.ids["m0"], self.ids["m1"]
        self.assertEqual([(1, m1), (2, m0)], await self._slots(live))
        self.assertEqual(2, await self._ready(live))
        self.assertEqual([("tournament.encounter.pick_ban_room_open_requested", live)], await self._room_requests(live))
        self.assertEqual("hero_classic", await self._frozen_preset())
        self.assertEqual(frozenset({live}), await self._pregame(live))

    async def _captain_accounts(self) -> dict[str, int]:
        """A login behind m0 and m1 -- this lobby's two captains -- so a DM has an inbox to land in."""
        accounts: dict[str, int] = {}
        async with self.Session() as s:
            for index in (0, 1):
                account = models.AuthUser(
                    username=f"cap{index}-{self.cg.id}", email=f"cap{index}-{self.cg.id}@example.test"
                )
                s.add(account)
                await s.flush()
                (await s.get_one(models.User, self.users[index])).auth_user_id = account.id
                accounts[f"m{index}"] = account.id
            await s.commit()
        self.accounts.extend(accounts.values())
        return accounts

    async def _dms(self, kind: str) -> list[tuple[int, str, dict, bool]]:
        """``kind`` rows of this workspace: ``(recipient, dedupe key, payload, its delivery event is in the outbox)``."""
        rows = await self._rows(
            "SELECT n.recipient_auth_user_id, n.dedupe_key, n.payload_json, EXISTS (SELECT 1 FROM event_outbox o"
            " WHERE o.routing_key = 'notification.created' AND (o.payload_json->>'notification_id')::bigint = n.id)"
            " FROM notification n WHERE n.kind = :kind AND n.source_workspace_id = :ws"
            " ORDER BY n.recipient_auth_user_id",
            kind=kind,
            ws=self.ids["ws"],
        )
        return [tuple(row) for row in rows]

    async def test_a_start_with_bans_dms_each_captain_once_and_a_start_without_dms_nobody(self) -> None:
        """R3-3: the ban room opens on this very start, so each captain hears it now, linked to lobby A's room."""
        accounts = await self._captain_accounts()
        await self._rated_lobby(3000, 2000)

        await self._write(CustomGameService().start_match, 0)

        [live] = await self._live_ids()
        m0, m1 = self.ids["m0"], self.ids["m1"]
        room = {"custom_game_id": self.cg.id, "mix_name": "Mix", "lobby": "A"}
        self.assertEqual(
            sorted(
                [
                    (accounts["m0"], f"mix_ban_room:{live}:{m0}", room, True),
                    (accounts["m1"], f"mix_ban_room:{live}:{m1}", room, True),
                ]
            ),
            await self._dms("mix.ban_room_opened"),
        )

        await self._write(CustomGameService().cancel_match, 0)
        await self._set_preset(None)
        await self._write(CustomGameService().start_match, 0)

        self.assertEqual(2, len(await self._dms("mix.ban_room_opened")))

    async def test_the_host_flips_the_opener_and_a_mix_without_bans_keeps_the_lineup_order(self) -> None:
        await self._rated_lobby(3000, 2000)
        service = CustomGameService()
        await self._write(service.start_match, 0, flip_opener=True)
        [flipped] = await self._live_ids()
        self.assertEqual([(1, self.ids["m0"]), (2, self.ids["m1"])], await self._slots(flipped))
        await self._write(service.cancel_match, 0)
        self.assertIsNone(await self._frozen_preset())

        await self._set_preset(None)
        await self._write(service.start_match, 0, flip_opener=True)
        [plain] = await self._live_ids()
        self.assertEqual([(1, self.ids["m0"]), (2, self.ids["m1"])], await self._slots(plain))
        # Both seats are ready with or without bans (spec §5.1); only the room request needs a preset.
        self.assertEqual(2, await self._ready(plain))
        self.assertEqual([], await self._room_requests(plain))
        self.assertIsNone(await self._frozen_preset())
        # No preset, no Pre-game: the match is live at once.
        self.assertEqual(frozenset(), await self._pregame(plain))

    async def test_last_times_loser_opens_and_the_result_lands_on_the_lineup_team(self) -> None:
        await self._rated_lobby(3000, 2000)
        service = CustomGameService()
        await self._write(service.start_match, 0)
        [first] = await self._live_ids()
        self.assertEqual([(1, self.ids["m1"]), (2, self.ids["m0"])], await self._slots(first))  # the weaker opens
        await self._write(service.record_outcome, 0, winner=2)  # lineup team 2 = m1 wins

        scores = await self._rows(
            "SELECT tm.workspace_member_id, et.score FROM encounter.team et"
            " JOIN encounter.team_member tm ON tm.encounter_team_id = et.id WHERE et.encounter_id = :id",
            id=first,
        )
        self.assertEqual({self.ids["m0"]: 0.0, self.ids["m1"]: 1.0}, dict(scores))
        self.assertIsNone(await self._frozen_preset())

        await self._write(service.start_match, 0)
        [second] = await self._live_ids()
        # Same two teams: m0 lost, so m0 opens although it is the stronger team.
        self.assertEqual([(1, self.ids["m0"]), (2, self.ids["m1"])], await self._slots(second))

    async def test_a_preset_edit_after_start_keeps_the_preset_the_room_opens_on(self) -> None:
        await self._rated_lobby(3000, 2000)
        await self._write(CustomGameService().start_match, 0)
        [live] = await self._live_ids()

        await self._set_preset(None)

        # tournament-service opens -- and any reset reopens -- the room on the lobby's frozen copy, not the header.
        self.assertEqual("hero_classic", await self._frozen_preset())
        self.assertEqual(frozenset({live}), await self._pregame(live))

    async def test_pregame_lasts_until_the_hero_room_is_completed_or_cancelled(self) -> None:
        await self._rated_lobby(3000, 2000)
        await self._write(CustomGameService().start_match, 0)
        [live] = await self._live_ids()
        room = await self._hero_room(live)

        for status, pregame in (
            (MapVetoSessionStatus.ACTIVE, {live}),
            (MapVetoSessionStatus.COMPLETED, set()),
            (MapVetoSessionStatus.CANCELLED, set()),
        ):
            async with self.Session() as s:
                (await s.get_one(models.PickBanSession, room)).status = status
                await s.commit()
            self.assertEqual(frozenset(pregame), await self._pregame(live), status)

    async def test_the_history_lists_a_rounds_hero_bans_in_the_order_they_were_made(self) -> None:
        encounter_id = await self._record(self._draft())
        team_of = dict(
            await self._rows("SELECT slot, id FROM encounter.team WHERE encounter_id = :id", id=encounter_id)
        )
        room = await self._hero_room(encounter_id, MapVetoSessionStatus.COMPLETED)
        async with self.Session() as s:
            # The candidates go in in pool order; slot 1 bans the last of them first, slot 2 the first one after.
            for item_id, slot, action_index in ((40, 2, 1), (41, None, None), (42, 1, 0)):
                s.add(
                    models.PickBanEntry(
                        session_id=room,
                        encounter_id=encounter_id,
                        item_id=item_id,
                        status=MapPoolEntryStatus.AVAILABLE if slot is None else MapPoolEntryStatus.BANNED,
                        action_index=action_index,
                        picked_by_kind=None if slot is None else PickBanActorKind.TEAM,
                        picked_by_team_id=None if slot is None else team_of[slot],
                    )
                )
                await s.flush()
            await s.commit()

        async with self.Session() as s:
            [played] = await custom._dump_rounds(s, list(await self.rounds.list_for_custom_game(s, self.cg.id)))

        self.assertEqual([{"slot": 1, "item_id": 42}, {"slot": 2, "item_id": 40}], played["bans"])

    async def test_the_history_lists_whose_hero_each_pick_was(self) -> None:
        encounter_id = await self._record(self._draft())
        seats = await self._rows(
            "SELECT tm.id, tm.workspace_member_id, tm.display_name_snapshot, et.slot, et.id"
            " FROM encounter.team_member tm JOIN encounter.team et ON et.id = tm.encounter_team_id"
            " WHERE tm.encounter_id = :id ORDER BY et.slot, tm.id",
            id=encounter_id,
        )
        room = await self._hero_room(encounter_id, MapVetoSessionStatus.COMPLETED)
        async with self.Session() as s:
            for index, (seat_id, _member, _name, _slot, team_id) in enumerate(seats):
                s.add(
                    models.PickBanEntry(
                        session_id=room,
                        encounter_id=encounter_id,
                        item_id=50 + index,
                        status=MapPoolEntryStatus.PICKED,
                        action_index=index,
                        picked_by_kind=PickBanActorKind.TEAM,
                        picked_by_team_id=team_id,
                        picked_for_member_id=seat_id,
                    )
                )
            await s.commit()

        async with self.Session() as s:
            [played] = await custom._dump_rounds(s, list(await self.rounds.list_for_custom_game(s, self.cg.id)))

        self.assertEqual(
            [
                {"slot": slot, "member_id": member, "name": name, "item_id": 50 + index}
                for index, (_seat, member, name, slot, _team) in enumerate(seats)
            ],
            played["picks"],
        )

    async def test_a_side_picked_game_keeps_its_sides_and_takes_its_score(self) -> None:
        match, result = self._draft()
        async with self.Session() as s:
            encounter = await start_mix_match(s, match)
            [game_id] = await s.scalars(
                sa.select(models.EncounterGame.id).where(models.EncounterGame.encounter_id == encounter.id)
            )
            teams = await s.scalars(
                sa.select(models.EncounterTeam.id)
                .where(models.EncounterTeam.encounter_id == encounter.id)
                .order_by(models.EncounterTeam.slot)
            )
            # A LoL room's side pick writes the game's lines before the result does.
            for team_id, side in zip(teams.all(), ("red", "blue"), strict=True):
                s.add(
                    models.EncounterGameTeam(
                        game_id=game_id, encounter_id=encounter.id, encounter_team_id=team_id, starting_side=side
                    )
                )
            await s.flush()
            await record_mix_result(s, MixResultDraft(encounter_id=encounter.id, **result))
            await s.commit()

        rows = await self._rows(
            "SELECT et.slot, gt.starting_side, gt.score FROM encounter.game_team gt"
            " JOIN encounter.team et ON et.id = gt.encounter_team_id WHERE gt.encounter_id = :id ORDER BY et.slot",
            id=encounter.id,
        )
        self.assertEqual([(1, "red", 1), (2, "blue", 0)], [tuple(row) for row in rows])
