"""The team writer's Player-creation site must populate ``workspace_member_id`` so workspace-scoped analytics
readers that INNER-JOIN on it don't silently drop newly created roster rows.

Exercised through balancer-service's adapter (``to_materialization_teams``) so both the payload mapping and the
writer stay covered.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from shared.domain.team_format import FormatDimension, TeamFormat  # noqa: E402
from shared.models.catalog.role import CatalogRole, RoleDimension  # noqa: E402
from shared.models.tournament.team import Player, Team  # noqa: E402
from shared.schemas.role import RoleRef  # noqa: E402
from shared.tests.test_team_format import _module_ontology  # noqa: E402
from src.schemas.team import BalancerTeam, BalancerTeamMember  # noqa: E402
from src.services.team import to_materialization_teams  # noqa: E402
from src.services.team_export import materialization as materialization_module  # noqa: E402


def _scalar_result(value):
    result = Mock()
    result.scalar_one_or_none.return_value = value
    return result


def _scalars_all_result(items):
    scalars = Mock()
    scalars.all.return_value = items
    result = Mock()
    result.scalars.return_value = scalars
    return result


def _rows_result(rows):
    result = Mock()
    result.all.return_value = rows
    return result


class MaterializeTeamsWorkspaceMemberTests(IsolatedAsyncioTestCase):
    async def test_new_player_gets_workspace_member_id(self) -> None:
        tournament = SimpleNamespace(
            id=88,
            workspace_id=55,
            start_date=None,
            end_date=None,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            discipline="overwatch",
        )
        member_user = SimpleNamespace(id=42)
        created_team = SimpleNamespace(id=3, name="Roster", tournament_id=88)
        created_member = SimpleNamespace(id=9001)

        # Batched execute() call order inside materialize_teams:
        # 1) load tournament (scalar),
        # 2) existing teams by name (scalars.all -> []),
        # 3) load_prior_participation: workspace.newcomer_scope lookup (scalar),
        # 4) load_prior_participation: prior-participation rows (rows.all -> [] newcomer),
        # 5) player facts over workspace_member join (rows.all -> [] not in tournament),
        # 6) existing workspace members (scalars.all -> []).
        session = SimpleNamespace(
            execute=AsyncMock(
                side_effect=[
                    _scalar_result(tournament),
                    _scalars_all_result([]),
                    _scalar_result("global"),
                    _rows_result([]),
                    _rows_result([]),
                    _scalars_all_result([]),
                ]
            ),
            add=Mock(),
            flush=AsyncMock(),
            commit=AsyncMock(),
        )

        def fake_add(entity):
            if isinstance(entity, Team):
                entity.id = created_team.id
                entity.name = created_team.name

        session.add.side_effect = fake_add

        payload = [
            BalancerTeam(
                uuid=uuid4(),
                avgSr=3000,
                name="Roster#0000",
                totalSr=3000,
                members=[
                    BalancerTeamMember(
                        uuid=uuid4(),
                        name="Roster#0000",
                        role=RoleRef(dimension="player_role", role="tank"),
                        rank=3000,
                    )
                ],
            )
        ]

        with (
            patch.object(
                materialization_module,
                "tournament_format",
                AsyncMock(
                    return_value=(
                        TeamFormat("overwatch", "Solo", 1, 1, dimensions=(FormatDimension("player_role", "enforced"),)),
                        "preset",
                    )
                ),
            ),
            patch.object(
                materialization_module.CatalogRoleRepository,
                "ontology",
                AsyncMock(return_value=_module_ontology("overwatch")),
            ),
            patch.object(
                materialization_module,
                "find_users_by_handles",
                AsyncMock(return_value={"Roster#0000": member_user}),
            ),
            patch.object(
                materialization_module,
                "get_or_create_workspace_member",
                AsyncMock(return_value=created_member),
            ) as get_or_create,
            patch.object(
                materialization_module,
                "resolve_role_ref",
                AsyncMock(
                    return_value=CatalogRole(
                        id=101,
                        dimension_id=1,
                        code="tank",
                        dimension=RoleDimension(id=1, discipline="overwatch", code="player_role", rated=True),
                    )
                ),
            ),
        ):
            await materialization_module.materialize_teams(session, 88, 99, to_materialization_teams(payload))

        get_or_create.assert_awaited_once_with(session, workspace_id=55, player_id=42)
        player_calls = [call.args[0] for call in session.add.call_args_list if isinstance(call.args[0], Player)]
        self.assertEqual(1, len(player_calls))
        created_player = player_calls[0]
        self.assertFalse(hasattr(created_player, "user_id"))
        self.assertEqual(9001, created_player.workspace_member_id)
        self.assertTrue(created_player.is_newcomer)
        self.assertTrue(created_player.is_newcomer_role)
        # The writer never commits — the orchestrator owns the boundary.
        session.commit.assert_not_awaited()
