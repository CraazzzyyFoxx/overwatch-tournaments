"""``rpc.tournament.regteam_free_agents`` returned every unteamed registrant's
BattleTag for ANY tournament id an authenticated caller supplied, with no
``assert_tournament_viewable`` call -- unlike every sibling public read in
``public_rpc.py``. A hidden/preview-only tournament's registrant list is
otherwise 404'd for an outsider; this endpoint served it anyway.
"""

from __future__ import annotations

import inspect
from unittest import TestCase

from src.rpc import public_rpc


class FreeAgentsVisibilityGateTests(TestCase):
    def _handler_source(self) -> str:
        source = inspect.getsource(public_rpc)
        start = source.index('@broker.subscriber("rpc.tournament.regteam_free_agents")')
        end = source.index("return await _run(logger, op)", start)
        return source[start:end]

    def test_it_checks_tournament_visibility(self) -> None:
        """Same gate every sibling public read in this file uses, called with
        the caller's real identity (this endpoint requires an account; only
        the visibility dimension was missing, not the authentication one)."""
        source = self._handler_source()

        self.assertIn("assert_tournament_viewable(session, user, tournament_id)", source)
        self.assertIn("user = _identity(data)", source)
