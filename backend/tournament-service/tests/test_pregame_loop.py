"""End-to-end proof of the pre-game loop, one map of the series at a time:

    map veto (this round's map) -> hero bans (for that map) -> the map is
    played and both captains report it -> that result opens the next map

The unit suites (``test_pick_ban_session.py``, ``test_pick_ban_action.py``)
each pin one function's behavior against a canned answer. This one runs the
real service functions -- ``get_pick_ban_state``, ``perform_pick_ban_action``,
``submit_map_report``, ``sync_hero_rounds`` -- against an in-memory store that
actually holds rows, so the loop has to CYCLE rather than merely be plausible
step by step. It is the regression net for the property the room is built on:
round N+1's bans cannot be taken before map N has been played and confirmed.

The store below is a fake ``AsyncSession``, not a database: it interprets the
handful of query shapes these services issue by walking the SQLAlchemy
expression tree (never by string-matching SQL). Everything it does not know
about -- the seed-resolution lookups (``StageItemInput``/``Stage``/
``Standing``) -- answers empty, which is exactly the "no bracket seeds" path
(``decide_seeds`` -> home acts first).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

import sqlalchemy as sa

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


from shared.core.enums import (  # noqa: E402
    FirstBanRotation,
    MapPickSide,
    MapPoolEntryStatus,
    MapVetoMode,
    PickBanKind,
    PickBanNoRepeatScope,
)
from shared.core.errors import BaseAPIException as HTTPException  # noqa: E402
from shared.models.matches.match import Match  # noqa: E402
from shared.models.tournament.encounter import Encounter  # noqa: E402
from shared.models.tournament.encounter_report import EncounterMapReport  # noqa: E402
from shared.models.tournament.pick_ban import (  # noqa: E402
    EncounterPickBanLedger,
    EncounterReadiness,
    PickBanConfig,
    PickBanConfigItem,
    PickBanConfigSlot,
    PickBanConfigSlotItem,
    PickBanEntry,
    PickBanSession,
)
from src.services.encounter import map_report as map_report_module  # noqa: E402
from src.services.encounter.map_report import map_report_service  # noqa: E402
from src.services.encounter.pick_ban_action import pick_ban_action_service  # noqa: E402
from src.services.encounter.pick_ban_session import (  # noqa: E402
    REASON_WAITING_MAP,
    pick_ban_session_service,
)


def staged_topics(session: Any) -> list[str]:
    """The realtime topics ``emit`` staged on this session, in call order.

    The topic is the whole contract for a pick-ban signal: it names the room
    that must refetch, and the payload adds nothing a subscriber branches on.
    """
    staged = session.info.get("realtime_staged")
    if staged is None:
        return []
    return [scope.domain_topic(data.domain) for scope, data, _actor in staged.domain]


# ── the store ────────────────────────────────────────────────────────────────


def _bound_value(clause: Any) -> Any:
    """The right-hand literal of a comparison, unwrapped from its bind."""
    right = clause.right
    value = getattr(right, "value", right)
    # `col.in_([...])` binds one expanding parameter whose value is the list.
    return value


def _matches(row: Any, clause: Any) -> bool:
    """Whether `row` satisfies `clause`, an ORM WHERE expression.

    Handles the shapes these services build: ``AND`` of comparisons (``=``,
    ``!=``, ``IN``, ``IS NULL``). An ``OR`` is treated as satisfied -- the only
    one here is ``_resolve_config``'s "tournament-wide or this stage" cascade,
    and the fixtures below store exactly one config per kind, so narrowing it
    would only re-implement the cascade this test is not about.
    """
    if clause is None:
        return True
    if isinstance(clause, sa.sql.elements.BooleanClauseList):
        if clause.operator is sa.sql.operators.and_:
            return all(_matches(row, part) for part in clause.clauses)
        return True  # OR — see docstring
    if not isinstance(clause, sa.sql.elements.BinaryExpression):
        return True
    name = getattr(clause.left, "key", None)
    if name is None:
        return True
    actual = getattr(row, name, None)
    operator = clause.operator.__name__
    expected = _bound_value(clause)
    if operator == "eq":
        return actual == expected
    if operator == "ne":
        return actual != expected
    if operator == "in_op":
        return any(actual == candidate for candidate in expected)
    if operator == "is_":
        return actual is None if expected is None else actual == expected
    if operator in ("is_not", "isnot"):
        return actual is not None if expected is None else actual != expected
    raise AssertionError(f"unsupported operator in fake store: {operator}")


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def unique(self) -> _Result:
        # `shared.repository` reads go through `result.unique().scalars()`, so the
        # store has to answer it -- a no-op here (no joined eager loads).
        return self

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[Any]:
        return list(self._rows)

    def first(self) -> Any:
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None


class _Store:
    """In-memory stand-in for ``AsyncSession`` over the pick-ban tables."""

    def __init__(self) -> None:
        self.rows: dict[type, list[Any]] = {}
        self.info: dict[Any, Any] = {}
        self._next_id = 1

    # -- seeding / bookkeeping --------------------------------------------
    def seed(self, *instances: Any) -> None:
        for instance in instances:
            self.add(instance)
        self._assign_ids()

    def all_of(self, model: type) -> list[Any]:
        return list(self.rows.get(model, []))

    def add(self, instance: Any) -> None:
        self.rows.setdefault(type(instance), []).append(instance)

    def _assign_ids(self) -> None:
        for model, rows in self.rows.items():
            for row in rows:
                if getattr(row, "id", None) is None:
                    row.id = self._next_id
                    self._next_id += 1
                # A real flush resolves a relationship-only insert into its FK;
                # every query here filters on the FK column.
                owner = getattr(row, "session", None)
                if model is PickBanEntry and getattr(row, "session_id", None) is None and owner is not None:
                    row.session_id = owner.id

    async def flush(self) -> None:
        self._assign_ids()

    async def commit(self) -> None:
        self._assign_ids()

    async def rollback(self) -> None:  # pragma: no cover - nothing raises here
        return None

    async def refresh(self, instance: Any) -> None:
        return None

    async def get(self, model: type, pk: Any) -> Any:
        return next((row for row in self.rows.get(model, []) if getattr(row, "id", None) == pk), None)

    # -- querying ---------------------------------------------------------
    def _entity(self, statement: Any) -> Any:
        return statement.column_descriptions[0]["entity"]

    def _select_rows(self, statement: Any) -> list[Any]:
        entity = self._entity(statement)
        rows = [row for row in self.rows.get(entity, []) if _matches(row, statement.whereclause)]
        descriptions = statement.column_descriptions
        if len(descriptions) == 1 and descriptions[0]["expr"] is entity:
            return rows
        columns = [description["name"] for description in descriptions]
        if len(columns) == 1:
            return [getattr(row, columns[0]) for row in rows]
        return [tuple(getattr(row, column) for column in columns) for row in rows]

    async def execute(self, statement: Any) -> _Result:
        if isinstance(statement, sa.sql.dml.Delete):
            model = next(
                (model for model in self.rows if model.__tablename__ == statement.table.name),
                None,
            )
            if model is not None:
                self.rows[model] = [row for row in self.rows[model] if not _matches(row, statement.whereclause)]
            return _Result([])
        entity = self._entity(statement)
        if (
            entity is not None
            and entity not in self.rows
            and entity
            not in (
                PickBanSession,
                PickBanEntry,
                PickBanConfig,
                EncounterReadiness,
                EncounterPickBanLedger,
                EncounterMapReport,
                Match,
                Encounter,
            )
        ):
            # Seed resolution's bracket/standings lookups: nothing stored, which
            # is the "no seeds, home acts first" path.
            return _Result([])
        return _Result(self._select_rows(statement))

    async def scalar(self, statement: Any) -> Any:
        # `select(func.count()).select_from(X).where(...)` — the only aggregate
        # these services issue.
        if statement.column_descriptions[0]["entity"] is None:
            froms = statement.get_final_froms()
            model = next((model for model in self.rows if model.__tablename__ == froms[0].name), None)
            if model is None:
                return 0
            return sum(1 for row in self.rows[model] if _matches(row, statement.whereclause))
        rows = self._select_rows(statement)
        return rows[0] if rows else None


# ── fixtures ─────────────────────────────────────────────────────────────────

MAP_SLOTS = [[11, 12, 13], [21, 22, 23], [31, 32, 33]]
# Wide enough for three rounds of four bans with nothing re-banned (12 heroes)
# and slack on top, the way a real hero pool is.
HEROES = list(range(101, 117))
HOME_TEAM, AWAY_TEAM = 10, 20


def _map_config() -> PickBanConfig:
    config = PickBanConfig(
        tournament_id=7,
        kind=PickBanKind.MAP,
        stage_id=None,
        round=None,
        mode=MapVetoMode.SLOTS,
        first_ban_rotation=FirstBanRotation.RESULT_WINNER_FIRST,
        preset="bracket",
        sequence_json=[],
        turn_timer_seconds=None,
        no_repeat_scope=PickBanNoRepeatScope.NONE,
        unique_attribute_per_side_per_round=None,
        allow_protect=False,
    )
    config.items = []
    config.slots = [
        PickBanConfigSlot(position=position, reserve_item_id=None) for position, _ in enumerate(MAP_SLOTS, start=1)
    ]
    for slot, item_ids in zip(config.slots, MAP_SLOTS, strict=True):
        slot.items = [PickBanConfigSlotItem(item_id=item_id) for item_id in item_ids]
    return config


def _hero_config() -> PickBanConfig:
    config = PickBanConfig(
        tournament_id=7,
        kind=PickBanKind.HERO,
        stage_id=None,
        round=None,
        mode=MapVetoMode.POOL,
        first_ban_rotation=FirstBanRotation.FIXED,
        preset="custom",
        # Two bans per side, per map of the series.
        sequence_json=["ban_first", "ban_second", "ban_second", "ban_first"],
        turn_timer_seconds=None,
        # Doc 1's rule: nobody re-bans a hero anywhere in the series.
        no_repeat_scope=PickBanNoRepeatScope.ENCOUNTER,
        unique_attribute_per_side_per_round=None,
        allow_protect=False,
    )
    config.slots = []
    config.items = [PickBanConfigItem(item_id=item_id, sort_order=index) for index, item_id in enumerate(HEROES)]
    return config


def _encounter() -> Encounter:
    encounter = Encounter(
        tournament_id=7,
        stage_id=None,
        stage_item_id=None,
        round=1,
        best_of=3,
        home_team_id=HOME_TEAM,
        away_team_id=AWAY_TEAM,
        home_score=0,
        away_score=0,
    )
    return encounter


class PregameLoopTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.store = _Store()
        self.map_config = _map_config()
        self.hero_config = _hero_config()
        self.encounter = _encounter()
        self.store.seed(
            self.encounter,
            self.map_config,
            self.hero_config,
            EncounterReadiness(encounter_id=1, side=MapPickSide.HOME.value, ready_user_id=None),
            EncounterReadiness(encounter_id=1, side=MapPickSide.AWAY.value, ready_user_id=None),
        )
        # Ids are assigned in seed order; the encounter is first.
        self.encounter_id = self.encounter.id
        for readiness in self.store.all_of(EncounterReadiness):
            readiness.encounter_id = self.encounter_id

    # -- helpers ----------------------------------------------------------
    async def map_state(self) -> dict:
        return await pick_ban_action_service.get_pick_ban_state(
            self.store, self.encounter_id, PickBanKind.MAP, viewer_side=MapPickSide.HOME.value
        )

    async def hero_state(self) -> dict:
        return await pick_ban_action_service.get_pick_ban_state(
            self.store, self.encounter_id, PickBanKind.HERO, viewer_side=MapPickSide.HOME.value
        )

    async def act(self, kind: PickBanKind, side: str, item_id: int, action: str = "ban") -> None:
        await pick_ban_action_service.perform_pick_ban_action(
            self.store, self.encounter_id, kind, side, item_id, action
        )

    async def ban_out_the_map_round(self) -> int:
        """Both sides ban this round's first two candidates; the decider takes
        the survivor. Returns the map the round settled on."""
        state = await self.map_state()
        available = [
            entry["item_id"] for entry in state["pool"] if entry["status"] == MapPoolEntryStatus.AVAILABLE.value
        ]
        self.assertEqual(3, len(available), "a map round offers its slot's three candidates")
        await self.act(PickBanKind.MAP, state["turn_side"], available[0])
        state = await self.map_state()
        await self.act(PickBanKind.MAP, state["turn_side"], available[1])
        state = await self.map_state()
        self.assertTrue(state["is_complete"], "the decider closes the round as soon as one candidate is left")
        return available[2]

    async def ban_out_the_hero_round(self) -> list[int]:
        """The round's four bans, two per side. Returns the heroes banned."""
        banned: list[int] = []
        for _ in range(4):
            state = await self.hero_state()
            self.assertFalse(state["is_complete"])
            available = [
                entry["item_id"]
                for entry in state["pool"]
                if entry["status"] == MapPoolEntryStatus.AVAILABLE.value and entry["round"] == state["current_round"]
            ]
            await self.act(PickBanKind.HERO, state["turn_side"], available[0])
            banned.append(available[0])
        self.assertTrue((await self.hero_state())["is_complete"])
        return banned

    async def report(self, map_id: int, home_score: int, away_score: int) -> dict:
        for team_id in (HOME_TEAM, AWAY_TEAM):
            result = await map_report_service.submit_map_report(
                self.store,
                self.encounter,
                map_id=map_id,
                team_id=team_id,
                reporter_user_id=None,
                home_score=home_score,
                away_score=away_score,
            )
        return result

    # -- the loop ---------------------------------------------------------
    async def test_a_bo3_runs_map_then_heroes_then_the_result_each_round(self) -> None:
        # ── round 1 ──────────────────────────────────────────────────────
        state = await self.map_state()
        self.assertEqual(["ban_home", "ban_away", "decider"], state["sequence"])
        self.assertEqual(3, len(state["pool"]), "only round 1 exists yet")

        # Heroes are banned FOR a map, so the hero phase is closed until this
        # round's map is picked.
        hero = await self.hero_state()
        self.assertIsNone(hero["session"])
        self.assertEqual(REASON_WAITING_MAP, hero["reason"])

        map_one = await self.ban_out_the_map_round()

        # Round 2's bans are NOT available: nothing is left to act on until the
        # result of map 1 lifts the barrier.
        state = await self.map_state()
        self.assertEqual(
            [], [entry for entry in state["pool"] if entry["status"] == MapPoolEntryStatus.AVAILABLE.value]
        )
        self.assertTrue(state["is_complete"])

        round_one_heroes = await self.ban_out_the_hero_round()

        # The map's result is the third phase, and what opens the next map.
        state = await self.map_state()
        self.assertEqual([], state["map_reports"])
        result = await self.report(map_one, 2, 1)
        self.assertEqual({"disputed": False, "resolved": True, "match_id": result["match_id"]}, result)
        self.assertEqual((1, 0), (self.encounter.home_score, self.encounter.away_score))

        # ── round 2 ──────────────────────────────────────────────────────
        state = await self.map_state()
        self.assertFalse(state["is_complete"], "map 1's result opened map 2's bans")
        self.assertEqual(2, state["current_round"])
        # `result_winner_first`: home won map 1, so home opens map 2's bans.
        self.assertEqual(MapPickSide.HOME.value, state["turn_side"])
        # Round 1 keeps its two bans and its decider, now flipped to `played`.
        self.assertEqual(
            {MapPoolEntryStatus.BANNED.value, MapPoolEntryStatus.PLAYED.value},
            {entry["status"] for entry in state["pool"] if entry["round"] == 1},
        )

        map_two = await self.ban_out_the_map_round()
        round_two_heroes = await self.ban_out_the_hero_round()
        # No hero is re-banned anywhere in the series (`no_repeat_scope=encounter`).
        self.assertEqual(set(), set(round_one_heroes) & set(round_two_heroes))
        await self.report(map_two, 1, 2)
        self.assertEqual((1, 1), (self.encounter.home_score, self.encounter.away_score))

        # ── round 3 ──────────────────────────────────────────────────────
        state = await self.map_state()
        self.assertEqual(3, state["current_round"])
        # Away won map 2, so away opens map 3's bans.
        self.assertEqual(MapPickSide.AWAY.value, state["turn_side"])

        map_three = await self.ban_out_the_map_round()
        round_three_heroes = await self.ban_out_the_hero_round()
        self.assertEqual(
            12,
            len({*round_one_heroes, *round_two_heroes, *round_three_heroes}),
            "three rounds of two bans per side, none repeated",
        )
        await self.report(map_three, 2, 0)
        self.assertEqual((2, 1), (self.encounter.home_score, self.encounter.away_score))

        # ── the series is over ───────────────────────────────────────────
        state = await self.map_state()
        self.assertTrue(state["is_complete"])
        self.assertEqual({1, 2, 3}, {entry["round"] for entry in state["pool"]}, "no fourth map round was ever opened")
        self.assertEqual(
            {MapPoolEntryStatus.PLAYED.value},
            {entry["status"] for entry in state["pool"] if entry["picked_by"] == MapPickSide.DECIDER.value},
        )
        hero = await self.hero_state()
        self.assertTrue(hero["is_complete"])
        self.assertEqual({1, 2, 3}, {entry["round"] for entry in hero["pool"]})
        # Each closed hero round keeps its four bans and drops the candidates
        # nobody touched, so the round in play is never mistaken for an old one.
        for round_number in (1, 2):
            self.assertEqual(4, len([entry for entry in hero["pool"] if entry["round"] == round_number]))

    async def test_a_disputed_result_holds_the_next_map_closed(self) -> None:
        map_one = await self.ban_out_the_map_round()
        await self.ban_out_the_hero_round()

        await map_report_service.submit_map_report(
            self.store,
            self.encounter,
            map_id=map_one,
            team_id=HOME_TEAM,
            reporter_user_id=None,
            home_score=2,
            away_score=1,
        )
        disputed = await map_report_service.submit_map_report(
            self.store,
            self.encounter,
            map_id=map_one,
            team_id=AWAY_TEAM,
            reporter_user_id=None,
            home_score=0,
            away_score=2,
        )

        self.assertTrue(disputed["disputed"])
        state = await self.map_state()
        self.assertTrue(state["is_complete"], "a disputed map opens nothing")
        self.assertEqual({1}, {entry["round"] for entry in state["pool"]})
        self.assertEqual((0, 0), (self.encounter.home_score, self.encounter.away_score))
        # Both claims are on the state so the room can say WHY it is waiting.
        self.assertEqual(
            [{MapPickSide.HOME.value, 2, 1}, {MapPickSide.AWAY.value, 0, 2}],
            [{report["side"], report["home_score"], report["away_score"]} for report in state["map_reports"]],
        )

    async def test_a_decided_series_stops_opening_rounds(self) -> None:
        # 2-0 in a Bo3: map 3 is never played, so it never gets a pick-ban round.
        map_one = await self.ban_out_the_map_round()
        await self.ban_out_the_hero_round()
        await self.report(map_one, 2, 0)

        map_two = await self.ban_out_the_map_round()
        await self.ban_out_the_hero_round()
        await self.report(map_two, 2, 1)

        self.assertEqual((2, 0), (self.encounter.home_score, self.encounter.away_score))
        state = await self.map_state()
        self.assertTrue(state["is_complete"])
        self.assertEqual({1, 2}, {entry["round"] for entry in state["pool"]})
        hero = await self.hero_state()
        self.assertEqual({1, 2}, {entry["round"] for entry in hero["pool"]})

    async def test_amending_an_already_agreed_report_corrects_it_without_recounting(self) -> None:
        map_one = await self.ban_out_the_map_round()
        await self.ban_out_the_hero_round()
        await self.report(map_one, 2, 1)
        self.assertEqual((1, 0), (self.encounter.home_score, self.encounter.away_score))

        # Both captains agree again on a corrected score. The map is already
        # `played`: its result may change, but the series score counts it once.
        await self.report(map_one, 1, 2)

        self.assertEqual((1, 0), (self.encounter.home_score, self.encounter.away_score))
        match = self.store.all_of(Match)[0]
        self.assertEqual((1, 2), (match.home_score, match.away_score))

    async def test_a_map_played_twice_keeps_the_two_plays_apart(self) -> None:
        # A slot config may list the same map in two rounds, and with
        # `no_repeat_scope=none` nothing stops the series from playing it twice.
        # Both per-map tables used to key a played map on `map_id` alone, so the
        # second play read back the first play's claims (already filed, already
        # agreed), flipped the FIRST play's entry to `played` again -- opening no
        # round and stalling the series -- and overwrote the first play's score.
        # Slot 3's decider is slot 1's decider: `ban_out_the_map_round` bans the
        # first two candidates, so both rounds settle on 13.
        self.map_config.slots[2].items = [PickBanConfigSlotItem(item_id=item_id) for item_id in (31, 32, 13)]

        first_play = await self.ban_out_the_map_round()
        await self.ban_out_the_hero_round()
        await self.report(first_play, 2, 1)

        map_two = await self.ban_out_the_map_round()
        await self.ban_out_the_hero_round()
        await self.report(map_two, 1, 2)

        third_play = await self.ban_out_the_map_round()
        self.assertEqual(first_play, third_play, "the fixture plays map 13 twice")
        await self.ban_out_the_hero_round()

        # The room tells the two plays apart by POSITION: map 13's round-1 claims
        # are on the state, and nothing is filed for position 3 yet.
        state = await self.map_state()
        thirteens = [report for report in state["map_reports"] if report["map_id"] == first_play]
        self.assertEqual([1, 1], sorted(report["map_index"] for report in thirteens))

        await self.report(third_play, 2, 0)

        # Two claims per side, one per play, and each play's own score.
        state = await self.map_state()
        thirteens = [report for report in state["map_reports"] if report["map_id"] == first_play]
        self.assertEqual([1, 1, 3, 3], sorted(report["map_index"] for report in thirteens))
        by_index = {
            match.map_index: (match.home_score, match.away_score)
            for match in self.store.all_of(Match)
            if match.map_id == first_play
        }
        self.assertEqual({1: (2, 1), 3: (2, 0)}, by_index)

        # Round 3's entry is the one that flipped, and the series counted three
        # maps rather than recounting the first.
        played_rounds = {
            entry["round"]
            for entry in state["pool"]
            if entry["item_id"] == first_play and entry["status"] == MapPoolEntryStatus.PLAYED.value
        }
        self.assertEqual({1, 3}, played_rounds)
        self.assertEqual((2, 1), (self.encounter.home_score, self.encounter.away_score))

    async def test_the_first_report_of_a_map_pushes_a_room_update(self) -> None:
        # The opponent's tile only flips from "not reported" to "sealed" on a
        # realtime signal: nothing else pushes it, and `submit_map_report`'s
        # return value reaches the captain who filed and nobody else. The
        # unresolved path used to commit silently, so the opponent had to reload.
        map_one = await self.ban_out_the_map_round()
        await self.ban_out_the_hero_round()
        self.store.info.pop("realtime_staged", None)

        result = await map_report_service.submit_map_report(
            self.store,
            self.encounter,
            map_id=map_one,
            team_id=HOME_TEAM,
            reporter_user_id=None,
            home_score=2,
            away_score=1,
        )

        self.assertFalse(result["resolved"], "one claim resolves nothing on its own")
        self.assertEqual(
            [f"encounter:{self.encounter_id}:map-veto", f"encounter:{self.encounter_id}:pick-ban:hero"],
            staged_topics(self.store),
        )


