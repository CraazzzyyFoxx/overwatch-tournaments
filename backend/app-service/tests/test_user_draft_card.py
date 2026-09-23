"""Coverage for the draft room's player card (`rpc.app.users.draft_card`).

The assembly tests mock every query behind the card: what they cover is the
slot-code vocabulary the draft room speaks, the ordering and cut-offs promised by
the contract, and the "no history is zeros, not a 404" rule. The last test builds
the two new aggregates for real and asserts they never span workspaces.
"""

from __future__ import annotations

import contextlib
import datetime
import importlib
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from sqlalchemy.dialects import postgresql

user_flows = importlib.import_module("src.services.user.service")
enums = importlib.import_module("src.core.enums")
queries = importlib.import_module("src.services.user.queries.encounters")


def _hero(hero_id: int, slug: str, hero_type: enums.HeroClass) -> SimpleNamespace:
    return SimpleNamespace(
        id=hero_id,
        slug=slug,
        name=slug.capitalize(),
        image_path=f"/heroes/{slug}.png",
        type=hero_type,
        color="#ffffff",
        aliases=[],
    )


def _team(tournament_id: int, *, placement: int | None, is_league: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        tournament_id=tournament_id,
        tournament=SimpleNamespace(
            id=tournament_id,
            name=f"OWT Mix #{tournament_id}",
            is_league=is_league,
            start_date=datetime.datetime(2026, 1, tournament_id, tzinfo=datetime.timezone.utc),
        ),
        standings=[SimpleNamespace(overall_position=placement or 0)],
    )


@contextlib.contextmanager
def _queries(
    user_id: int,
    *,
    overall: tuple[int, int, float] | None = None,
    roles: list | None = None,
    teams: list | None = None,
    heroes: list | None = None,
    mvp_maps: int = 0,
    teams_counts: dict[int, int] | None = None,
    hero_records: AsyncMock | None = None,
):
    """Stand in for every query behind the card; ids differ per test so the
    decorator's cache never serves one test's card to another."""
    with (
        patch.object(user_flows.users, "get", AsyncMock(return_value=SimpleNamespace(id=user_id))),
        patch.object(user_flows.users.profile, "get_overall_statistics", AsyncMock(return_value=overall)),
        patch.object(user_flows.users.profile, "get_roles", AsyncMock(return_value=roles or [])),
        patch.object(
            user_flows.users.profile, "get_teams", AsyncMock(return_value=(teams or [], len(teams or [])))
        ),
        patch.object(
            user_flows.users.encounters,
            "get_user_hero_records",
            hero_records or AsyncMock(return_value=heroes or []),
        ),
        patch.object(user_flows.users.encounters, "count_user_mvp_maps", AsyncMock(return_value=mvp_maps)),
        patch.object(
            user_flows.users.encounters,
            "count_teams_by_tournament_bulk",
            AsyncMock(return_value=teams_counts or {}),
        ),
    ):
        yield


