import importlib
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock, patch

from shared.testing.factories import division_tier

division_grid = importlib.import_module("shared.division_grid")
division_grid_access = importlib.import_module("shared.services.division_grid.access")
division_grid_cache = importlib.import_module("shared.services.division_grid.cache")
division_rank = importlib.import_module("shared.domain.division_rank")


def make_grid() -> division_grid.DivisionGrid:
    return division_grid.DivisionGrid(
        version_id=77,
        tiers=(
            division_tier(1, 1, 500, None, slug="top", name="Top", icon_url="/top.png"),
            division_tier(2, 2, 100, 499, slug="mid", name="Mid", icon_url="/mid.png"),
        ),
    )


class DivisionRankDomainTests(TestCase):
    def test_resolves_rank_to_division_without_cache_or_database(self) -> None:
        grid = make_grid()

        self.assertEqual(1, division_rank.resolve_division_for_rank(grid, 750))
        self.assertEqual(2, division_rank.resolve_division_for_rank(grid, 250))
        self.assertEqual(2, division_rank.resolve_division_for_rank(grid, 50))

    def test_resolves_rank_from_division_and_clamps_to_grid_bounds(self) -> None:
        grid = make_grid()

        self.assertEqual(500, division_rank.resolve_rank_for_division(grid, 1))
        # Tier floor, not the band midpoint: a division->rank round trip has to land on
        # the same rank_value every other grid path uses (the 4449-for-Grandmaster-1 bug).
        self.assertEqual(100, division_rank.resolve_rank_for_division(grid, 2))
        self.assertEqual(1, division_rank.clamp_division_to_grid(grid, -4))
        self.assertEqual(2, division_rank.clamp_division_to_grid(grid, 99))


class DivisionGridCachedAccessTests(IsolatedAsyncioTestCase):
    async def test_load_division_grid_snapshot_uses_cache_hit_without_database(self) -> None:
        cached_snapshot = division_grid_cache.DivisionGridVersionSnapshot(
            id=77,
            tiers=(
                division_grid_cache.DivisionGridTierSnapshot(
                    id=1,
                    slug="top",
                    number=1,
                    name="Top",
                    rank_min=500,
                    rank_max=None,
                    icon_url="/top.png",
                ),
            ),
        )

        with (
            patch.object(
                division_grid_cache,
                "get_grid_version_snapshot",
                AsyncMock(return_value=cached_snapshot),
            ),
            patch.object(
                division_grid_access,
                "_load_division_grid_version_from_db",
                AsyncMock(),
            ) as load_from_db,
        ):
            snapshot = await division_grid_access.load_division_grid_snapshot(
                session=object(),
                version_id=77,
            )

        self.assertEqual(cached_snapshot, snapshot)
        load_from_db.assert_not_awaited()


def _execute_result(rows: list[tuple]) -> Mock:
    result = Mock()
    result.all = Mock(return_value=rows)
    return result


def _scalars_result(items: list) -> Mock:
    result = Mock()
    result.all = Mock(return_value=items)
    return result


class GetEffectiveDivisionGridVersionIdsBatchTests(IsolatedAsyncioTestCase):
    """Batch counterpart of ``get_effective_division_grid_version_id``.

    A per-tournament loop calling the single-item function pays one Redis
    round trip and up to two DB round trips PER tournament; these tests pin
    that the batch path instead pays a CONSTANT number of round trips no
    matter how many tournaments are asked for.
    """

    async def test_all_cache_hits_never_touch_the_database(self) -> None:
        session = Mock(execute=AsyncMock())

        with patch.object(
            division_grid_cache,
            "get_tournament_effective_version_ids",
            AsyncMock(return_value={1: 10, 2: None, 3: 30}),
        ):
            result = await division_grid_access.get_effective_division_grid_version_ids(
                session=session, tournament_ids=[1, 2, 3]
            )

        self.assertEqual({1: 10, 2: None, 3: 30}, result)
        session.execute.assert_not_awaited()

    async def test_cache_misses_cost_one_query_plus_one_default_per_workspace(self) -> None:
        # 1 -> cache hit; 2 -> cache miss, owns a grid; 3 and 4 -> cache miss,
        # unpinned in workspace 5; 8 -> unpinned in workspace 6, so it gets
        # workspace 6's default, not the first workspace's.
        session = Mock(
            execute=AsyncMock(
                return_value=_execute_result([(2, 20, 5), (3, None, 5), (4, None, 5), (8, None, 6)]),
            )
        )
        set_calls: list[dict[int, int | None]] = []

        with (
            patch.object(
                division_grid_cache,
                "get_tournament_effective_version_ids",
                AsyncMock(return_value={1: 10}),
            ),
            patch.object(
                division_grid_cache,
                "set_tournament_effective_version_ids",
                AsyncMock(side_effect=lambda values: set_calls.append(dict(values))),
            ),
            patch.object(
                division_grid_access,
                "get_workspace_division_grid_version_id",
                AsyncMock(side_effect=lambda _session, workspace_id: 99 if workspace_id == 5 else 77),
            ) as get_default,
        ):
            result = await division_grid_access.get_effective_division_grid_version_ids(
                session=session, tournament_ids=[1, 2, 3, 4, 8]
            )

        self.assertEqual({1: 10, 2: 20, 3: 99, 4: 99, 8: 77}, result)
        session.execute.assert_awaited_once()
        # One default lookup per distinct owning workspace, not per tournament.
        self.assertEqual(
            [((session, 5), {}), ((session, 6), {})], [tuple(call) for call in get_default.await_args_list]
        )
        self.assertEqual([{2: 20, 3: 99, 4: 99, 8: 77}], set_calls)

    async def test_deleted_tournament_returns_none_without_workspace_fallback(self) -> None:
        # Tournament 7 missed the cache and no longer has a database row
        # (deleted between the caller's own query and this one).
        session = Mock(execute=AsyncMock(return_value=_execute_result([])))

        with (
            patch.object(
                division_grid_cache,
                "get_tournament_effective_version_ids",
                AsyncMock(return_value={}),
            ),
            patch.object(division_grid_cache, "set_tournament_effective_version_ids", AsyncMock()),
            patch.object(
                division_grid_access,
                "get_workspace_division_grid_version_id",
                AsyncMock(),
            ) as get_default,
        ):
            result = await division_grid_access.get_effective_division_grid_version_ids(
                session=session, tournament_ids=[7]
            )

        self.assertEqual({7: None}, result)
        get_default.assert_not_awaited()

    async def test_empty_input_returns_empty_without_any_round_trip(self) -> None:
        session = Mock(execute=AsyncMock())

        with patch.object(division_grid_cache, "get_tournament_effective_version_ids", AsyncMock()) as get_cached:
            result = await division_grid_access.get_effective_division_grid_version_ids(
                session=session, tournament_ids=[]
            )

        self.assertEqual({}, result)
        get_cached.assert_not_awaited()
        session.execute.assert_not_awaited()


