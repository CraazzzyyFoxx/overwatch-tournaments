"""``rpc.balancer.players.upsert`` and the ``workspace`` (canon) scope of
``set_ranks`` used to be gated by workspace membership alone: any plain member
could create roster rows or rewrite the shared rank canon every author and
mix inherits, with no ``resource.action`` grant at all -- unlike every sibling
roster-shaping write in this service (``admin.py``, ``binary.py``), which all
require ``team.create``/``team.update``.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from unittest import TestCase

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"
for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from src.rpc import players  # noqa: E402


def _handler_source(name: str) -> str:
    source = inspect.getsource(players)
    start = source.index(f'@broker.subscriber("rpc.balancer.players.{name}")')
    end = source.index("return await c.envelope(", start)
    return source[start:end]


class UpsertPermissionGateTests(TestCase):
    def test_creating_a_roster_member_requires_team_create(self) -> None:
        source = _handler_source("upsert")

        self.assertIn("c.require_member(user, workspace_id)", source)
        self.assertIn('ensure_workspace_permission(user, workspace_id, "team", "create")', source)


class SetRanksPermissionGateTests(TestCase):
    def test_writing_the_shared_canon_requires_team_update(self) -> None:
        """The ``workspace`` (canon) layer is everyone's shared book -- writing
        it now needs the same ``team.update`` grant the sibling roster-shaping
        writes require, gated only when the scope is NOT ``author``."""
        source = _handler_source("set_ranks")

        self.assertIn('is_author_scope = _scope(data) == "author"', source)
        self.assertIn("if not is_author_scope:", source)
        self.assertIn('ensure_workspace_permission(user, workspace_id, "team", "update")', source)

    def test_writing_ones_own_book_stays_self_service(self) -> None:
        """The ``author`` layer is always the caller's own -- membership alone
        must remain sufficient, with no additional grant required."""
        source = _handler_source("set_ranks")
        gate_index = source.index("ensure_workspace_permission")
        guard_index = source.index("if not is_author_scope:")

        self.assertLess(guard_index, gate_index, "the grant check must be conditional on scope != author")