class LoserChoiceStallTests(IsolatedAsyncioTestCase):
    """``first_ban_rotation=result_loser_choice`` on the HERO config: the round
    after each map cannot open until a human names its opener.

    Standalone rather than a ``PregameLoopTests`` subclass on purpose — the
    suite above cycles a series unattended, which this rotation by definition
    cannot do.

    The regression: nothing but the losing captain's own modal ever surfaced
    the wait, and no override could resolve it. An unreachable captain left the
    room showing a finished round with nothing to click, and the only admin
    control on screen was a session-wiping reset — which re-creates round 1 and
    walks into the same wall one map later.
    """

    async def asyncSetUp(self) -> None:
        self.store = _Store()
        self.map_config = _map_config()
        self.hero_config = _hero_config()
        self.hero_config.first_ban_rotation = FirstBanRotation.RESULT_LOSER_CHOICE
        self.encounter = _encounter()
        self.store.seed(
            self.encounter,
            self.map_config,
            self.hero_config,
            EncounterReadiness(encounter_id=1, side=MapPickSide.HOME.value, ready_user_id=None),
            EncounterReadiness(encounter_id=1, side=MapPickSide.AWAY.value, ready_user_id=None),
        )
        self.encounter_id = self.encounter.id
        for readiness in self.store.all_of(EncounterReadiness):
            readiness.encounter_id = self.encounter_id

    async def state(self, kind: PickBanKind) -> dict:
        return await pick_ban_action_service.get_pick_ban_state(
            self.store, self.encounter_id, kind, viewer_side=MapPickSide.HOME.value
        )

    async def play_map_one(self) -> None:
        """Map 1 vetoed, its four hero bans taken, its result agreed (home wins),
        and map 2 vetoed — the loop's state one step before hero round 2."""
        for _ in range(2):
            state = await self.state(PickBanKind.MAP)
            available = [
                entry["item_id"] for entry in state["pool"] if entry["status"] == MapPoolEntryStatus.AVAILABLE.value
            ]
            await pick_ban_action_service.perform_pick_ban_action(
                self.store, self.encounter_id, PickBanKind.MAP, state["turn_side"], available[0], "ban"
            )
        map_one = next(
            entry.item_id
            for entry in self.store.all_of(PickBanEntry)
            if entry.status == MapPoolEntryStatus.PICKED.value
        )
        for _ in range(4):
            state = await self.state(PickBanKind.HERO)
            available = [
                entry["item_id"]
                for entry in state["pool"]
                if entry["status"] == MapPoolEntryStatus.AVAILABLE.value and entry["round"] == state["current_round"]
            ]
            await pick_ban_action_service.perform_pick_ban_action(
                self.store, self.encounter_id, PickBanKind.HERO, state["turn_side"], available[0], "ban"
            )
        for team_id in (HOME_TEAM, AWAY_TEAM):
            await map_report_service.submit_map_report(
                self.store,
                self.encounter,
                map_id=map_one,
                team_id=team_id,
                reporter_user_id=None,
                home_score=2,
                away_score=1,
            )
        for _ in range(2):
            state = await self.state(PickBanKind.MAP)
            available = [
                entry["item_id"]
                for entry in state["pool"]
                if entry["status"] == MapPoolEntryStatus.AVAILABLE.value and entry["round"] == state["current_round"]
            ]
            await pick_ban_action_service.perform_pick_ban_action(
                self.store, self.encounter_id, PickBanKind.MAP, state["turn_side"], available[0], "ban"
            )
        # The hero session catches up with the map phase on a READ
        # (`sync_hero_rounds`), which is where the choice gate is reached.
        await self.state(PickBanKind.HERO)

    def hero_session(self) -> PickBanSession:
        return next(pick_ban for pick_ban in self.store.all_of(PickBanSession) if pick_ban.kind == PickBanKind.HERO)

    def hero_rounds(self) -> set[int]:
        hero_id = self.hero_session().id
        return {entry.round for entry in self.store.all_of(PickBanEntry) if entry.session_id == hero_id}

    async def test_the_wait_is_on_the_state_for_every_viewer_not_just_the_loser(self) -> None:
        await self.play_map_one()

        hero = await self.state(PickBanKind.HERO)
        self.assertTrue(hero["is_complete"])
        self.assertEqual({1}, {entry["round"] for entry in hero["pool"]}, "round 2 waits on the choice")
        # Away lost map 1, so away chooses — and the room can say so to anybody,
        # including the admin looking at a session that is `completed`.
        self.assertTrue(hero["session"]["awaiting_choice"])
        self.assertEqual(MapPickSide.AWAY.value, hero["session"]["pending_loser_side"])

    async def test_the_winning_captain_may_not_elect(self) -> None:
        await self.play_map_one()

        with self.assertRaises(HTTPException) as caught:
            await pick_ban_session_service.elect_round_opener(
                self.store, self.hero_session(), first_side="home", acting_side=MapPickSide.HOME.value
            )
        self.assertEqual(403, caught.exception.status_code)
        self.assertEqual({1}, self.hero_rounds())

    async def test_an_admin_elects_for_an_unreachable_captain_and_the_round_opens(self) -> None:
        await self.play_map_one()

        await pick_ban_session_service.elect_round_opener(
            self.store, self.hero_session(), first_side=MapPickSide.AWAY.value, acting_side=None
        )

        hero = await self.state(PickBanKind.HERO)
        self.assertEqual(2, hero["current_round"])
        self.assertFalse(hero["is_complete"])
        self.assertEqual(MapPickSide.AWAY.value, hero["turn_side"], "the elected side opens the round")
        self.assertFalse(hero["session"]["awaiting_choice"])
        self.assertIsNone(hero["session"]["pending_loser_side"])

    async def test_electing_twice_is_refused_rather_than_appending_a_second_round(self) -> None:
        await self.play_map_one()
        await pick_ban_session_service.elect_round_opener(
            self.store, self.hero_session(), first_side=MapPickSide.AWAY.value, acting_side=None
        )

        with self.assertRaises(HTTPException) as caught:
            await pick_ban_session_service.elect_round_opener(
                self.store, self.hero_session(), first_side=MapPickSide.HOME.value, acting_side=None
            )
        self.assertEqual(400, caught.exception.status_code)
        self.assertEqual({1, 2}, self.hero_rounds())


