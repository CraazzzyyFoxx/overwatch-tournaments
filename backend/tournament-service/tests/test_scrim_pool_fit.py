"""``scrim/service.py:_assert_playable`` — a room is refused, not bricked.

``create_room`` validates a *custom* pool against the engine's own validators,
but a *copied* one was trusted. Borrowing a 3-slot tournament round for a
best-of-5 scrim therefore produced a room whose only screen read

    The pool does not cover this series
    This match plays more rounds than the configured pool has slots.
    The organizer has to add the missing slots — waiting will not fix it.

naming a person a scrim does not have, and leaving no recovery but closing the
room. The check now runs at create time, against the rows just written, and the
request is refused instead.

Exercised against a real (SQLite) database rather than a faked session, because
the whole point is that the verdict comes from ``unavailable_reason`` — the same
function ``ensure_pick_ban_session`` gates on — and a fake would only assert
that this module can call a stub.
"""

from __future__ import annotations

import sys
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest import IsolatedAsyncioTestCase

import sqlalchemy as sa
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


from sqlalchemy.dialects.postgresql import ARRAY, JSONB  # noqa: E402

from shared.core.enums import MapVetoMode, PickBanKind  # noqa: E402
from shared.core.errors import BaseAPIException as HTTPException  # noqa: E402
from shared.models.tournament.pick_ban import (  # noqa: E402
    PickBanConfig,
    PickBanConfigItem,
    PickBanConfigSlot,
    PickBanConfigSlotItem,
)
from src import models  # noqa: E402
from src.services.scrim import service as scrim  # noqa: E402


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN003, ANN202
    return "JSON"


@compiles(ARRAY, "sqlite")
def _compile_array_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN003, ANN202
    return "JSON"


@compiles(sa.BigInteger, "sqlite")
def _compile_bigint_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN003, ANN202
    return "INTEGER"


# ``tournament.player`` holds no rows but must exist: ``Team.avg_sr`` is a
# ``column_property`` aggregate over it. ``encounter_readiness`` is reached on the
# healthy path, where the verdict is "nobody is ready yet".
TABLE_NAMES = (
    "players.user",
    "tournament.tournament",
    "tournament.stage",
    "tournament.stage_round_best_of",
    "tournament.team",
    "tournament.player",
    "tournament.encounter",
    # ``Encounter.has_logs`` is a ``column_property`` EXISTS over this table
    # (see ``shared/models/matches/match.py``) — every ``select(Encounter)``
    # references it now, so it must exist even with zero rows.
    "matches.match",
    "tournament.encounter_readiness",
    "tournament.pick_ban_config",
    "tournament.pick_ban_config_item",
    "tournament.pick_ban_config_slot",
    "tournament.pick_ban_config_slot_item",
)

WORKSPACE_ID = 1
CONTAINER_ID = 7
STAGE_ID = 70
ENCOUNTER_ID = 700


