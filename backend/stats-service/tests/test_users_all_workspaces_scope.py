"""The public ``/users`` surface can be read across every workspace on purpose.

``?workspace_id=all`` is the opt-in: it resolves to the ``ALL_WORKSPACES``
sentinel, so the read is unfiltered *deliberately* while a missing
``workspace_id`` still fails closed with 400 (cross-tenant leak guard).

In that mode there is no single workspace grid to normalize ranks onto: the
same rank is a different division in different grids. Every role instead
reports its canonical number on the game's native ladder (resolved in SQL from
its own tournament's effective grid), which is no stored grid version, so the
response ships no grids.

Postgres-backed assertions live with the integration suites; these cover pure
scope parsing and division resolution with cached grid loaders stubbed.
"""

from __future__ import annotations

import importlib
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

import pytest

from shared.core.errors import BaseAPIException
from shared.division_grid import DEFAULT_GRID
from shared.rpc import common as rpc_common
from shared.rpc.query import build_query_model
from shared.schemas.role import RoleRef
from shared.services.division_grid.normalization import DivisionGridNormalizer
from shared.services.workspace_scope import ALL_WORKSPACES
from shared.testing.factories import division_grid as make_grid
from src import schemas

user_rpc = importlib.import_module("src.rpc.users")
user_service = importlib.import_module("src.services.user.service")
enums = importlib.import_module("shared.core.enums")


def _query(**params: str) -> dict:
    return {"query": {key: [value] for key, value in params.items()}}


def _version_payload(version_id: int) -> dict:
    return {
        "id": version_id,
        "grid_id": version_id * 10,
        "version": 1,
        "label": f"Grid {version_id}",
        "status": "published",
        "created_from_version_id": None,
        "published_at": None,
        "tiers": [],
    }


class WorkspaceScopeParsingTests(TestCase):
    def test_all_is_the_explicit_cross_workspace_opt_in(self) -> None:
        self.assertIs(ALL_WORKSPACES, rpc_common.q_workspace_scope(_query(workspace_id="all")))

    def test_integer_is_a_scoped_read(self) -> None:
        self.assertEqual(7, rpc_common.q_workspace_scope(_query(workspace_id="7")))

    def test_missing_scope_is_not_an_opt_in(self) -> None:
        self.assertIsNone(rpc_common.q_workspace_scope({}))

    def test_malformed_scope_is_a_422_not_a_dropped_filter(self) -> None:
        for parse in (rpc_common.q_workspace_scope, rpc_common.q_workspace_id):
            with pytest.raises(BaseAPIException) as excinfo:
                parse(_query(workspace_id="everything"))
            self.assertEqual(422, excinfo.value.status_code)

    def test_global_reads_accept_the_all_sentinel(self) -> None:
        self.assertIsNone(rpc_common.q_workspace_id(_query(workspace_id="all")))
        self.assertEqual(7, rpc_common.q_workspace_id(_query(workspace_id="7")))

    def test_users_read_fails_closed_without_a_scope(self) -> None:
        with pytest.raises(BaseAPIException) as excinfo:
            user_rpc._ws_id({})
        self.assertEqual(400, excinfo.value.status_code)

        with pytest.raises(BaseAPIException):
            user_rpc._ws_id(_query(workspace_id="not-a-workspace"))

    def test_users_read_drops_the_filter_only_for_the_explicit_all(self) -> None:
        self.assertIsNone(user_rpc._ws_id(_query(workspace_id="all")))
        self.assertEqual(7, user_rpc._ws_id(_query(workspace_id="7")))


class OverviewDivisionFilterTests(TestCase):
    """The ``divisions`` chips cannot be translated once for everyone."""

    def test_role_filter_distinguishes_omitted_unassigned_and_named(self) -> None:
        for query_model, params_model in (
            (schemas.UserOverviewQueryParams, schemas.UserOverviewParams),
            (schemas.UserCatalogQueryParams, schemas.UserCatalogParams),
        ):
            self.assertFalse(params_model.from_query_params(build_query_model(query_model, {})).has_role_filter)
            unassigned = params_model.from_query_params(build_query_model(query_model, {"role": ["null"]}))
            self.assertTrue(unassigned.has_role_filter)
            self.assertIsNone(unassigned.role)
            role = RoleRef(dimension="position", role="support")
            selected = params_model.from_query_params(
                build_query_model(query_model, {"role": [role.model_dump_json()]})
            )
            self.assertEqual(role, selected.role)


class OverviewRoleDivisionTests(IsolatedAsyncioTestCase):
    GRID_A = make_grid(101, ((1011, 1, 3000, None), (1012, 2, 2000, 2999), (1013, 3, 0, 1999)))

    async def _resolve(self, raw_roles_map, *, workspace_id, normalizer=None):
        with patch.object(
            user_service,
            "load_division_grid_version_read_payloads",
            AsyncMock(side_effect=lambda _session, ids: {vid: _version_payload(vid) for vid in ids}),
        ):
            return await user_service._overview_role_divisions(
                object(),
                raw_roles_map,
                grid=DEFAULT_GRID,
                normalizer=normalizer,
                workspace_id=workspace_id,
            )

    async def test_all_workspaces_roles_carry_their_canonical_number_and_no_grid(self) -> None:
        # The all-workspaces query hands over each role's canonical ladder number already (None: no ladder).
        roles_by_user, division_grids = await self._resolve(
            {
                1: [(RoleRef(dimension="player_role", role="tank"), 2500, 12)],
                2: [
                    (RoleRef(dimension="player_role", role="tank"), 25, 12),
                    (RoleRef(dimension="player_role", role="support"), 3100, None),
                ],
            },
            workspace_id=None,
        )

        self.assertEqual([(12, None)], [(r.division, r.division_grid_version_id) for r in roles_by_user[1]])
        self.assertEqual(
            [(12, None), (None, None)], [(r.division, r.division_grid_version_id) for r in roles_by_user[2]]
        )
        self.assertEqual([], division_grids)

    async def test_scoped_read_normalizes_every_role_onto_the_workspace_grid(self) -> None:
        # Workspace 7 targets grid 101: a rank played on grid 202 is normalized
        # (here: no mapping, so it falls back), and *every* role reports the one
        # target version — the division numbers are comparable within the page.
        normalizer = DivisionGridNormalizer(
            target_version_id=101,
            target_grid=self.GRID_A,
            source_grids_by_version_id={101: self.GRID_A},
            primary_target_by_source_tier_id={},
        )
        roles_by_user, division_grids = await self._resolve(
            {
                1: [
                    (RoleRef(dimension="player_role", role="tank"), 2500, 101),
                    (RoleRef(dimension="player_role", role="support"), 2500, 202),
                ]
            },
            workspace_id=7,
            normalizer=normalizer,
        )

        self.assertEqual({101}, {role.division_grid_version_id for role in roles_by_user[1]})
        self.assertEqual([101], [grid.id for grid in division_grids])
        self.assertEqual(2, roles_by_user[1][0].division)
