import importlib
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

division_grid = importlib.import_module("shared.division_grid")
division_grid_access = importlib.import_module("shared.services.division_grid_access")
division_grid_cache = importlib.import_module("shared.services.division_grid_cache")
division_rank = importlib.import_module("shared.domain.division_rank")


def make_grid() -> division_grid.DivisionGrid:
    return division_grid.DivisionGrid(
        version_id=77,
        tiers=(
            division_grid.DivisionTier(
                id=1,
                slug="top",
                number=1,
                name="Top",
                rank_min=500,
                rank_max=None,
                icon_url="/top.png",
            ),
            division_grid.DivisionTier(
                id=2,
                slug="mid",
                number=2,
                name="Mid",
                rank_min=100,
                rank_max=499,
                icon_url="/mid.png",
            ),
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
        self.assertEqual(299, division_rank.resolve_rank_for_division(grid, 2))
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
