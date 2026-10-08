"""``rpc.balancer.ranks.list`` and the UNION behind it.

Three things are worth pinning. (1) Every one of the nine layers actually
reaches the wire -- a branch that silently drops out of the union looks exactly
like "this member has no such rank". (2) The two *effective* layers are computed
in SQL, so they can drift away from ``MemberRankService.resolve`` -- the
resolver every real balance runs on -- without anything else failing; the parity
test runs both on the same fixture. (3) The read is admin-only: it puts every
author's private book on one screen.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"
for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

os.environ["DEBUG"] = "false"

import sqlalchemy as sa  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker  # noqa: E402

from shared import models  # noqa: E402
from shared.core import enums  # noqa: E402
from shared.core.social import SocialProvider  # noqa: E402
from shared.division_grid import DivisionGrid  # noqa: E402
from shared.services.division_grid.access import get_effective_division_grid  # noqa: E402
from shared.services.member_rank import MIX_ORDER, TOURNAMENT_ORDER, member_rank_service  # noqa: E402
from shared.testing import create_test_async_engine, division_grid  # noqa: E402
from src.rpc import ranks as ranks_rpc  # noqa: E402
from src.schemas.ranks import LAYERS  # noqa: E402
from src.services.rank_overview import (  # noqa: E402
    RankOverviewFilters,
    _grid_rank_case,
    rank_overview_page,
)

SUBJECT = "rpc.balancer.ranks.list"
WORKSPACE_ID = 9
ROLES = ("tank", "damage", "support")


class _CapturingBroker:
    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}

    def subscriber(self, subject: str):
        def decorator(function):
            self.handlers[subject] = function
            return function

        return decorator


class _FakeLogger:
    def warning(self, *args, **kwargs) -> None:
        return None

    def exception(self, *args, **kwargs) -> None:
        return None


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> bool:
        return False


def _identity(workspace_id: int, role: str, *permissions: tuple[str, str]) -> dict:
    """A rehydrated workspace identity. ``role`` matters: a workspace ``admin``
    is granted everything non-governance regardless of its permission list, so
    the forbidden cases have to be a non-admin role."""
    return {
        "user_id": 501,
        "is_superuser": False,
        "is_active": True,
        "roles": [],
        "permissions": [],
        "workspaces": [
            {
                "workspace_id": workspace_id,
                "role": role,
                "rbac_roles": [role],
                "rbac_permissions": [{"resource": resource, "action": action} for resource, action in permissions],
            }
        ],
    }


class RankOverviewPermissionTests(IsolatedAsyncioTestCase):
    """``team.update``, the same grant writing the canon needs."""

    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    async def _call(self, identity: dict) -> dict:
        broker = _CapturingBroker()
        ranks_rpc.register(broker, _FakeLogger())
        self.page = AsyncMock(return_value=([], 0))
        with (
            patch.object(ranks_rpc, "_SF", _FakeSession),
            patch.object(ranks_rpc, "rank_overview_page", self.page),
        ):
            return await broker.handlers[SUBJECT]({"workspace_id": WORKSPACE_ID, "identity": identity}, None)

    async def test_team_update_may_read(self) -> None:
        response = await self._call(_identity(WORKSPACE_ID, "organizer", ("team", "read"), ("team", "update")))
        assert response["ok"] is True, response
        assert response["data"]["results"] == []
        self.page.assert_awaited_once()

    async def test_read_without_team_update_is_forbidden(self) -> None:
        response = await self._call(_identity(WORKSPACE_ID, "host", ("team", "read"), ("custom_game", "create")))
        assert response["ok"] is False
        assert response["error"]["code"] == "forbidden"
        self.page.assert_not_awaited()

    async def test_member_of_another_workspace_is_forbidden(self) -> None:
        response = await self._call(_identity(WORKSPACE_ID + 999_999, "organizer", ("team", "update")))
        assert response["ok"] is False
        assert response["error"]["code"] == "forbidden"
        self.page.assert_not_awaited()


class GridRankCaseTests(IsolatedAsyncioTestCase):
    """``_grid_rank_case`` is the SQL twin of ``resolve_division_from_ow_rank``.

    Both regimes: a grid with no OW mapping configured places the raw SR by
    plain rank containment (and never misses), one with an explicit mapping
    drops anything outside it. Evaluated by Postgres, since that is the engine
    whose answer has to match.
    """

    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    async def asyncSetUp(self) -> None:
        self.engine = create_test_async_engine()
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def _mapped(self, grid, sr: int | None) -> int | None:
        value = sa.cast(sa.literal(sr), sa.Integer) if sr is not None else sa.cast(sa.null(), sa.Integer)
        async with self.Session() as session:
            return await session.scalar(sa.select(_grid_rank_case(value, grid)))

    async def test_unmapped_grid_places_every_sr_by_rank_containment(self) -> None:
        grid = division_grid(1, ((10, 3, 3000, None), (11, 2, 2000, 2999), (12, 1, 1000, 1999)))
        for sr in (500, 1500, 2500, 4000):
            expected = grid.resolve_division_from_ow_rank(sr)
            assert expected is not None
            assert await self._mapped(grid, sr) == expected.rank_min, sr

    async def test_configured_grid_drops_sr_outside_every_range(self) -> None:
        base = division_grid(1, ((10, 3, 3000, None), (11, 2, 2000, 2999), (12, 1, 1000, 1999)))
        tiers = tuple(
            replace(tier, ow_rank_min=tier.rank_min, ow_rank_max=tier.rank_max or 9999) for tier in base.tiers
        )
        grid = DivisionGrid(version_id=2, tiers=tiers)
        assert await self._mapped(grid, 2500) == 2000
        assert grid.resolve_division_from_ow_rank(500) is None
        assert await self._mapped(grid, 500) is None

    async def test_no_ow_rank_at_all_maps_to_nothing(self) -> None:
        """Regression: an OUTER JOIN miss must not fall through to the lowest
        tier, which would invent a rank for a role the player never placed in."""
        grid = division_grid(1, ((10, 3, 3000, None), (11, 2, 2000, 2999), (12, 1, 1000, 1999)))
        assert await self._mapped(grid, None) is None


class RankOverviewQueryTests(IsolatedAsyncioTestCase):
    """The union itself, against a real Postgres."""

    if sys.platform == "win32":
        # psycopg async cannot run on the Proactor loop (Windows default).
        loop_factory = asyncio.SelectorEventLoop

    async def asyncSetUp(self) -> None:
        self.engine = create_test_async_engine()
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        suffix = f"rankov-{os.getpid()}"
        async with self.Session() as s:
            author = models.AuthUser(
                email=f"{suffix}@example.test", username=f"author-{suffix}", is_active=True, is_verified=True
            )
            s.add(author)
            player = models.User(name=f"Player {suffix}")
            s.add(player)
            await s.flush()

            workspace = models.Workspace(slug=f"ws-{suffix}", name=f"WS {suffix}")
            s.add(workspace)
            await s.flush()
            member = models.WorkspaceMember(workspace_id=workspace.id, player_id=player.id, display_name="Parity")
            s.add(member)
            await s.flush()

            # canon: tank only, so damage has to fall through to OW.
            s.add(
                models.MemberRank(
                    workspace_id=workspace.id, workspace_member_id=member.id, role="tank", rank_value=2500
                )
            )
            # the author's own book: tank corrected upward, support invented.
            s.add_all(
                [
                    models.MemberRank(
                        workspace_id=workspace.id,
                        workspace_member_id=member.id,
                        author_user_id=author.id,
                        role="tank",
                        rank_value=2700,
                    ),
                    models.MemberRank(
                        workspace_id=workspace.id,
                        workspace_member_id=member.id,
                        author_user_id=author.id,
                        role="support",
                        rank_value=1800,
                    ),
                ]
            )
            s.add(
                models.MemberHiddenRating(
                    workspace_id=workspace.id, workspace_member_id=member.id, role="tank", mu=2345.6, sigma=120.5
                )
            )

            account = models.SocialAccount(
                user_id=player.id,
                provider=SocialProvider.BATTLENET,
                username=f"Parity#{os.getpid() % 10000:04d}",
                username_normalized=f"parity#{os.getpid() % 10000:04d}",
                is_primary=True,
            )
            s.add(account)
            await s.flush()
            s.add(
                models.BattleTagRankState(
                    social_account_id=account.id,
                    battle_tag=account.username,
                    player_id_slug=account.username.replace("#", "-"),
                    last_success_at=datetime.now(UTC),
                )
            )
            captured = datetime.now(UTC) - timedelta(days=1)
            s.add_all(
                [
                    models.UserRankSnapshot(
                        user_id=player.id,
                        social_account_id=account.id,
                        battle_tag=account.username,
                        platform="pc",
                        role="tank",
                        division="grandmaster",
                        tier=3,
                        rank_value=3000,
                        is_ranked=True,
                        captured_at=captured,
                    ),
                    models.UserRankSnapshot(
                        user_id=player.id,
                        social_account_id=account.id,
                        battle_tag=account.username,
                        platform="pc",
                        role="damage",
                        division="platinum",
                        tier=1,
                        rank_value=2000,
                        is_ranked=True,
                        captured_at=captured,
                    ),
                    # Newest support row is unranked: the role has no rank now,
                    # however high the older one was.
                    models.UserRankSnapshot(
                        user_id=player.id,
                        social_account_id=account.id,
                        battle_tag=account.username,
                        platform="pc",
                        role="support",
                        rank_value=2600,
                        is_ranked=True,
                        captured_at=captured - timedelta(days=2),
                    ),
                    models.UserRankSnapshot(
                        user_id=player.id,
                        social_account_id=account.id,
                        battle_tag=account.username,
                        platform="pc",
                        role="support",
                        rank_value=None,
                        is_ranked=False,
                        captured_at=captured,
                    ),
                ]
            )

            tournament = models.Tournament(
                workspace_id=workspace.id, name=f"T {suffix}", slug=f"t-{suffix}", is_hidden=True
            )
            s.add(tournament)
            await s.flush()
            registration = models.BalancerRegistration(
                tournament_id=tournament.id, workspace_member_id=member.id, display_name="Parity"
            )
            s.add(registration)
            await s.flush()
            s.add(models.BalancerRegistrationRole(registration_id=registration.id, role="tank", rank_value=2200))
            team = models.Team(tournament_id=tournament.id, name=f"Team {suffix}", balancer_name=f"Team {suffix}")
            s.add(team)
            await s.flush()
            s.add(
                models.Player(
                    name="Parity",
                    rank=2100,
                    role=enums.HeroClass.tank,
                    tournament_id=tournament.id,
                    team_id=team.id,
                    workspace_member_id=member.id,
                )
            )

            game = models.CustomGame(workspace_id=workspace.id, host_user_id=author.id, name=f"Mix {suffix}")
            s.add(game)
            await s.flush()
            match = models.CasualMatch(custom_game_id=game.id, lobby_index=1, points_per_win_applied=25)
            s.add(match)
            await s.flush()
            home = models.CasualTeam(match_id=match.id, side="home", name="Home", score=2)
            away = models.CasualTeam(match_id=match.id, side="away", name="Away", score=1)
            s.add_all([home, away])
            await s.flush()
            s.add(
                models.CasualPlayer(
                    team_id=home.id,
                    workspace_member_id=member.id,
                    display_name_snapshot="Parity",
                    role=enums.HeroClass.tank,
                    rank=2050,
                )
            )
            await s.commit()

            self.workspace_id = workspace.id
            self.member_id = member.id
            self.player_id = player.id
            self.auth_user_id = author.id
            self.tournament_id = tournament.id
            self.battle_tag = account.username

    async def asyncTearDown(self) -> None:
        if not hasattr(self, "Session"):
            await self.engine.dispose()
            return
        async with self.Session() as s:
            await s.execute(sa.delete(models.Tournament).where(models.Tournament.id == self.tournament_id))
            await s.execute(sa.delete(models.Workspace).where(models.Workspace.id == self.workspace_id))
            await s.execute(sa.delete(models.User).where(models.User.id == self.player_id))
            await s.execute(sa.delete(models.AuthUser).where(models.AuthUser.id == self.auth_user_id))
            await s.commit()
        await self.engine.dispose()

    async def _page(self, **overrides) -> tuple[list[dict], int]:
        overrides.setdefault("layers", LAYERS)
        overrides.setdefault("per_page", 200)
        async with self.Session() as session:
            return await rank_overview_page(
                session, workspace_id=self.workspace_id, filters=RankOverviewFilters(**overrides)
            )

    async def test_every_layer_reaches_the_wire(self) -> None:
        rows, total = await self._page()
        assert total == len(rows)
        assert {row["layer"] for row in rows} == set(LAYERS)
        # Every row carries a division resolved on the workspace grid.
        assert all(row["division"] is not None for row in rows)

    async def test_per_layer_payloads(self) -> None:
        rows, _ = await self._page()
        by_layer: dict[str, list[dict]] = {}
        for row in rows:
            by_layer.setdefault(row["layer"], []).append(row)

        canon = by_layer["canon"]
        assert [(r["role"], r["rank_value"]) for r in canon] == [("tank", 2500)]
        assert canon[0]["author_user_id"] is None

        author = {r["role"]: r for r in by_layer["author"]}
        assert author["tank"]["rank_value"] == 2700
        assert author["tank"]["canon_diff"] == 200
        # No canon for support, so there is nothing to differ from.
        assert author["support"]["canon_diff"] is None
        assert author["tank"]["author_user_id"] == self.auth_user_id
        assert author["tank"]["author_name"]

        ow = {r["role"]: r for r in by_layer["ow"]}
        assert set(ow) == {"tank", "damage"}, "an unranked newest row means the role has no rank"
        assert ow["tank"]["rank_value"] == 3000
        assert ow["tank"]["ow_division"] == "grandmaster"
        assert ow["tank"]["ow_tier"] == 3
        assert ow["tank"]["context"] == {
            "kind": "battle_tag",
            "id": None,
            "label": self.battle_tag,
            "team": "pc",
            "lobby_index": None,
        }

        hidden = by_layer["hidden"][0]
        assert hidden["rank_value"] == 2346
        assert hidden["sigma"] == 120.5

        registration = by_layer["registration"][0]
        assert registration["rank_value"] == 2200
        assert registration["context"]["kind"] == "tournament"
        assert registration["context"]["id"] == self.tournament_id

        roster = by_layer["tournament"][0]
        assert roster["rank_value"] == 2100
        assert roster["context"]["team"]

        casual = by_layer["casual"][0]
        assert casual["rank_value"] == 2050
        # Home won by 2:1 and the match was recorded in points mode.
        assert casual["delta"] == 25
        assert casual["context"]["kind"] == "mix"
        assert casual["context"]["lobby_index"] == 1
        assert casual["author_user_id"] == self.auth_user_id
        assert casual["at"] is not None

    async def test_effective_tournament_matches_the_resolver(self) -> None:
        rows, _ = await self._page(layers=("effective_tournament",))
        async with self.Session() as session:
            grid = await get_effective_division_grid(session, self.workspace_id)
            resolved = await member_rank_service.resolve(
                session,
                workspace_id=self.workspace_id,
                members={self.member_id: self.player_id},
                roles=ROLES,
                order=TOURNAMENT_ORDER,
                grid=grid,
            )
        assert _as_pairs(rows, self.member_id) == _resolver_pairs(resolved)

    async def test_effective_mix_matches_the_resolver(self) -> None:
        rows, _ = await self._page(layers=("effective_mix",))
        assert {row["author_user_id"] for row in rows} == {self.auth_user_id}
        async with self.Session() as session:
            grid = await get_effective_division_grid(session, None)
            resolved = await member_rank_service.resolve(
                session,
                workspace_id=self.workspace_id,
                members={self.member_id: self.player_id},
                roles=ROLES,
                order=MIX_ORDER,
                author_user_id=self.auth_user_id,
                grid=grid,
            )
        assert _as_pairs(rows, self.member_id) == _resolver_pairs(resolved)

    async def test_differs_from_canon_keeps_only_author_rows(self) -> None:
        rows, total = await self._page(differs_from_canon=True)
        assert total == len(rows)
        assert {row["layer"] for row in rows} == {"author"}
        # tank differs by 200, support has no canon at all; neither is 0.
        assert {row["role"] for row in rows} == {"tank", "support"}

        async with self.Session() as session:
            await session.execute(
                sa.update(models.MemberRank)
                .where(
                    models.MemberRank.workspace_member_id == self.member_id,
                    models.MemberRank.author_user_id == self.auth_user_id,
                    models.MemberRank.role == "tank",
                )
                .values(rank_value=2500)
            )
            await session.commit()
        rows, _ = await self._page(differs_from_canon=True)
        assert {row["role"] for row in rows} == {"support"}

    async def test_filters_and_paging(self) -> None:
        rows, total = await self._page(layers=("ow",), roles=("tank",))
        assert total == 1 and rows[0]["rank_value"] == 3000

        _rows, total = await self._page(rank_min=2600)
        assert total == len([r for r in (await self._page())[0] if r["rank_value"] >= 2600])

        first, total = await self._page(sort="rank_value", order="desc", per_page=1, page=1)
        second, _ = await self._page(sort="rank_value", order="desc", per_page=1, page=2)
        assert total > 2
        assert first[0]["rank_value"] >= second[0]["rank_value"]
        assert first[0] != second[0]

        empty, total = await self._page(player_id=self.player_id + 10_000_000)
        assert (empty, total) == ([], 0)

    async def test_handler_answers_a_json_serializable_envelope(self) -> None:
        """The whole RPC path: query parsing, the union, and the wire body.

        Nothing downstream re-encodes the handler's dict, so a stray ``datetime``
        in it only fails when the broker tries to publish the reply.
        """
        broker = _CapturingBroker()
        ranks_rpc.register(broker, _FakeLogger())
        data = {
            "workspace_id": self.workspace_id,
            "identity": _identity(self.workspace_id, "organizer", ("team", "update")),
            "query": {
                "layer": ["canon", "casual"],
                "role": ["tank"],
                "sort": ["rank_value"],
                "order": ["desc"],
                "per_page": ["5"],
            },
        }
        with patch.object(ranks_rpc, "_SF", self.Session):
            response = await broker.handlers[SUBJECT](data, None)
        assert response["ok"] is True, response
        body = response["data"]
        assert (body["page"], body["per_page"]) == (1, 5)
        assert {row["layer"] for row in body["results"]} == {"canon", "casual"}
        assert body["total"] == len(body["results"]) == 2
        json.dumps(body)


def _as_pairs(rows: list[dict], member_id: int) -> dict[str, tuple[int, str]]:
    return {row["role"]: (row["rank_value"], row["source"]) for row in rows if row["member_id"] == member_id}


def _resolver_pairs(resolved: dict) -> dict[str, tuple[int, str]]:
    return {role: (rank.value, rank.source) for (_member, role), rank in resolved.items() if rank.value is not None}


def test_handler_is_registered() -> None:
    broker = _CapturingBroker()
    ranks_rpc.register(broker, _FakeLogger())
    assert SUBJECT in broker.handlers
