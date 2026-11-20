"""Bracket slot swaps exchange the teams two seats hold, rebuild both names, and
refuse a settled or live encounter.

The swap is seeding surgery: it rewires the seats the reports, pick-ban
sessions and standings all key off. Anything past seeding (completed, disputed,
or a series already running) must be sent to the reopen endpoint instead of
being re-teamed underneath its result.

A seat does not change hands in place -- the occupant is retired and a new
participation written (D55) -- so these run against the real participation
writer on the test Postgres.
"""

from __future__ import annotations

import importlib
import itertools
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

import sqlalchemy as sa

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


from shared.models.encounter import Encounter, EncounterTeam  # noqa: E402
from shared.models.tournament.encounter_link import EncounterLink  # noqa: E402
from shared.models.tournament.stage import Stage, StageItem  # noqa: E402
from tests._encounter_layer import EncounterLayerCase  # noqa: E402
from tests._rpc_fakes import CapturingBroker, FakeSessionMaker, make_identity  # noqa: E402

enc_service = importlib.import_module("src.services.admin.encounter")
schemas = importlib.import_module("src.schemas")
enums = importlib.import_module("shared.core.enums")
admin_misc = importlib.import_module("src.rpc.admin_misc")
helpers = importlib.import_module("src.rpc._helpers")

_TAG = itertools.count()


@contextmanager
def assert_http_status(test_case: IsolatedAsyncioTestCase, expected_status: int):
    try:
        yield
    except Exception as exc:  # noqa: BLE001 - inspect status_code attribute
        test_case.assertEqual(getattr(exc, "status_code", None), expected_status)
        return
    test_case.fail(f"expected an exception with status_code {expected_status}")


def _body(slot: int, target_id: int, target_slot: int):
    return schemas.EncounterSwapSlotInput(slot=slot, target_encounter_id=target_id, target_slot=target_slot)


class SwapSlotCase(EncounterLayerCase):
    async def swap(self, encounter_id: int, slot: int, target_id: int, target_slot: int):
        async with self.Session() as s:
            return await enc_service.encounter_service.swap_slots(s, encounter_id, _body(slot, target_id, target_slot))


