"""Layer precedence in ``MemberRankService.resolve``.

The resolver is the only place that decides which of a member's several rank
sources a balance actually runs on, and it is shared by mixes (``MIX_ORDER``) and
tournaments (``TOURNAMENT_ORDER``). The two disagree about precedence on purpose,
so the order has to be asserted per context rather than once.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"
for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from shared.domain.member_rank import ResolvedRank  # noqa: E402
from shared.services.member_rank import (  # noqa: E402
    MIX_ORDER,
    TOURNAMENT_ORDER,
    MemberRankService,
)

_FETCH = "shared.services.member_rank.fetch_latest_ow_ranks_by_account"
_ROLES = ("tank", "damage", "support")

_HOST = 99


def _rank(member_id: int, role: str, value: int, author_user_id: int | None = None) -> SimpleNamespace:
    return SimpleNamespace(workspace_member_id=member_id, role=role, rank_value=value, author_user_id=author_user_id)


class MemberRankResolveTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    def setUp(self) -> None:
        self.ranks = MagicMock()
        self.ranks.list_layers = AsyncMock(return_value=[])
        self.service = MemberRankService(ranks=self.ranks, members=MagicMock())
        self.session = MagicMock()

    async def _mix(self, members, roles, *, author_user_id=_HOST, ow=None):
        """Resolve under ``MIX_ORDER``, returning ``(result, fetch_mock)``.

        ``grid=None`` keeps the raw snapshot values, so a test asserts the layer
        that won rather than the division grid's rounding of it.
        """
        with patch(_FETCH, new=AsyncMock(return_value=ow or {})) as fetch:
            result = await self.service.resolve(
                self.session,
                workspace_id=1,
                members=members,
                roles=list(roles),
                order=MIX_ORDER,
                author_user_id=author_user_id,
            )
        return result, fetch

    async def test_author_beats_workspace(self) -> None:
        self.ranks.list_layers.return_value = [
            _rank(1, "tank", 2000),
            _rank(1, "tank", 3100, author_user_id=_HOST),
        ]
        result, fetch = await self._mix({1: 10}, ["tank"])
        self.assertEqual(result[(1, "tank")], ResolvedRank(3100, "author"))
        fetch.assert_not_awaited()

    async def test_workspace_beats_ow(self) -> None:
        self.ranks.list_layers.return_value = [_rank(1, "tank", 2000)]
        result, fetch = await self._mix({1: 10}, ["tank"], ow={10: {"Ana#1": {"tank": 1800}}})
        self.assertEqual(result[(1, "tank")], ResolvedRank(2000, "workspace"))
        fetch.assert_not_awaited()

    async def test_empty_author_layer_inherits_the_workspace(self) -> None:
        """Absence of a row is what makes inheritance work; a 0 would not."""
        self.ranks.list_layers.return_value = [
            _rank(1, "tank", 2000),
            _rank(1, "damage", 1900, author_user_id=_HOST),
        ]
        result, _fetch = await self._mix({1: 10}, ["tank", "damage"])
        self.assertEqual(result[(1, "tank")], ResolvedRank(2000, "workspace"))
        self.assertEqual(result[(1, "damage")], ResolvedRank(1900, "author"))

    async def test_ow_fills_what_no_stored_layer_covers(self) -> None:
        result, fetch = await self._mix({1: 10}, ["tank"], ow={10: {"Ana#1": {"tank": 1800}}})
        self.assertEqual(result[(1, "tank")], ResolvedRank(1800, "ow"))
        fetch.assert_awaited_once()
        self.assertEqual(fetch.await_args.args[1], [10])

    async def test_ow_best_account_wins(self) -> None:
        """Smurfs are one player: the strongest snapshot per role represents them."""
        result, _fetch = await self._mix(
            {1: 10},
            ["tank"],
            ow={10: {"Main#1": {"tank": 1800}, "Smurf#2": {"tank": 2900}}},
        )
        self.assertEqual(result[(1, "tank")], ResolvedRank(2900, "ow"))

    async def test_ow_not_queried_when_cheap_layers_cover_every_role(self) -> None:
        self.ranks.list_layers.return_value = [_rank(member_id, role, 2000) for member_id in (1, 2) for role in _ROLES]
        _result, fetch = await self._mix({1: 10, 2: 20}, _ROLES)
        fetch.assert_not_awaited()

    async def test_ow_queried_only_for_members_with_a_hole(self) -> None:
        self.ranks.list_layers.return_value = [_rank(1, "tank", 2000)]
        result, fetch = await self._mix({1: 10, 2: 20}, ["tank"], ow={20: {"Bob#1": {"tank": 1500}}})
        fetch.assert_awaited_once()
        self.assertEqual(fetch.await_args.args[1], [20])
        self.assertEqual(result[(1, "tank")], ResolvedRank(2000, "workspace"))
        self.assertEqual(result[(2, "tank")], ResolvedRank(1500, "ow"))

    async def test_member_without_a_player_cannot_reach_ow(self) -> None:
        result, fetch = await self._mix({3: None}, ["tank"])
        self.assertEqual(result[(3, "tank")], ResolvedRank(None, "none"))
        fetch.assert_not_awaited()

    async def test_unranked_after_every_layer_is_none(self) -> None:
        result, fetch = await self._mix({1: 10}, ["tank"], ow={10: {"Ana#1": {"damage": 1800}}})
        self.assertEqual(result[(1, "tank")], ResolvedRank(None, "none"))
        fetch.assert_awaited_once()

    async def test_no_members_touches_no_layer(self) -> None:
        result, fetch = await self._mix({}, ["tank"])
        self.assertEqual(result, {})
        self.ranks.list_layers.assert_not_awaited()
        fetch.assert_not_awaited()

    async def test_tournament_order_ignores_the_author_book(self) -> None:
        """An order that omits ``author`` must not even pay for that join."""
        self.ranks.list_layers.return_value = [_rank(1, "tank", 2000)]
        with patch(_FETCH, new=AsyncMock(return_value={})):
            result = await self.service.resolve(
                self.session,
                workspace_id=1,
                members={1: 10},
                roles=["tank", "damage"],
                order=TOURNAMENT_ORDER,
                author_user_id=_HOST,
                registration_ranks={(1, "damage"): 2600},
            )
        self.assertIsNone(self.ranks.list_layers.await_args.kwargs["author_user_id"])
        # An empty registration role inherits the canon instead of reading as unranked.
        self.assertEqual(result[(1, "tank")], ResolvedRank(2000, "workspace"))
        self.assertEqual(result[(1, "damage")], ResolvedRank(2600, "registration"))
