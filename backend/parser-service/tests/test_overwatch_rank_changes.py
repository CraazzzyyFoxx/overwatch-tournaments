"""``rank_snapshot`` is a series of changes: what gets a row and what does not.

The pure decision lives in ``changed_ranks``; ``record_result`` is checked once
for the wiring around it -- an unchanged poll writes no snapshot but still
records the success the coverage dashboard reads.

Runs under stdlib unittest -- no pytest-asyncio in this repo.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "parser-service"))

from shared.core import enums  # noqa: E402
from shared.schemas.settings import RankCollectionConfig  # noqa: E402
from src.domain.overwatch_rank import (  # noqa: E402
    ParsedRank,
    RankFetchResult,
    RankSeriesState,
    changed_ranks,
)
from src.services.overwatch_rank import service as service_mod  # noqa: E402

PC = enums.RankPlatform.pc.value
CONSOLE = enums.RankPlatform.console.value


# The v2 ladder, tier 3: enough of a mapping for the tests to derive rank_value
# the way the service does, so a fixture cannot disagree with itself.
_BASE = {
    "bronze": 500,
    "silver": 1000,
    "gold": 1500,
    "platinum": 2000,
    "emerald": 2500,
    "diamond": 3000,
    "master": 3500,
}


def _value(division: str | None, tier: int | None) -> int | None:
    return None if division is None else _BASE[division] + (5 - tier) * 100


def _rank(role: str, division: str | None, tier: int | None, *, platform: str = PC) -> ParsedRank:
    return ParsedRank(
        platform=platform,
        role=role,
        division=division,
        tier=tier,
        season=13,
        is_ranked=division is not None,
    )


def _seen(role: str, division: str | None, tier: int | None, *, platform: str = PC) -> tuple[ParsedRank, int | None]:
    return _rank(role, division, tier, platform=platform), _value(division, tier)


def _stored(division: str | None, tier: int | None, rank_value: int | None = None) -> RankSeriesState:
    return RankSeriesState(
        division=division,
        tier=tier,
        is_ranked=division is not None,
        rank_value=_value(division, tier) if rank_value is None else rank_value,
    )


class ChangedRanksTests(TestCase):
    def test_first_poll_records_every_role_including_unranked(self) -> None:
        observed = [_seen("tank", "diamond", 3), _seen("damage", None, None), _seen("support", "master", 5)]
        self.assertEqual(changed_ranks(observed, {}), observed)

    def test_unchanged_poll_writes_nothing(self) -> None:
        observed = [_seen("tank", "diamond", 3), _seen("damage", None, None)]
        latest = {(PC, "tank"): _stored("diamond", 3), (PC, "damage"): _stored(None, None)}
        self.assertEqual(changed_ranks(observed, latest), [])

    def test_only_the_moved_role_gets_a_row(self) -> None:
        tank, support = _seen("tank", "diamond", 3), _seen("support", "master", 4)
        latest = {(PC, "tank"): _stored("diamond", 3), (PC, "support"): _stored("master", 5)}
        self.assertEqual(changed_ranks([tank, support], latest), [support])

    def test_division_change_is_a_change(self) -> None:
        latest = {(PC, "tank"): _stored("diamond", 1)}
        self.assertEqual(changed_ranks([_seen("tank", "master", 5)], latest), [_seen("tank", "master", 5)])

    def test_ranked_to_unranked_is_recorded_as_the_transition(self) -> None:
        """Going unranked is a change too: the chart's line has to stop somewhere."""
        latest = {(PC, "tank"): _stored("diamond", 3)}
        gone = _seen("tank", None, None)
        self.assertEqual(changed_ranks([gone], latest), [gone])

    def test_unranked_to_ranked_is_recorded(self) -> None:
        latest = {(PC, "tank"): _stored(None, None)}
        placed = _seen("tank", "gold", 2)
        self.assertEqual(changed_ranks([placed], latest), [placed])

    def test_platforms_are_independent_series(self) -> None:
        latest = {(PC, "tank"): _stored("diamond", 3)}
        console = _seen("tank", "diamond", 3, platform=CONSOLE)
        self.assertEqual(changed_ranks([_seen("tank", "diamond", 3), console], latest), [console])

    def test_season_alone_does_not_make_a_row(self) -> None:
        """A new season that leaves the rank where it was is not a rank change."""
        latest = {(PC, "tank"): _stored("diamond", 3)}
        rolled = ParsedRank(platform=PC, role="tank", division="diamond", tier=3, season=14, is_ranked=True)
        self.assertEqual(changed_ranks([(rolled, _value("diamond", 3))], latest), [])

    def test_a_remapped_ladder_writes_a_row_for_the_same_native_rank(self) -> None:
        """The balancer reads ``rank_value``: platinum 3 on the old ladder (2700)
        and on the new one (2200) are different numbers, so the latest row must
        carry the current one even though division/tier did not move."""
        latest = {(PC, "support"): _stored("platinum", 3, rank_value=2700)}
        remapped = _seen("support", "platinum", 3)
        self.assertEqual(changed_ranks([remapped], latest), [remapped])


class RecordResultTests(IsolatedAsyncioTestCase):
    """The wiring: an unchanged poll still counts as a successful check."""

    def setUp(self) -> None:
        self.svc = service_mod.RankStateService(
            repo=AsyncMock(),
            snapshot_repo=AsyncMock(),
            log_repo=AsyncMock(),
        )
        self.state = SimpleNamespace(
            last_checked_at=None,
            last_error="old",
            status="pending",
            last_success_at=None,
            consecutive_failures=2,
            next_eligible_at=None,
        )
        self.svc.ensure_state = AsyncMock(return_value=self.state)
        self.svc._user_id_for_tag = AsyncMock(return_value=42)
        self.config = RankCollectionConfig(enabled=True, interval_seconds=900, jitter_fraction=0.0)
        self.now = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)

    async def _record(self, ranks: list[ParsedRank], latest: dict) -> int:
        self.svc._latest_series_states = AsyncMock(return_value=latest)
        with patch.object(
            service_mod.mapping,
            "map_division_tier_to_rank_value",
            side_effect=lambda division, tier, lookup: _value(division, tier),
        ):
            return await self.svc.record_result(
                AsyncMock(),
                social_account_id=7,
                battle_tag="Name#1234",
                source="scheduled",
                result=RankFetchResult(status=enums.RankCollectionStatus.ok, ranks=ranks),
                lookup={},
                mapping_version="v2",
                config=self.config,
                now=self.now,
            )

    async def test_unchanged_poll_writes_no_snapshot_but_records_success(self) -> None:
        written = await self._record([_rank("tank", "diamond", 3)], {(PC, "tank"): _stored("diamond", 3)})

        self.assertEqual(written, 0)
        self.svc.snapshot_repo.create_many.assert_not_awaited()
        self.assertEqual(self.state.last_success_at, self.now)
        self.assertEqual(self.state.last_checked_at, self.now)
        self.assertEqual(self.state.status, enums.RankCollectionStatus.ok.value)
        self.assertEqual(self.state.consecutive_failures, 0)

    async def test_changed_role_writes_exactly_that_snapshot(self) -> None:
        written = await self._record(
            [_rank("tank", "diamond", 3), _rank("support", "master", 5)],
            {(PC, "tank"): _stored("diamond", 3), (PC, "support"): _stored("master", 4)},
        )

        self.assertEqual(written, 1)
        (rows,) = self.svc.snapshot_repo.create_many.await_args.args[1:]
        self.assertEqual(
            [(r.role, r.division, r.tier, r.rank_value, r.captured_at) for r in rows],
            [("support", "master", 5, _value("master", 5), self.now)],
        )