class DeletedConfigStallTests(IsolatedAsyncioTestCase):
    """A progressive session whose config was deleted mid-series names the
    problem instead of declining in silence.

    ``PickBanSession.config_id`` is ``ondelete=SET NULL``, so the session
    survives its config and can never open another round. Returning quietly
    from ``advance_to_next_round`` left the room frozen on a finished round with
    no reason on screen and nothing in the logs.
    """

    async def asyncSetUp(self) -> None:
        self.store = _Store()
        self.encounter = _encounter()
        self.store.seed(
            self.encounter,
            _map_config(),
            _hero_config(),
            EncounterReadiness(encounter_id=1, side=MapPickSide.HOME.value, ready_user_id=None),
            EncounterReadiness(encounter_id=1, side=MapPickSide.AWAY.value, ready_user_id=None),
        )
        self.encounter_id = self.encounter.id
        for readiness in self.store.all_of(EncounterReadiness):
            readiness.encounter_id = self.encounter_id

    async def test_it_says_the_config_is_gone(self) -> None:
        state = await pick_ban_action_service.get_pick_ban_state(
            self.store, self.encounter_id, PickBanKind.MAP, viewer_side=MapPickSide.HOME.value
        )
        pick_ban = next(row for row in self.store.all_of(PickBanSession) if row.kind == PickBanKind.MAP)
        available = [
            entry["item_id"] for entry in state["pool"] if entry["status"] == MapPoolEntryStatus.AVAILABLE.value
        ]
        for item_id in available[:2]:
            state = await pick_ban_action_service.get_pick_ban_state(
                self.store, self.encounter_id, PickBanKind.MAP, viewer_side=MapPickSide.HOME.value
            )
            await pick_ban_action_service.perform_pick_ban_action(
                self.store, self.encounter_id, PickBanKind.MAP, state["turn_side"], item_id, "ban"
            )
        pick_ban.config_id = None

        with self.assertRaises(HTTPException) as caught:
            await pick_ban_session_service.advance_to_next_round(
                self.store, pick_ban, completed_round=1, winner=MapPickSide.HOME.value
            )
        self.assertEqual(422, caught.exception.status_code)
        self.assertIn("no longer", str(caught.exception.detail))