class _AsyncSessionShim:
    """Async facade over a synchronous ``Session`` — no aiosqlite is installed,
    and these paths await only ``execute``/``scalar``."""

    def __init__(self, session: Session) -> None:
        self.sync_session = session

    async def execute(self, statement, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return self.sync_session.execute(statement, *args, **kwargs)

    async def scalar(self, statement, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return self.sync_session.scalar(statement, *args, **kwargs)

    async def get(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return self.sync_session.get(*args, **kwargs)

    def __getattr__(self, name):  # noqa: ANN001, ANN204
        return getattr(self.sync_session, name)


class _Fixture:
    def __init__(self) -> None:
        metadata = models.Tournament.__table__.metadata
        tables = [metadata.tables[name] for name in TABLE_NAMES]
        self.engine = sa.create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        with self.engine.begin() as conn:
            for schema in sorted({table.schema for table in tables if table.schema}):
                conn.exec_driver_sql(f"ATTACH DATABASE ':memory:' AS {schema}")
            for table in tables:
                table.create(conn)
        self.session = Session(self.engine)
        self.shim = _AsyncSessionShim(self.session)
        self._next_id = 900

        self.insert(
            models.Tournament.__table__,
            id=CONTAINER_ID,
            workspace_id=WORKSPACE_ID,
            name=scrim.CONTAINER_NAME,
            slug="scrims",
            is_hidden=True,
            is_league=False,
            start_date=datetime(2026, 8, 12, tzinfo=UTC),
            end_date=datetime(2026, 8, 12, tzinfo=UTC),
            win_points=1.0,
            draw_points=0.5,
            loss_points=0.0,
        )
        self.insert(
            models.Stage.__table__,
            id=STAGE_ID,
            tournament_id=CONTAINER_ID,
            name="room",
            stage_type="single_elimination",
            max_rounds=1,
            order=1,
            # A scrim room's stage is published immediately in production
            # (``scrim/service.py::create_room``) -- mirrored here so the fake
            # room is never mistaken for an organizer's un-activated preview.
            is_published=True,
        )

    def close(self) -> None:
        self.session.close()
        self.engine.dispose()

    def _id(self) -> int:
        self._next_id += 1
        return self._next_id

    def insert(self, table, **values) -> None:  # noqa: ANN001, ANN003
        self.session.execute(sa.insert(table).values(**values))

    def encounter(self, *, best_of: int) -> models.Encounter:
        teams = []
        for _ in range(2):
            team_id = self._id()
            self.insert(
                models.Team.__table__,
                id=team_id,
                tournament_id=CONTAINER_ID,
                name=f"team{team_id}",
                balancer_name=f"team{team_id}",
            )
            teams.append(team_id)
        self.insert(
            models.Encounter.__table__,
            id=ENCOUNTER_ID,
            tournament_id=CONTAINER_ID,
            stage_id=STAGE_ID,
            name="room",
            home_team_id=teams[0],
            away_team_id=teams[1],
            home_score=0,
            away_score=0,
            round=1,
            best_of=best_of,
            status="OPEN",
        )
        self.session.commit()
        return self.session.get(models.Encounter, ENCOUNTER_ID)

    def slot_config(self, *, slots: list[list[int]], kind: PickBanKind = PickBanKind.MAP) -> None:
        """A slot-mode config exactly as ``_clone_config`` writes one: pinned to the
        room's stage, round-less."""
        config_id = self._id()
        self.insert(
            PickBanConfig.__table__,
            id=config_id,
            tournament_id=CONTAINER_ID,
            stage_id=STAGE_ID,
            round=None,
            kind=kind.value,
            mode=MapVetoMode.SLOTS.value,
            sequence_json=[],
        )
        for position, candidates in enumerate(slots, start=1):
            slot_id = self._id()
            self.insert(
                PickBanConfigSlot.__table__,
                id=slot_id,
                pick_ban_config_id=config_id,
                position=position,
            )
            for order, item_id in enumerate(candidates):
                self.insert(
                    PickBanConfigSlotItem.__table__,
                    id=self._id(),
                    pick_ban_config_slot_id=slot_id,
                    item_id=item_id,
                    sort_order=order,
                )
        self.session.commit()

    def flat_config(self, *, item_ids: list[int], kind: PickBanKind = PickBanKind.MAP) -> None:
        config_id = self._id()
        self.insert(
            PickBanConfig.__table__,
            id=config_id,
            tournament_id=CONTAINER_ID,
            stage_id=STAGE_ID,
            round=None,
            kind=kind.value,
            mode=MapVetoMode.POOL.value,
            sequence_json=[],
        )
        for order, item_id in enumerate(item_ids):
            self.insert(
                PickBanConfigItem.__table__,
                id=self._id(),
                pick_ban_config_id=config_id,
                item_id=item_id,
                sort_order=order,
            )
        self.session.commit()


class _FitCase(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.db = _Fixture()
        self.addCleanup(self.db.close)

    async def assert_playable(self, encounter: Any, *, best_of: int) -> None:
        await scrim.scrim_service._assert_playable(self.db.shim, encounter, [PickBanKind.MAP], best_of=best_of)


class ASlotPoolTooShortForTheSeriesIsRefused(_FitCase):
    async def test_three_slots_cannot_serve_a_best_of_five(self) -> None:
        """The reported failure: a Bo5 room copying a 3-slot round."""
        encounter = self.db.encounter(best_of=5)
        self.db.slot_config(slots=[[1, 2], [3, 4], [5, 6]])

        with self.assertRaises(HTTPException) as ctx:
            await self.assert_playable(encounter, best_of=5)

        self.assertEqual(422, ctx.exception.status_code)
        detail = str(ctx.exception.detail)
        # The numbers have to be IN the message: "does not cover this series" was
        # the old screen, and it told the captain nothing they could act on.
        self.assertIn("3", detail)
        self.assertIn("best_of", detail)

    async def test_three_slots_serve_a_best_of_three(self) -> None:
        encounter = self.db.encounter(best_of=3)
        self.db.slot_config(slots=[[1, 2], [3, 4], [5, 6]])
        await self.assert_playable(encounter, best_of=3)

    async def test_a_shorter_series_than_the_pool_is_fine(self) -> None:
        """Extra slots are truncated by the engine, not an error."""
        encounter = self.db.encounter(best_of=1)
        self.db.slot_config(slots=[[1, 2], [3, 4], [5, 6]])
        await self.assert_playable(encounter, best_of=1)

    async def test_a_slot_with_nothing_to_ban_is_refused(self) -> None:
        encounter = self.db.encounter(best_of=2)
        self.db.slot_config(slots=[[1, 2], [3]])

        with self.assertRaises(HTTPException) as ctx:
            await self.assert_playable(encounter, best_of=2)

        self.assertEqual(422, ctx.exception.status_code)
        self.assertIn("candidates", str(ctx.exception.detail))

    async def test_a_slot_mode_config_with_no_slots_is_refused(self) -> None:
        """A slot config with no groups is a rules template now (it saves, and
        opens no room), so the refusal names the missing candidates rather than
        a slot count the organizer cannot raise."""
        encounter = self.db.encounter(best_of=1)
        self.db.slot_config(slots=[])

        with self.assertRaises(HTTPException) as ctx:
            await self.assert_playable(encounter, best_of=1)

        self.assertEqual(422, ctx.exception.status_code)
        self.assertIn("no candidates", str(ctx.exception.detail))


class AFlatPoolIsNotJudgedOnLength(_FitCase):
    """The engine CLAMPS a flat pool to what it can play
    (``build_sequence_for_best_of``: ``played = min(best_of, pool_size)``), so
    refusing one here would be stricter than the engine and would block a
    perfectly playable room."""

    async def test_a_small_flat_pool_is_accepted_for_a_long_series(self) -> None:
        encounter = self.db.encounter(best_of=5)
        self.db.flat_config(item_ids=[1, 2, 3])
        await self.assert_playable(encounter, best_of=5)


class AMissingConfigIsRefused(_FitCase):
    async def test_a_kind_with_no_config_at_all_is_refused(self) -> None:
        """Cannot happen through ``create_room`` — it only passes kinds it wrote a
        config for — so this pins the branch as a loud failure rather than a
        silently bricked room if that ever stops holding."""
        encounter = self.db.encounter(best_of=3)

        with self.assertRaises(HTTPException) as ctx:
            await self.assert_playable(encounter, best_of=3)

        self.assertEqual(422, ctx.exception.status_code)

    async def test_a_hero_config_is_checked_independently_of_the_map_one(self) -> None:
        encounter = self.db.encounter(best_of=3)
        self.db.slot_config(slots=[[1, 2], [3, 4], [5, 6]])
        self.db.slot_config(slots=[[9, 10]], kind=PickBanKind.HERO)

        with self.assertRaises(HTTPException) as ctx:
            await scrim.scrim_service._assert_playable(
                self.db.shim, encounter, [PickBanKind.MAP, PickBanKind.HERO], best_of=3
            )

        self.assertEqual(422, ctx.exception.status_code)
        self.assertIn("1", str(ctx.exception.detail))


class TheHealthyRoomPasses(_FitCase):
    async def test_not_ready_yet_is_not_a_refusal(self) -> None:
        """A fresh room has nobody ready, which ``unavailable_reason`` reports as
        ``not_ready``. That is the normal state and must not be mistaken for a
        broken pool — the bug this whole check risks introducing."""
        encounter = self.db.encounter(best_of=3)
        self.db.slot_config(slots=[[1, 2], [3, 4], [5, 6]])
        readiness = models.Tournament.__table__.metadata.tables["tournament.encounter_readiness"]
        self.assertEqual(0, self.db.session.scalar(sa.select(sa.func.count()).select_from(readiness)))
        await self.assert_playable(encounter, best_of=3)
