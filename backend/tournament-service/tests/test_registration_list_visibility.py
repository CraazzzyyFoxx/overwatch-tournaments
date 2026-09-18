"""The participants list an organizer chose not to publish.

``hide_registrations`` is an ACCESS decision, not a CSS one: the list endpoint is
cached per tournament with no viewer in the key, so whatever it returns is what
every reader gets. Two things are pinned here:

1. the hidden payload carries no registrations AND never runs the identity /
   team / history / admission read -- a version that built the full read model
   and emptied the list afterwards would pass a "no rows" assertion while still
   shipping every battletag to the cache on the way;
2. the aggregate beside it counts the same rows the visible list would have
   shown, one bucket per registration, so flipping the toggle never changes the
   number a reader sees.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"

service = importlib.import_module("src.services.registration.service")


def _role(role: str, *, is_primary: bool = True, priority: int = 0) -> SimpleNamespace:
    return SimpleNamespace(role=role, is_primary=is_primary, priority=priority)


def _registration(reg_id: int, *roles: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(id=reg_id, roles=list(roles))


def _form(**overrides) -> SimpleNamespace:
    return SimpleNamespace(**{"hide_registrations": False, "max_participants": None, "show_ranks": False, **overrides})


class RoleCountTests(IsolatedAsyncioTestCase):
    def test_counts_the_primary_role_once_per_registration(self):
        """A flex player declaring three roles is one tank, not one of each."""
        counts = service._role_counts(
            [
                _registration(1, _role("tank"), _role("damage", is_primary=False, priority=1)),
                _registration(2, _role("damage")),
                _registration(3, _role("damage")),
            ]
        )

        self.assertEqual(counts, {"tank": 1, "damage": 2})

    def test_falls_back_to_the_highest_priority_role_when_none_is_primary(self):
        """Legacy rows carry no primary flag; dropping them would under-count the field."""
        counts = service._role_counts(
            [
                _registration(
                    1,
                    _role("support", is_primary=False, priority=1),
                    _role("tank", is_primary=False, priority=0),
                )
            ]
        )

        self.assertEqual(counts, {"tank": 1})

    def test_a_registration_with_no_roles_lands_in_no_bucket(self):
        self.assertEqual(service._role_counts([_registration(1)]), {})


class HiddenListTests(IsolatedAsyncioTestCase):
    async def _build(self, form: SimpleNamespace, rows: list[SimpleNamespace]):
        session = SimpleNamespace(
            scalars=AsyncMock(return_value=rows),
            # Left as an AsyncMock so the test can assert it stayed unused: this
            # is the call that loads battletags, teams and tournament history.
            execute=AsyncMock(),
        )
        with (
            patch.object(service, "_resolve_tournament_workspace", AsyncMock(return_value=7)),
            patch.object(service._common_service, "get_registration_form", AsyncMock(return_value=form)),
        ):
            return session, await service.registration_service.build_public_registration_list(session, tournament_id=42)

    async def test_a_hidden_list_answers_with_the_aggregate_and_no_rows(self):
        session, response = await self._build(
            _form(hide_registrations=True, max_participants=60),
            [
                _registration(1, _role("tank")),
                _registration(2, _role("damage")),
                _registration(3, _role("damage")),
            ],
        )

        self.assertTrue(response.hidden)
        self.assertEqual(response.registrations, [])
        self.assertEqual(response.total, 3)
        self.assertEqual(response.role_counts, {"tank": 1, "damage": 2})
        self.assertEqual(response.max_participants, 60)

    async def test_a_hidden_list_never_reads_the_identities_it_is_hiding(self):
        session, _ = await self._build(_form(hide_registrations=True), [_registration(1, _role("tank"))])

        session.execute.assert_not_awaited()