class ScrimLoopTests(PregameLoopTests):
    """The same loop for a scrim room: it must CYCLE identically while writing no
    ``matches.match`` row.

    A scrim's per-map score exists to run the series, not to record it — it is
    what names the next map's opener under a result-dependent rotation, which
    both real rulebooks use. Everything the progression needs still has to
    happen; only the bookkeeping goes.

    Inherits the whole suite deliberately: every loop assertion above is re-run
    with the scrim predicate on, so a divergence in the progression itself shows
    up here rather than only in the one case below. ``is_scrim_container`` is
    patched rather than seeded — the predicate has its own tests
    (``test_scrim_recalculation_exclusion.py``); what is under test here is what
    ``submit_map_report`` does once it answers True.
    """

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        patcher = patch.object(map_report_module, "is_scrim_container", AsyncMock(return_value=True))
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_a_bo3_cycles_without_writing_a_single_match_row(self) -> None:
        for round_number in (1, 2):
            played_map = await self.ban_out_the_map_round()
            await self.ban_out_the_hero_round()
            result = await self.report(played_map, 2, 1)

            self.assertTrue(result["resolved"], f"round {round_number} did not reconcile")
            # The one difference from a tournament: nothing to point at.
            self.assertIsNone(result["match_id"])
            self.assertEqual([], self.store.all_of(Match), "a scrim wrote a match row")

        # And the progression the score drives is intact: home won both maps, so
        # the series is decided and the loop stopped opening rounds.
        self.assertEqual((2, 0), (self.encounter.home_score, self.encounter.away_score))
        state = await self.map_state()
        self.assertTrue(state["is_complete"])
        self.assertEqual(
            [MapPoolEntryStatus.PLAYED.value] * 2,
            [entry["status"] for entry in state["pool"] if entry["picked_by"] == MapPickSide.DECIDER.value],
            "both settled maps must still flip to played — that is what advances the series",
        )

    async def test_the_winner_still_opens_the_next_round(self) -> None:
        """The reason the score is kept at all. ``result_winner_first``: away wins
        map 1, so away opens map 2's bans — which is impossible to resolve from a
        scoreless "map done" click."""
        map_one = await self.ban_out_the_map_round()
        await self.ban_out_the_hero_round()
        await self.report(map_one, 1, 2)

        state = await self.map_state()
        self.assertEqual(2, state["current_round"])
        self.assertEqual(MapPickSide.AWAY.value, state["turn_side"])

    # -- overrides: the two inherited cases whose assertions ARE about the row a
    #    scrim does not write. Re-stated so the behaviour they defend is still
    #    covered here, minus the row.

    async def test_amending_an_already_agreed_report_corrects_it_without_recounting(self) -> None:
        map_one = await self.ban_out_the_map_round()
        await self.ban_out_the_hero_round()
        await self.report(map_one, 2, 1)
        self.assertEqual((1, 0), (self.encounter.home_score, self.encounter.away_score))

        await self.report(map_one, 1, 2)

        # Counted once, exactly as for a tournament; the corrected score lives on
        # the captains' own claims instead of on a match row.
        self.assertEqual((1, 0), (self.encounter.home_score, self.encounter.away_score))
        self.assertEqual([], self.store.all_of(Match))
        state = await self.map_state()
        self.assertEqual(
            [(1, 2), (1, 2)],
            [(report["home_score"], report["away_score"]) for report in state["map_reports"]],
        )

    async def test_a_map_played_twice_keeps_the_two_plays_apart(self) -> None:
        self.map_config.slots[2].items = [PickBanConfigSlotItem(item_id=item_id) for item_id in (31, 32, 13)]

        first_play = await self.ban_out_the_map_round()
        await self.ban_out_the_hero_round()
        await self.report(first_play, 2, 1)

        map_two = await self.ban_out_the_map_round()
        await self.ban_out_the_hero_round()
        await self.report(map_two, 1, 2)

        third_play = await self.ban_out_the_map_round()
        self.assertEqual(first_play, third_play, "the fixture plays map 13 twice")
        await self.ban_out_the_hero_round()
        await self.report(third_play, 2, 0)

        # The two plays are still told apart by POSITION -- the property this test
        # exists for -- and that is carried by the claims, not by the match row.
        state = await self.map_state()
        thirteens = [report for report in state["map_reports"] if report["map_id"] == first_play]
        self.assertEqual([1, 1, 3, 3], sorted(report["map_index"] for report in thirteens))
        self.assertEqual([], self.store.all_of(Match))

        played_rounds = {
            entry["round"]
            for entry in state["pool"]
            if entry["item_id"] == first_play and entry["status"] == MapPoolEntryStatus.PLAYED.value
        }
        self.assertEqual({1, 3}, played_rounds)
        self.assertEqual((2, 1), (self.encounter.home_score, self.encounter.away_score))
