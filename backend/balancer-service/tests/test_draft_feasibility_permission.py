"""``rpc.balancer.draft.feasibility`` and ``rpc.balancer.draft.suggestions``
are two read-only analyses of the same draft session, yet ``feasibility``
demanded workspace ``team.create`` while ``suggestions`` only needed
``team.read`` -- no comment explained the split, and neither handler writes
anything. Pinned to ``team.read``, matching its sibling.
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

from src.rpc import draft  # noqa: E402


def _handler_source(name: str) -> str:
    source = inspect.getsource(draft)
    start = source.index(f'@broker.subscriber("rpc.balancer.draft.{name}")')
    end = source.index("return await c.envelope(", start)
    return source[start:end]


class FeasibilityPermissionTests(TestCase):
    def test_feasibility_and_suggestions_require_the_same_read_grant(self) -> None:
        feasibility = _handler_source("feasibility")
        suggestions = _handler_source("suggestions")

        self.assertIn('c.require_workspace_permission(data, user, ws_id, "team", "read")', feasibility)
        self.assertIn('c.require_workspace_permission(data, user, ws_id, "team", "read")', suggestions)

    def test_the_genuine_mutation_next_to_it_keeps_the_stricter_grant(self) -> None:
        """``player_role_edit`` actually writes a player's role/rank -- it must
        stay on ``team.create``, unlike the two read-only analyses above it."""
        player_role_edit = _handler_source("player_role_edit")

        self.assertIn('c.require_workspace_permission(data, user, ws_id, "team", "create")', player_role_edit)