class SwapSlots(SwapSlotCase):
    async def test_rpc_swaps_teams_in_an_unpublished_stage(self) -> None:
        source = await self.encounter(0, 1)
        target = await self.encounter(2, 3)
        broker = CapturingBroker()
        admin_misc.register(broker, SimpleNamespace(exception=lambda *a, **k: None))
        identity = make_identity(
            workspaces=[
                {
                    "workspace_id": self.workspace_id,
                    "rbac_roles": [],
                    "rbac_permissions": [{"resource": "match", "action": "update"}],
                }
            ]
        )
        async with self.Session() as session:
            with patch.object(helpers.db, "async_session_maker", FakeSessionMaker(session)):
                envelope = await broker.handlers["rpc.tournament.encounter_swap_slot"](
                    {"identity": identity, "id": source, "payload": _body(1, target, 1).model_dump()},
                    None,
                )

        self.assertTrue(envelope["ok"], envelope)
        data = envelope["data"]
        self.assertEqual(
            (source, [(1, self.teams[2]), (2, self.teams[1])], "t2 vs t1"),
            (
                data["source"]["id"],
                [(seat["slot"], seat["team_id"]) for seat in data["source"]["teams"]],
                data["source"]["name"],
            ),
        )
        self.assertEqual(
            (target, [(1, self.teams[0]), (2, self.teams[3])], "t0 vs t3"),
            (
                data["target"]["id"],
                [(seat["slot"], seat["team_id"]) for seat in data["target"]["teams"]],
                data["target"]["name"],
            ),
        )
        async with self.Session() as s:
            self.assertFalse((await s.get_one(Stage, self.stage_id)).is_published)

    async def test_swaps_between_two_open_encounters(self) -> None:
        source = await self.encounter(0, 1)
        target = await self.encounter(2, None)

        returned_source, returned_target = await self.swap(source, 1, target, 2)

        self.assertEqual([(2, "t1")], await self.seats(source))
        self.assertEqual([(1, "t2"), (2, "t0")], await self.seats(target))
        async with self.Session() as s:
            self.assertEqual("TBD vs t1", (await s.get_one(Encounter, source)).name)
            self.assertEqual("t2 vs t0", (await s.get_one(Encounter, target)).name)
        self.assertEqual((source, target), (returned_source.id, returned_target.id))

    async def test_the_moved_team_is_a_new_participation_and_the_old_one_is_kept(self) -> None:
        """Append-only (D55): the seat the team left stays, inactive, with its history."""
        source = await self.encounter(0, 1)
        target = await self.encounter(2, None)

        await self.swap(source, 1, target, 2)

        async with self.Session() as s:
            rows = (
                await s.execute(
                    sa.select(EncounterTeam.encounter_id, EncounterTeam.slot, EncounterTeam.name, EncounterTeam.active)
                    .where(EncounterTeam.encounter_id.in_([source, target]))
                    .order_by(EncounterTeam.encounter_id, EncounterTeam.slot, EncounterTeam.id)
                )
            ).all()
        self.assertEqual(
            [
                (source, 1, "t0", False),
                (source, 2, "t1", True),
                (target, 1, "t2", True),
                (target, 2, "t0", True),
            ],
            [tuple(row) for row in rows],
        )

    async def test_exchanges_two_seats_within_one_encounter(self) -> None:
        encounter = await self.encounter(0, 1)

        returned_source, returned_target = await self.swap(encounter, 1, encounter, 2)

        self.assertEqual([(1, "t1"), (2, "t0")], await self.seats(encounter))
        async with self.Session() as s:
            self.assertEqual("t1 vs t0", (await s.get_one(Encounter, encounter)).name)
        self.assertEqual(returned_source.id, returned_target.id)

    async def test_bronze_origins_stay_on_the_bronze_card(self) -> None:
        semis = [await self.encounter(0, 3), await self.encounter(1, 2)]
        bronze = await self.encounter(3, 2, round_number=2)
        final = await self.encounter(0, 1, round_number=2)
        async with self.Session() as s:
            s.add_all(
                EncounterLink(
                    tournament_id=self.tournament_id,
                    source_encounter_id=semi,
                    source_position=place,
                    target_encounter_id=target,
                    target_slot=slot,
                )
                for slot, semi in enumerate(semis, start=1)
                for place, target in ((1, final), (2, bronze))
            )
            await s.commit()

        with assert_http_status(self, 409):
            await self.swap(bronze, 1, final, 1)
        self.assertEqual([(1, "t3"), (2, "t2")], await self.seats(bronze))
        self.assertEqual([(1, "t0"), (2, "t1")], await self.seats(final))

    async def test_rejects_the_same_slot_of_the_same_encounter(self) -> None:
        encounter = await self.encounter(0, 1)
        with assert_http_status(self, 400):
            await self.swap(encounter, 1, encounter, 1)

    async def test_rejects_a_completed_target(self) -> None:
        source = await self.encounter(0, 1)
        target = await self.encounter(2, 3, scores=(2, 0))
        with assert_http_status(self, 409):
            await self.swap(source, 1, target, 1)
        self.assertEqual([(1, "t0"), (2, "t1")], await self.seats(source))

    async def test_rejects_a_live_target(self) -> None:
        source = await self.encounter(0, 1)
        target = await self.encounter(2, 3, started_at=datetime.now(UTC))
        with assert_http_status(self, 409):
            await self.swap(source, 1, target, 1)
        self.assertEqual([(1, "t0"), (2, "t1")], await self.seats(source))

    async def test_rejects_a_target_in_another_stage(self) -> None:
        async with self.Session() as s:
            other = Stage(
                tournament_id=self.tournament_id,
                scoring_rule_id=self.rule_id,
                name="Other",
                stage_type=enums.StageType.SINGLE_ELIMINATION,
                order=2,
            )
            s.add(other)
            await s.flush()
            other_item = StageItem(stage_id=other.id, name="B", type=enums.StageItemType.SINGLE_BRACKET, order=0)
            s.add(other_item)
            await s.commit()
            other_id, other_item_id = other.id, other_item.id
        source = await self.encounter(0, 1)
        target = await self.encounter(2, 3, stage_id=other_id, item_id=other_item_id)
        with assert_http_status(self, 400):
            await self.swap(source, 1, target, 1)
        self.assertEqual([(1, "t0"), (2, "t1")], await self.seats(source))

    async def test_rejects_a_slot_past_the_card(self) -> None:
        source = await self.encounter(0, 1)
        target = await self.encounter(2, 3)
        with assert_http_status(self, 400):
            await self.swap(source, 3, target, 1)


class SwapSlotsStubbedRpcGuard(IsolatedAsyncioTestCase):
    async def test_the_rpc_refuses_a_caller_without_the_update_permission(self) -> None:
        broker = CapturingBroker()
        admin_misc.register(broker, SimpleNamespace(exception=lambda *a, **k: None))
        identity = make_identity(workspaces=[{"workspace_id": 1, "rbac_roles": [], "rbac_permissions": []}])
        with (
            patch.object(helpers.db, "async_session_maker", FakeSessionMaker()),
            patch.object(admin_misc.auth, "get_encounter_workspace_id", AsyncMock(return_value=1)),
        ):
            envelope = await broker.handlers["rpc.tournament.encounter_swap_slot"](
                {"identity": identity, "id": 10, "payload": _body(1, 11, 1).model_dump()},
                None,
            )
        self.assertFalse(envelope["ok"])
