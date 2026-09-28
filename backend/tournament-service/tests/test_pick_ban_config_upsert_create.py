"""``pick_ban_config.upsert_config`` — the create path must not lazy-load its pool.

``config_repo.create`` flushes, so a freshly inserted ``PickBanConfig`` is
persistent with ``items``/``slots`` *unloaded*. The wholesale replacement then
assigned onto those collections, and SQLAlchemy lazy-loaded them first to work
out the ``delete-orphan`` diff — a SELECT emitted outside the greenlet under
asyncpg, i.e. ``MissingGreenlet`` on every first-time config upsert.

Asserted as "no SELECT against the child tables fires after the config INSERT",
which is exactly the condition that raised, and is driver-independent: no
aiosqlite in this environment, and a synchronous session would happily service
the lazy load instead of raising.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

import sqlalchemy as sa
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

from sqlalchemy.dialects.postgresql import ARRAY, JSONB  # noqa: E402

from shared.core.enums import (  # noqa: E402
    FirstBanRotation,
    FirstPickRule,
    MapVetoMode,
    PickBanKind,
)
from shared.domain import pick_ban_rules as pbr  # noqa: E402
from shared.models.tournament.pick_ban import PickBanConfig  # noqa: E402
from src import models  # noqa: E402
from src.services.encounter.pick_ban_config import PickBanConfigService, SlotSpec  # noqa: E402


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN003, ANN202
    return "JSON"


@compiles(ARRAY, "sqlite")
def _compile_array_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN003, ANN202
    return "JSON"


@compiles(sa.BigInteger, "sqlite")
def _compile_bigint_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN003, ANN202
    return "INTEGER"


TABLE_NAMES = (
    "tournament.pick_ban_config",
    "tournament.pick_ban_config_item",
    "tournament.pick_ban_config_slot",
    "tournament.pick_ban_config_slot_item",
)

TOURNAMENT_ID = 11
CHILD_TABLES = ("pick_ban_config_item", "pick_ban_config_slot", "pick_ban_config_slot_item")


class _AsyncSessionShim:
    """Async facade over a synchronous ``Session``; the service awaits only
    ``execute``/``flush``."""

    def __init__(self, session: Session) -> None:
        self.sync_session = session

    async def execute(self, statement, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return self.sync_session.execute(statement, *args, **kwargs)

    async def flush(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return self.sync_session.flush(*args, **kwargs)

    def __getattr__(self, name):  # noqa: ANN001, ANN204
        return getattr(self.sync_session, name)


class UpsertConfigCreatePathTest(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
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
        self.statements: list[str] = []

        @sa.event.listens_for(self.engine, "before_cursor_execute")
        def _record(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001, ANN202
            self.statements.append(" ".join(statement.split()))

        self.service = PickBanConfigService()

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    async def _upsert(self, **overrides) -> PickBanConfig:  # noqa: ANN003
        kwargs = {
            "tournament_id": TOURNAMENT_ID,
            "kind": PickBanKind.MAP,
            "mode": MapVetoMode.SLOTS,
            "first_pick_rule": FirstPickRule.HIGHER_SEED,
            "first_ban_rotation": FirstBanRotation.ALTERNATE,
            "ruleset": pbr.PRESETS_BY_ID["map_slot_veto"].ruleset.to_json(),
            "item_ids": [1, 2, 3],
            "slots": [SlotSpec(candidates=[1, 2], reserve_item_id=3)],
        }
        kwargs.update(overrides)
        return await self.service.upsert_config(self.shim, **kwargs)

    async def test_create_path_emits_no_child_select(self) -> None:
        config = await self._upsert()
        self.session.commit()

        selects = [s for s in self.statements if s.startswith("SELECT") and any(t in s for t in CHILD_TABLES)]
        assert not selects, f"create path lazy-loaded the pool: {selects}"

        assert [item.item_id for item in config.items] == [1, 2, 3]
        assert [slot.position for slot in config.slots] == [1]
        assert [item.item_id for item in config.slots[0].items] == [1, 2]
        assert config.slots[0].reserve_item_id == 3

    async def test_update_path_replaces_pool(self) -> None:
        await self._upsert()
        self.session.commit()

        config = await self._upsert(item_ids=[4], slots=[SlotSpec(candidates=[4])])
        self.session.commit()

        assert [item.item_id for item in config.items] == [4]
        assert [item.item_id for item in config.slots[0].items] == [4]
        assert self.session.scalar(sa.select(sa.func.count()).select_from(PickBanConfig)) == 1


if __name__ == "__main__":
    import unittest

    unittest.main()
