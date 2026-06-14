from __future__ import annotations

import importlib
import os
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

user_flows = importlib.import_module("src.services.user.flows")
enums = importlib.import_module("src.core.enums")
division_grid = importlib.import_module("shared.division_grid")
division_grid_schemas = importlib.import_module("src.schemas.division_grid")


class UserProfileFlowsTests(IsolatedAsyncioTestCase):
    async def test_get_profile_normalizes_role_division_from_tournament_grid(self) -> None:
        session = SimpleNamespace()
        user = SimpleNamespace(id=42)
        grid = division_grid.DEFAULT_GRID
        workspace_grid_version = division_grid_schemas.DivisionGridVersionRead(
            id=88,
            grid_id=15,
            version=3,
            label="Workspace grid",
            status="published",
            created_from_version_id=None,
            published_at=None,
            tiers=[
                division_grid_schemas.DivisionGridTierRead(
                    id=8801,
                    version_id=88,
                    slug="division-4",
                    number=4,
                    name="Workspace Division 4",
                    sort_order=1,
                    rank_min=0,
                    rank_max=999,
                    icon_url="/workspace-division-4.png",
                )
            ],
        )
        normalizer = SimpleNamespace(
            normalize_division=Mock(
                return_value=division_grid.DivisionTier(
                    id=8801,
                    slug="division-4",
                    number=4,
                    name="Workspace Division 4",
                    rank_min=0,
                    rank_max=999,
                    icon_url="/workspace-division-4.png",
                )
            ),
            target_grid=grid,
            source_grids_by_version_id={},
        )

        with (
            patch.object(user_flows, "get", AsyncMock(return_value=user)),
            patch.object(
                user_flows,
                "build_workspace_division_grid_normalizer",
                AsyncMock(return_value=normalizer),
            ),
            patch.object(
                user_flows,
                "get_division_grid_version",
                AsyncMock(return_value=workspace_grid_version),
            ),
            patch.object(
                user_flows.service,
                "get_overall_statistics",
                AsyncMock(return_value=(7, 3, 0.61)),
            ),
            patch.object(
                user_flows.service,
                "get_roles",
                AsyncMock(
                    return_value=[
                        (
                            enums.HeroClass.damage,
                            7,
                            3,
                            [
                                {
                                    "tournament": 12,
                                    "rank": 150,
                                    "division_grid_version_id": 77,
                                }
                            ],
                        )
                    ]
                ),
            ),
            patch.object(
                user_flows.hero_flows,
                "get_playtime",
                AsyncMock(return_value=SimpleNamespace(results=[])),
            ),
            patch.object(
                user_flows.service,
                "get_teams",
                AsyncMock(return_value=([], 0)),
            ),
        ):
            profile = await user_flows.get_profile(session, 42, workspace_id=5, grid=grid)

        self.assertEqual(1, len(profile.roles))
        self.assertEqual(enums.HeroClass.damage, profile.roles[0].role)
        self.assertEqual(4, profile.roles[0].division)
        self.assertIsNotNone(profile.roles[0].division_grid_version)
        self.assertEqual(88, profile.roles[0].division_grid_version.id)
        self.assertEqual("/workspace-division-4.png", profile.roles[0].division_grid_version.tiers[0].icon_url)
        normalizer.normalize_division.assert_called_once_with(77, 150)

    async def test_get_tournaments_keeps_tournament_specific_division_grid(self) -> None:
        session = SimpleNamespace()
        user = SimpleNamespace(id=42)
        tournament_grid_version = division_grid_schemas.DivisionGridVersionRead(
            id=77,
            grid_id=12,
            version=2,
            label="Tournament grid",
            status="published",
            created_from_version_id=None,
            published_at=None,
            tiers=[
                division_grid_schemas.DivisionGridTierRead(
                    id=7701,
                    version_id=77,
                    slug="division-1",
                    number=1,
                    name="Division 1",
                    sort_order=1,
                    rank_min=2000,
                    rank_max=None,
                    icon_url="/division-1.png",
                ),
                division_grid_schemas.DivisionGridTierRead(
                    id=7702,
                    version_id=77,
                    slug="division-9",
                    number=9,
                    name="Division 9",
                    sort_order=2,
                    rank_min=1000,
                    rank_max=1999,
                    icon_url="/division-9.png",
                ),
                division_grid_schemas.DivisionGridTierRead(
                    id=7703,
                    version_id=77,
                    slug="division-15",
                    number=15,
                    name="Division 15",
                    sort_order=3,
                    rank_min=0,
                    rank_max=999,
                    icon_url="/division-15.png",
                ),
            ],
        )
        player = SimpleNamespace(user_id=42, role=enums.HeroClass.damage, rank=1500)
        standing = SimpleNamespace(overall_position=2, win=3, lose=1, draw=0)
        team = SimpleNamespace(
            id=9,
            name="Team Example",
            tournament_id=3,
            players=[player],
            standings=[standing],
            tournament=SimpleNamespace(
                id=3,
                number=12,
                name="Tournament Example",
                is_league=False,
                division_grid_version=tournament_grid_version,
            ),
        )

        with (
            patch.object(user_flows, "get", AsyncMock(return_value=user)),
            patch.object(
                user_flows.service,
                "get_tournaments_with_stats",
                AsyncMock(return_value=[(team, 4, 2, 0.75)]),
            ),
            patch.object(
                user_flows.encounter_service,
                "get_by_user_with_teams",
                AsyncMock(return_value=[]),
            ),
            patch.object(
                user_flows.team_service,
                "get_team_count_by_tournament_bulk",
                AsyncMock(return_value={3: 8}),
            ),
            patch.object(
                user_flows.team_flows,
                "to_pydantic_player",
                AsyncMock(
                    return_value=user_flows.schemas.PlayerRead.model_construct(
                        id=91,
                        name="Player Example",
                        sub_role=None,
                        rank=1500,
                        division=9,
                        role=enums.HeroClass.damage.value,
                        tournament_id=3,
                        user_id=42,
                        team_id=9,
                        is_newcomer=False,
                        is_newcomer_role=False,
                        is_substitution=False,
                        related_player_id=None,
                        tournament=None,
                        team=None,
                        user=None,
                    )
                ),
            ),
        ):
            tournaments = await user_flows.get_tournaments(
                session,
                42,
                workspace_id=5,
                grid=division_grid.DEFAULT_GRID,
            )

        self.assertEqual(1, len(tournaments))
        self.assertEqual(9, tournaments[0].division)
        self.assertIsNotNone(tournaments[0].division_grid_version)
        self.assertEqual(77, tournaments[0].division_grid_version.id)

    async def test_get_tournaments_uses_best_positive_team_placement(self) -> None:
        session = SimpleNamespace()
        user = SimpleNamespace(id=42)
        player = SimpleNamespace(user_id=42, role=enums.HeroClass.damage, rank=1500)
        team = SimpleNamespace(
            id=9,
            name="Team Example",
            tournament_id=3,
            players=[player],
            standings=[
                SimpleNamespace(overall_position=0, win=0, lose=0, draw=0),
                SimpleNamespace(overall_position=3, win=3, lose=1, draw=0),
            ],
            tournament=SimpleNamespace(
                id=3,
                number=12,
                name="Tournament Example",
                is_league=False,
                division_grid_version=None,
            ),
        )

        with (
            patch.object(user_flows, "get", AsyncMock(return_value=user)),
            patch.object(
                user_flows.service,
                "get_tournaments_with_stats",
                AsyncMock(return_value=[(team, 4, 2, 0.75)]),
            ),
            patch.object(
                user_flows.encounter_service,
                "get_by_user_with_teams",
                AsyncMock(return_value=[]),
            ),
            patch.object(
                user_flows.team_service,
                "get_team_count_by_tournament_bulk",
                AsyncMock(return_value={3: 8}),
            ),
            patch.object(
                user_flows.team_flows,
                "to_pydantic_player",
                AsyncMock(
                    return_value=user_flows.schemas.PlayerRead.model_construct(
                        id=91,
                        name="Player Example",
                        sub_role=None,
                        rank=1500,
                        division=9,
                        role=enums.HeroClass.damage.value,
                        tournament_id=3,
                        user_id=42,
                        team_id=9,
                        is_newcomer=False,
                        is_newcomer_role=False,
                        is_substitution=False,
                        related_player_id=None,
                        tournament=None,
                        team=None,
                        user=None,
                    )
                ),
            ),
        ):
            tournaments = await user_flows.get_tournaments(
                session,
                42,
                workspace_id=5,
                grid=division_grid.DEFAULT_GRID,
            )

        self.assertEqual(1, len(tournaments))
        self.assertEqual(3, tournaments[0].placement)
