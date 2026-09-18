"""Unit tests for the cached roster-shape access layer.

Pins the two non-obvious design decisions of
``shared.services.roster_shape_access`` so a later "simplification" cannot
quietly undo them:

1. The cache holds the **raw per-level slot maps**, never the resolved
   effective shape. Therefore changing a workspace default invalidates exactly
   one key instead of a wildcard sweep over every tournament of the workspace
   (which is what ``division_grid_cache.invalidate_workspace`` is forced to do).
2. A ``NULL`` column is cached as ``{}``, not ``None``, because Redis cannot
   tell "key absent" from "key holds None" -- caching ``None`` would mean a
   database round-trip on every read of the overwhelmingly common no-override
   case.

Runs under stdlib unittest with a fake session and cashews' in-memory backend
-- no Postgres, no Redis, matching the repo's IsolatedAsyncioTestCase
convention (see ``test_finalize_encounter_score.py`` for the fake-session
pattern, ``app-service/tests/test_user_read_caches.py`` for ``mem://``).
"""

from __future__ import annotations

from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from cashews import cache
from sqlalchemy.dialects import postgresql

from shared.domain.roster_shape import DEFAULT_ROSTER_SHAPE, RosterShapeError, parse_roster_slots
from shared.services import roster_shape_access as access

TOURNAMENT_COLUMN_SQL = "tournament.roster_slots_json"
WORKSPACE_COLUMN_SQL = "workspace.default_roster_slots_json"


def _compiled_sql(statement: Any) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


class _Session:
    """Minimal ``AsyncSession`` stand-in that answers the two column probes.

    Counts the probes per level, so a test can assert "no second SELECT"
    without reaching into the cache internals.
    """

    def __init__(
        self,
        *,
        tournament_slots: Any = None,
        workspace_slots: Any = None,
    ) -> None:
        self._tournament_slots = tournament_slots
        self._workspace_slots = workspace_slots
        self.statements: list[str] = []

    async def scalar(self, statement: Any) -> Any:
        sql = _compiled_sql(statement)
        self.statements.append(sql)
        if TOURNAMENT_COLUMN_SQL in sql:
            return self._tournament_slots
        if WORKSPACE_COLUMN_SQL in sql:
            return self._workspace_slots
        raise AssertionError(f"Unexpected statement: {sql}")

    @property
    def calls(self) -> int:
        return len(self.statements)

    @property
    def tournament_calls(self) -> int:
        return sum(1 for sql in self.statements if TOURNAMENT_COLUMN_SQL in sql)

    @property
    def workspace_calls(self) -> int:
        return sum(1 for sql in self.statements if WORKSPACE_COLUMN_SQL in sql)


class _FakeCache:
    """In-process cache double for the degradation tests.

    ``get`` returning ``None`` for both "absent" and "stored None" mirrors
    Redis exactly -- which is the whole reason ``{}`` is the cached spelling of
    a ``NULL`` column.
    """

    def __init__(self, *, setup: bool = True, fail: bool = False) -> None:
        self.store: dict[str, Any] = {}
        self._setup = setup
        self._fail = fail
        self.get_calls: list[str] = []
        self.set_calls: list[str] = []

    def is_setup(self) -> bool:
        return self._setup

    async def get(self, key: str) -> Any:
        self.get_calls.append(key)
        if self._fail:
            raise RuntimeError("redis is down")
        return self.store.get(key)

    async def set(self, key: str, value: Any, expire: Any = None) -> None:
        self.set_calls.append(key)
        if self._fail:
            raise RuntimeError("redis is down")
        self.store[key] = value

    async def delete(self, key: str) -> None:
        if self._fail:
            raise RuntimeError("redis is down")
        self.store.pop(key, None)

    async def delete_match(self, pattern: str) -> None:  # pragma: no cover - must never run
        raise AssertionError("roster shape invalidation must never use wildcards")