class UserDraftCardTests(IsolatedAsyncioTestCase):
    async def test_player_without_history_gets_a_card_of_zeros(self) -> None:
        """The draft room opens on players who have never played: the card must be
        zeros and empty lists, never the 404 an empty-history guard would raise."""
        with _queries(101):
            card = await user_flows.users.get_draft_card(object(), 101, workspace_id=1)

        self.assertEqual(0, card.tournaments)
        self.assertEqual(0, card.tournaments_won)
        self.assertEqual((0, 0, 0), (card.maps, card.maps_won, card.maps_lost))
        self.assertIsNone(card.best_placement)
        self.assertIsNone(card.avg_placement)
        self.assertEqual([], card.roles)
        self.assertEqual([], card.heroes)
        self.assertEqual([], card.recent_tournaments)

    async def test_heroes_are_the_ranking_verbatim_with_slot_code_roles(self) -> None:
        """`heroes` is the query's ranking verbatim (most maps first) and the hero's
        class is emitted as a draft slot code, not the `HeroClass` value."""
        records = AsyncMock(
            return_value=[
                (_hero(1, "ashe", enums.HeroClass.damage), 76, 46),
                (_hero(2, "ana", enums.HeroClass.support), 40, 20),
                (_hero(3, "dva", enums.HeroClass.tank), 12, 5),
            ]
        )
        with _queries(102, overall=(67, 60, 0.5), mvp_maps=6, hero_records=records):
            card = await user_flows.users.get_draft_card(object(), 102, workspace_id=1)

        self.assertEqual(["ashe", "ana", "dva"], [entry.hero.slug for entry in card.heroes])
        self.assertEqual([76, 40, 12], [entry.maps for entry in card.heroes])
        self.assertEqual([46, 20, 5], [entry.maps_won for entry in card.heroes])
        self.assertEqual(["damage", "support", "tank"], [entry.role for entry in card.heroes])
        self.assertEqual(127, card.maps)
        self.assertEqual(6, card.mvp_maps)

    async def test_recent_tournaments_are_newest_first_capped_at_five(self) -> None:
        """Newest first, at most five, each carrying the placement, roster size and
        the role/rank the player held there — while the totals still span the whole
        history."""
        roles = [
            (
                enums.HeroClass.damage,
                40,
                20,
                [{"tournament": tid, "rank": 3700 + tid, "division_grid_version_id": None} for tid in range(1, 8)],
            )
        ]
        with _queries(
            103,
            overall=(40, 20, 0.5),
            roles=roles,
            teams=[_team(tid, placement=tid) for tid in range(1, 8)],
            teams_counts={tid: 24 for tid in range(1, 8)},
        ):
            card = await user_flows.users.get_draft_card(object(), 103, workspace_id=1)

        self.assertEqual([7, 6, 5, 4, 3], [entry.id for entry in card.recent_tournaments])
        self.assertEqual([7, 6, 5, 4, 3], [entry.placement for entry in card.recent_tournaments])
        self.assertEqual([24] * 5, [entry.teams_count for entry in card.recent_tournaments])
        self.assertEqual(3707, card.recent_tournaments[0].rank)
        self.assertEqual("damage", card.recent_tournaments[0].role)
        self.assertEqual(datetime.date(2026, 1, 7), card.recent_tournaments[0].date)
        self.assertEqual(7, card.tournaments)
        self.assertEqual(1, card.tournaments_won)
        self.assertEqual(1, card.best_placement)
        self.assertEqual(4.0, card.avg_placement)
        self.assertEqual(
            [{"role": "damage", "maps": 60, "maps_won": 40}],
            [entry.model_dump() for entry in card.roles],
        )

    async def test_leagues_never_reach_the_card(self) -> None:
        """A league has no bracket and no placement; counting it would make the
        card's tournament and placement numbers disagree with each other."""
        with _queries(
            104,
            overall=(10, 5, 0.5),
            teams=[_team(2, placement=3), _team(9, placement=None, is_league=True)],
            teams_counts={2: 16},
        ):
            card = await user_flows.users.get_draft_card(object(), 104, workspace_id=1)

        self.assertEqual(1, card.tournaments)
        self.assertEqual([2], [entry.id for entry in card.recent_tournaments])


class DraftCardQueryScopeTests(IsolatedAsyncioTestCase):
    """The card is served to a workspace's draft room; an aggregate that forgot
    its workspace filter would sum a player's record across every tenant."""

    class _EmptyResult:
        def __iter__(self):
            return iter(())

        def scalar_one(self) -> int:
            return 0

    class _CaptureSession:
        def __init__(self) -> None:
            self.statements: list = []

        async def execute(self, statement):
            self.statements.append(statement)
            return DraftCardQueryScopeTests._EmptyResult()

    async def _compiled(self, coroutine_factory) -> str:
        session = self._CaptureSession()
        await coroutine_factory(session)
        return str(
            session.statements[0].compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )

    async def test_hero_records_are_workspace_scoped(self) -> None:
        sql = await self._compiled(
            lambda session: queries.encounters.get_user_hero_records(session, 7, workspace_id=2)
        )
        self.assertIn("tournament.workspace_id = 2", sql)

    async def test_mvp_map_count_is_workspace_scoped(self) -> None:
        sql = await self._compiled(
            lambda session: queries.encounters.count_user_mvp_maps(session, 7, workspace_id=2)
        )
        self.assertIn("tournament.workspace_id = 2", sql)