class LoadDivisionGridSnapshotsBatchTests(IsolatedAsyncioTestCase):
    """Batch counterpart of ``load_division_grid_snapshot``."""

    async def test_all_cache_hits_never_touch_the_database(self) -> None:
        session = Mock(scalars=AsyncMock())
        cached = {
            77: division_grid_cache.DivisionGridVersionSnapshot(id=77, tiers=()),
            88: division_grid_cache.DivisionGridVersionSnapshot(id=88, tiers=()),
        }

        with patch.object(division_grid_cache, "get_grid_version_snapshots", AsyncMock(return_value=cached)):
            result = await division_grid_access.load_division_grid_snapshots(session=session, version_ids=[77, 88])

        self.assertEqual(cached, result)
        session.scalars.assert_not_awaited()

    async def test_cache_misses_cost_exactly_one_batched_query(self) -> None:
        fresh_snapshot = division_grid_cache.DivisionGridVersionSnapshot(id=99, tiers=())
        fresh_version = Mock(id=99)
        session = Mock(scalars=AsyncMock(return_value=_scalars_result([fresh_version])))
        set_calls: list[dict[int, object]] = []

        with (
            patch.object(
                division_grid_cache,
                "get_grid_version_snapshots",
                AsyncMock(return_value={77: division_grid_cache.DivisionGridVersionSnapshot(id=77, tiers=())}),
            ),
            patch.object(
                division_grid_cache,
                "set_grid_version_snapshots",
                AsyncMock(side_effect=lambda snaps: set_calls.append(dict(snaps))),
            ),
            patch.object(
                division_grid_cache.DivisionGridVersionSnapshot,
                "from_model",
                classmethod(lambda cls, version: fresh_snapshot),
            ),
        ):
            result = await division_grid_access.load_division_grid_snapshots(session=session, version_ids=[77, 99])

        self.assertEqual(77, result[77].id)
        self.assertEqual(fresh_snapshot, result[99])
        session.scalars.assert_awaited_once()
        self.assertEqual([{99: fresh_snapshot}], set_calls)

    async def test_deleted_version_is_absent_from_result(self) -> None:
        session = Mock(scalars=AsyncMock(return_value=_scalars_result([])))

        with (
            patch.object(division_grid_cache, "get_grid_version_snapshots", AsyncMock(return_value={})),
            patch.object(division_grid_cache, "set_grid_version_snapshots", AsyncMock()) as set_snapshots,
        ):
            result = await division_grid_access.load_division_grid_snapshots(session=session, version_ids=[404])

        self.assertEqual({}, result)
        set_snapshots.assert_awaited_once_with({})

    async def test_empty_input_returns_empty_without_any_round_trip(self) -> None:
        session = Mock(scalars=AsyncMock())

        with patch.object(division_grid_cache, "get_grid_version_snapshots", AsyncMock()) as get_cached:
            result = await division_grid_access.load_division_grid_snapshots(session=session, version_ids=[])

        self.assertEqual({}, result)
        get_cached.assert_not_awaited()
        session.scalars.assert_not_awaited()


division_grid_schemas = importlib.import_module("src.schemas.division_grid")