class RosterShapeAccessTests(IsolatedAsyncioTestCase):
    """Cache is the real cashews ``mem://`` backend unless a test injects a double."""

    async def asyncSetUp(self) -> None:
        cache.setup("mem://", prefix=access.CACHE_KEY_PREFIX)
        await cache.delete_match(f"{access.CACHE_KEY_PREFIX}roster_slots:*")

    # --- resolution -------------------------------------------------------

    async def test_tournament_override_beats_workspace_default(self) -> None:
        session = _Session(
            tournament_slots={"tank": 2, "damage": 2, "support": 2},
            workspace_slots={"tank": 1, "damage": 1, "support": 1},
        )

        shape = await access.get_effective_roster_shape(
            session,
            tournament_id=1,
            workspace_id=1,
        )

        self.assertEqual(shape, parse_roster_slots({"tank": 2, "damage": 2, "support": 2}))

    async def test_workspace_default_applies_without_tournament_override(self) -> None:
        session = _Session(tournament_slots=None, workspace_slots={"tank": 1, "damage": 3, "support": 2})

        shape = await access.get_effective_roster_shape(
            session,
            tournament_id=2,
            workspace_id=2,
        )

        self.assertEqual(shape, parse_roster_slots({"tank": 1, "damage": 3, "support": 2}))

    async def test_both_levels_null_returns_the_canonical_default_object(self) -> None:
        session = _Session(tournament_slots=None, workspace_slots=None)

        shape = await access.get_effective_roster_shape(
            session,
            tournament_id=3,
            workspace_id=3,
        )

        # ``is``, not ``==``: the fallback must reuse the import-time default
        # rather than re-parse the same slot map on every read.
        self.assertIs(shape, DEFAULT_ROSTER_SHAPE)

    async def test_no_ids_returns_the_default_without_touching_the_session(self) -> None:
        session = AsyncMock()

        shape = await access.get_effective_roster_shape(
            session,
            tournament_id=None,
            workspace_id=None,
        )

        self.assertIs(shape, DEFAULT_ROSTER_SHAPE)
        self.assertEqual(session.mock_calls, [])

    async def test_corrupt_stored_slots_raise_instead_of_degrading(self) -> None:
        session = _Session(tournament_slots={"healer": 6})

        with self.assertRaises(RosterShapeError) as ctx:
            await access.get_effective_roster_shape(session, tournament_id=4, workspace_id=4)

        self.assertEqual(ctx.exception.code, "roster_slots_unknown_code")

        # Same failure on the warm read: the raw value is cached unvalidated, so a
        # corrupt column cannot start resolving to the default once it is cached.
        with self.assertRaises(RosterShapeError) as cached_ctx:
            await access.get_effective_roster_shape(session, tournament_id=4, workspace_id=4)

        self.assertEqual(cached_ctx.exception.code, "roster_slots_unknown_code")
        self.assertEqual(session.tournament_calls, 1)

    # --- caching ----------------------------------------------------------

    async def test_second_read_of_a_stored_shape_skips_the_database(self) -> None:
        session = _Session(
            tournament_slots={"tank": 1, "damage": 2, "support": 2},
            workspace_slots={"tank": 2, "damage": 2, "support": 2},
        )

        first = await access.get_effective_roster_shape(session, tournament_id=5, workspace_id=5)
        calls_after_first = session.calls
        second = await access.get_effective_roster_shape(session, tournament_id=5, workspace_id=5)

        self.assertEqual(second, first)
        self.assertEqual(calls_after_first, 2)
        self.assertEqual(session.calls, calls_after_first)

    async def test_second_read_of_a_null_column_also_skips_the_database(self) -> None:
        # The point of decision #2. A cached ``None`` is indistinguishable from
        # a cache miss, so the most common case (no override anywhere) would
        # hit the database forever. ``{}`` is the cached spelling of ``NULL``.
        session = _Session(tournament_slots=None, workspace_slots=None)

        first = await access.get_effective_roster_shape(session, tournament_id=6, workspace_id=6)
        calls_after_first = session.calls
        second = await access.get_effective_roster_shape(session, tournament_id=6, workspace_id=6)

        self.assertIs(first, DEFAULT_ROSTER_SHAPE)
        self.assertIs(second, DEFAULT_ROSTER_SHAPE)
        self.assertEqual(calls_after_first, 2)
        self.assertEqual(session.calls, calls_after_first)

    async def test_tournament_invalidation_rereads_only_the_tournament_key(self) -> None:
        session = _Session(tournament_slots=None, workspace_slots={"tank": 1, "damage": 2, "support": 2})

        await access.get_effective_roster_shape(session, tournament_id=7, workspace_id=7)
        self.assertEqual((session.tournament_calls, session.workspace_calls), (1, 1))

        await access.invalidate_roster_shape_cache(tournament_id=7)
        await access.get_effective_roster_shape(session, tournament_id=7, workspace_id=7)

        self.assertEqual((session.tournament_calls, session.workspace_calls), (2, 1))

    async def test_workspace_invalidation_drops_one_key_and_never_uses_wildcards(self) -> None:
        # Deliberate difference from ``division_grid_cache.invalidate_workspace``,
        # which must ``delete_match("...tournament:*:effective_version")`` because
        # it caches the *effective* value per tournament. We cache the raw
        # per-level maps, so a workspace default change touches exactly its own
        # key -- no key-space scan.
        session = _Session(tournament_slots=None, workspace_slots={"tank": 1, "damage": 2, "support": 2})

        await access.get_effective_roster_shape(session, tournament_id=8, workspace_id=8)

        delete = AsyncMock()
        delete_match = AsyncMock()
        with (
            patch.object(cache, "delete", delete),
            patch.object(cache, "delete_match", delete_match),
        ):
            await access.invalidate_roster_shape_cache(workspace_id=8)

        delete.assert_awaited_once_with(f"{access.CACHE_KEY_PREFIX}roster_slots:workspace:8")
        delete_match.assert_not_awaited()

        # And the real effect: only the workspace level is re-read.
        await cache.delete(f"{access.CACHE_KEY_PREFIX}roster_slots:workspace:8")
        await access.get_effective_roster_shape(session, tournament_id=8, workspace_id=8)
        self.assertEqual((session.tournament_calls, session.workspace_calls), (1, 2))

    # --- degradation ------------------------------------------------------

    async def test_works_without_a_configured_cache(self) -> None:
        session = _Session(tournament_slots={"tank": 1, "damage": 2, "support": 2})
        fake = _FakeCache(setup=False)

        with patch.object(access, "cache", fake):
            shape = await access.get_effective_roster_shape(session, tournament_id=9, workspace_id=9)
            await access.invalidate_roster_shape_cache(tournament_id=9, workspace_id=9)

        self.assertEqual(shape, parse_roster_slots({"tank": 1, "damage": 2, "support": 2}))
        self.assertEqual(fake.get_calls, [])
        self.assertEqual(fake.set_calls, [])
        # No cache means every read goes to the database -- correctness over speed.
        self.assertEqual(session.calls, 2)

    async def test_a_broken_cache_does_not_break_the_read(self) -> None:
        session = _Session(tournament_slots={"tank": 2, "damage": 2, "support": 1})
        fake = _FakeCache(fail=True)

        with patch.object(access, "cache", fake):
            shape = await access.get_effective_roster_shape(session, tournament_id=10, workspace_id=10)
            # Invalidation is best-effort too: a dead Redis must not fail a write path.
            await access.invalidate_roster_shape_cache(tournament_id=10, workspace_id=10)

        self.assertEqual(shape, parse_roster_slots({"tank": 2, "damage": 2, "support": 1}))
        # Both sides of the wrapper were exercised and both swallowed the failure.
        self.assertTrue(fake.get_calls)
        self.assertTrue(fake.set_calls)

    # --- public per-level getters ----------------------------------------

    async def test_level_getters_return_none_for_a_null_column_even_when_cached(self) -> None:
        # ``{}`` is an internal cache representation and must not leak into the
        # public type: callers see the column as it is, i.e. ``None``.
        session = _Session(tournament_slots=None, workspace_slots=None)

        self.assertIsNone(await access.get_tournament_roster_slots(session, 11))
        self.assertIsNone(await access.get_workspace_roster_slots(session, 11))
        calls_after_first = session.calls

        self.assertIsNone(await access.get_tournament_roster_slots(session, 11))
        self.assertIsNone(await access.get_workspace_roster_slots(session, 11))

        self.assertEqual(calls_after_first, 2)
        self.assertEqual(session.calls, calls_after_first)

    async def test_level_getters_return_stored_maps_and_skip_the_session_for_none_ids(self) -> None:
        session = _Session(
            tournament_slots={"tank": 1, "damage": 1},
            workspace_slots={"support": 2, "flex": 1},
        )

        self.assertEqual(await access.get_tournament_roster_slots(session, 12), {"tank": 1, "damage": 1})
        self.assertEqual(await access.get_workspace_roster_slots(session, 12), {"support": 2, "flex": 1})

        empty = AsyncMock()
        self.assertIsNone(await access.get_tournament_roster_slots(empty, None))
        self.assertIsNone(await access.get_workspace_roster_slots(empty, None))
        self.assertEqual(empty.mock_calls, [])

    async def test_column_probes_are_narrow_selects(self) -> None:
        session = _Session(tournament_slots=None, workspace_slots=None)

        await access.get_effective_roster_shape(session, tournament_id=13, workspace_id=13)

        tournament_sql, workspace_sql = session.statements
        # A single column, not the whole ORM row: the shape is read on hot paths.
        self.assertNotIn("tournament.win_points", tournament_sql)
        self.assertNotIn("workspace.brand_accent", workspace_sql)
        # Schema-qualified in compiled SQL, hence the regex rather than a literal.
        self.assertRegex(tournament_sql, r"WHERE \S*tournament\.id = ")
        self.assertRegex(workspace_sql, r"WHERE \S*workspace\.id = ")
