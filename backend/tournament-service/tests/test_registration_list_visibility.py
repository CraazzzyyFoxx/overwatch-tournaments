"""The participants list an organizer chose not to publish.

``hide_registrations`` is an ACCESS decision, not a CSS one: the list endpoint is
cached per tournament with no viewer in the key, so whatever it returns is what
every reader gets. Two things are pinned here:

1. the hidden payload carries no registrations AND never runs the identity /
   team / history / admission read -- a version that built the full read model
   and emptied the list afterwards would pass a "no rows" assertion while still
   shipping every battletag to the cache on the way;
2. the aggregate beside it counts the same rows the visible list would have
   shown, minus withdrawn ones, one bucket per registration, so flipping the
   toggle never changes the number a reader sees -- while the visible list still
   ships the withdrawn rows its Withdrawn filter needs.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from shared import models

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


service = importlib.import_module("src.services.registration.service")


def _role(role: str, *, is_primary: bool = True, priority: int = 0) -> SimpleNamespace:
    return SimpleNamespace(role=role, is_primary=is_primary, priority=priority)


def _registration(reg_id: int, *roles: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(id=reg_id, roles=list(roles))


def _entry(reg_id: int, *roles: SimpleNamespace, status: str = "approved") -> SimpleNamespace:
    """The registration's entry in the listed node: the list is made of entries."""
    return SimpleNamespace(id=reg_id, registration_id=reg_id, status=status, registration=_registration(reg_id, *roles))


def _form(**overrides) -> SimpleNamespace:
    return SimpleNamespace(**{"hide_registrations": False, "show_ranks": False, **overrides})


def _node(max_participants: int | None) -> models.FlowNode:
    """The listed registration node: its config sets the capacity the list reports."""
    return models.FlowNode(
        id=3,
        tournament_id=42,
        kind="registration",
        name="Registration",
        status="open",
        config={"max_participants": max_participants},
    )


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
    async def _build(self, form: SimpleNamespace, rows: list[SimpleNamespace], *, max_participants: int | None = None):
        session = SimpleNamespace(
            scalars=AsyncMock(return_value=rows),
            # Left as an AsyncMock so the test can assert it stayed unused: this
            # is the call that loads battletags, teams and tournament history.
            execute=AsyncMock(),
        )
        with (
            patch.object(
                service.registration_service.tournament_repo,
                "get",
                AsyncMock(return_value=SimpleNamespace(workspace_id=7, status=None, phase_schedule=[])),
            ),
            patch.object(service._common_service, "get_registration_form", AsyncMock(return_value=form)),
            patch.object(
                service._common_service, "ensure_registration_node", AsyncMock(return_value=_node(max_participants))
            ),
            patch.object(service.windows_service, "load_schedule", AsyncMock(return_value=[])),
        ):
            return session, await service.registration_service.build_public_registration_list(
                session, tournament_id=42, registration_node_id=3
            )

    async def test_a_hidden_list_answers_with_the_aggregate_and_no_rows(self):
        session, response = await self._build(
            _form(hide_registrations=True),
            [
                _entry(1, _role("tank")),
                _entry(2, _role("damage")),
                _entry(3, _role("damage")),
            ],
            max_participants=60,
        )

        self.assertTrue(response.hidden)
        self.assertEqual(response.registrations, [])
        self.assertEqual(response.total, 3)
        self.assertEqual(response.role_counts, {"tank": 1, "damage": 2})
        self.assertEqual(response.max_participants, 60)

    async def test_a_hidden_list_never_reads_the_identities_it_is_hiding(self):
        session, _ = await self._build(_form(hide_registrations=True), [_entry(1, _role("tank"))])

        session.execute.assert_not_awaited()

    async def test_a_withdrawn_registration_is_not_counted(self):
        _, response = await self._build(
            _form(hide_registrations=True),
            [_entry(1, _role("tank")), _entry(2, _role("damage"), status="withdrawn")],
        )

        self.assertEqual(response.total, 1)
        self.assertEqual(response.role_counts, {"tank": 1})


class VisibleListTests(IsolatedAsyncioTestCase):
    async def test_a_withdrawn_row_is_listed_but_not_counted(self):
        """The Withdrawn filter needs the row; "Registered N" must not count it."""
        rows = [
            _entry(1, _role("tank")),
            _entry(2, _role("damage"), status="withdrawn"),
            _entry(3, _role("damage")),
        ]
        result = MagicMock()
        result.scalars.return_value.all.return_value = rows
        session = SimpleNamespace(execute=AsyncMock(return_value=result))
        construct = service.RegistrationListRead.model_construct
        # Everything past the row read is the per-row serializer, stubbed: this pins
        # which rows ship and what the aggregate counts, nothing else.
        with (
            patch.object(
                service.registration_service.tournament_repo,
                "get",
                AsyncMock(return_value=SimpleNamespace(workspace_id=7, discipline="overwatch")),
            ),
            patch.object(
                service._common_service, "get_registration_form", AsyncMock(return_value=_form(current_version_id=None))
            ),
            patch.object(service._common_service, "ensure_registration_node", AsyncMock(return_value=_node(None))),
            patch.object(service.windows_service, "load_schedule", AsyncMock(return_value=[])),
            patch.object(service.registration_service, "resolve_admission_list", AsyncMock(return_value={})),
            patch.multiple(
                service,
                get_status_metas_map=AsyncMock(return_value={}),
                _public_rosters=AsyncMock(return_value={}),
                _build_tournament_history=AsyncMock(return_value=({}, {}, {})),
                registration_public_keys=MagicMock(return_value=lambda _: frozenset()),
                discipline_identity_provider=MagicMock(return_value="battlenet"),
                submitted_late=MagicMock(return_value=False),
                _reg_to_read=lambda r, e, **_: {"id": r.id, "status": e.status},
                RegistrationListRead=construct,
            ),
        ):
            response = await service.registration_service.build_public_registration_list(
                session, tournament_id=42, registration_node_id=3
            )

        self.assertFalse(response.hidden)
        self.assertEqual([read.id for read in response.registrations], [1, 2, 3])
        self.assertEqual(response.total, 2)
        self.assertEqual(response.role_counts, {"tank": 1, "damage": 1})