def _fake_version_row(
    version_id: int,
    grid_id: int = 1,
    version: int = 1,
    label: str = "Season 1",
    status: str = "published",
    created_from_version_id: int | None = None,
    published_at=None,
) -> Mock:
    tier = Mock(
        id=10,
        slug="gold",
        number=1,
        sort_order=1,
        rank_min=1000,
        rank_max=1999,
        icon_url="/gold.png",
    )
    tier.name = "Gold"  # "name" collides with Mock's own ctor kwarg -- set after.
    return Mock(
        id=version_id,
        grid_id=grid_id,
        version=version,
        label=label,
        status=status,
        created_from_version_id=created_from_version_id,
        published_at=published_at,
        tiers=[tier],
    )


class LoadDivisionGridVersionReadPayloadsBatchTests(IsolatedAsyncioTestCase):
    """``load_division_grid_version_read_payloads`` -- the read-model counterpart
    of ``load_division_grid_snapshots``, cached under its own key so extending
    this richer shape can never break the (widely shared) resolution snapshot.
    """

    async def test_all_cache_hits_never_touch_the_database(self) -> None:
        session = Mock(scalars=AsyncMock())
        cached_payloads = {
            77: {
                "id": 77,
                "grid_id": 1,
                "version": 1,
                "label": "S1",
                "status": "published",
                "created_from_version_id": None,
                "published_at": None,
                "tiers": [],
            }
        }

        with patch.object(
            division_grid_cache, "get_grid_version_read_payloads", AsyncMock(return_value=cached_payloads)
        ):
            result = await division_grid_access.load_division_grid_version_read_payloads(
                session=session, version_ids=[77]
            )

        self.assertEqual(cached_payloads, result)
        session.scalars.assert_not_awaited()

    async def test_cache_miss_costs_one_query_and_the_payload_matches_the_pydantic_schema(self) -> None:
        fake_version = _fake_version_row(99, grid_id=3, version=2, label="Season 2", status="draft")
        session = Mock(scalars=AsyncMock(return_value=_scalars_result([fake_version])))
        set_calls: list[dict[int, dict]] = []

        with (
            patch.object(division_grid_cache, "get_grid_version_read_payloads", AsyncMock(return_value={})),
            patch.object(
                division_grid_cache,
                "set_grid_version_read_payloads",
                AsyncMock(side_effect=lambda payloads: set_calls.append(dict(payloads))),
            ),
        ):
            result = await division_grid_access.load_division_grid_version_read_payloads(
                session=session, version_ids=[99]
            )

        session.scalars.assert_awaited_once()
        self.assertEqual([99], list(result))
        self.assertEqual(result, set_calls[0])

        # The payload alone (no ``from_attributes``) must satisfy the real
        # DivisionGridVersionRead schema -- this is what pins the shape.
        read = division_grid_schemas.DivisionGridVersionRead.model_validate(result[99])
        self.assertEqual(99, read.id)
        self.assertEqual(3, read.grid_id)
        self.assertEqual(2, read.version)
        self.assertEqual("Season 2", read.label)
        self.assertEqual("draft", read.status)
        self.assertEqual(1, len(read.tiers))
        self.assertEqual("gold", read.tiers[0].slug)
        self.assertEqual(99, read.tiers[0].version_id)

    async def test_deleted_version_is_absent_from_result(self) -> None:
        session = Mock(scalars=AsyncMock(return_value=_scalars_result([])))

        with (
            patch.object(division_grid_cache, "get_grid_version_read_payloads", AsyncMock(return_value={})),
            patch.object(division_grid_cache, "set_grid_version_read_payloads", AsyncMock()) as set_payloads,
        ):
            result = await division_grid_access.load_division_grid_version_read_payloads(
                session=session, version_ids=[404]
            )

        self.assertEqual({}, result)
        set_payloads.assert_awaited_once_with({})

    async def test_empty_input_returns_empty_without_any_round_trip(self) -> None:
        session = Mock(scalars=AsyncMock())

        with patch.object(division_grid_cache, "get_grid_version_read_payloads", AsyncMock()) as get_cached:
            result = await division_grid_access.load_division_grid_version_read_payloads(
                session=session, version_ids=[]
            )

        self.assertEqual({}, result)
        get_cached.assert_not_awaited()
        session.scalars.assert_not_awaited()


class InvalidateGridVersionTests(IsolatedAsyncioTestCase):
    async def test_clears_both_the_resolution_snapshot_and_the_full_read_payload(self) -> None:
        deleted_keys: list[str] = []

        with (
            patch.object(division_grid_cache.cache, "is_setup", Mock(return_value=True)),
            patch.object(
                division_grid_cache.cache, "delete", AsyncMock(side_effect=lambda key: deleted_keys.append(key))
            ),
            patch.object(division_grid_cache.cache, "delete_match", AsyncMock()),
        ):
            await division_grid_cache.invalidate_grid_version(55)

        self.assertIn(division_grid_cache._version_key(55), deleted_keys)
        self.assertIn(division_grid_cache._version_read_key(55), deleted_keys)
