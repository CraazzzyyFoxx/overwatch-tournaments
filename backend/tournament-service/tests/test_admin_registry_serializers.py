"""Regressions in the admin-CRUD serializers (``rpc.tournament.admin.*``).

``_ser_player``: a required keyword-only ``grid`` argument was added to
``team_flows.flows_service.to_pydantic_player`` (it resolves
``PlayerRead.division`` against the tournament's effective division grid), but
``_ser_player`` was left calling it positionally, so every admin player write
crashed at serialization with::

    TypeError: to_pydantic_player() missing 1 required keyword-only argument: 'grid'

That test drives the REAL ``to_pydantic_player`` (so its signature is enforced)
and asserts ``_ser_player`` resolves the effective grid from the player's
tournament and threads it through.

``_ser_tournament``: the ``challonge_id``/``challonge_slug`` response fields are
DERIVED from ``challonge_source`` (the columns that used to back them are gone),
and ``to_pydantic`` serializes them as ``None`` unless the caller passes the
resolved refs. ``_ser_tournament`` did not, so the admin Settings tab read back
``challonge_slug: null`` immediately after linking a bracket -- the field looked
blank, the badge read "Not linked" and every sync control stayed disabled even
though the link was persisted.
"""

from __future__ import annotations

import importlib
import os
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DEBUG", "true")

registry = importlib.import_module("src.services.admin.registry")
team_flows = importlib.import_module("src.services.team.flows")
tournament_flows = importlib.import_module("src.services.tournament.flows")

from sqlalchemy.orm import make_transient_to_detached  # noqa: E402

from shared.division_grid import DEFAULT_GRID  # noqa: E402
from src import models  # noqa: E402
from src.core import enums  # noqa: E402


def _player() -> SimpleNamespace:
    return SimpleNamespace(
        to_dict=lambda: {
            "id": 1,
            "created_at": None,
            "updated_at": None,
            "name": "Roster Player",
            "sub_role": None,
            "rank": 1500,
            "role": "damage",
            "tournament_id": 78,
            "team_id": 9,
            "is_newcomer": False,
            "is_newcomer_role": False,
            "is_substitution": False,
            "related_player_id": None,
            "workspace_member_id": 555,
        },
        rank=1500,
        tournament_id=78,
        # The nested `.player` is the real `User` row `player_to_read` serializes
        # through `user_to_read`, so it needs every column `UserRead` requires --
        # `id` alone stopped being enough once that serializer became a plain
        # sync call this test can no longer intercept.
        workspace_member=SimpleNamespace(player_id=42, player=SimpleNamespace(id=42, name="Roster Player")),
        tournament=SimpleNamespace(id=78),
        team=None,
    )


class SerPlayerGridTests(IsolatedAsyncioTestCase):
    async def test_ser_player_resolves_and_passes_effective_grid(self) -> None:
        session = object()
        player = _player()

        get_grid = AsyncMock(return_value=DEFAULT_GRID)

        with (
            patch.object(registry, "get_division_grid", get_grid),
            patch.object(team_flows.tournament_flows_service, "to_pydantic", AsyncMock(return_value=None)),
        ):
            result = await registry.registry_service._ser_player(session, player)

        # Grid resolved from the player's own tournament (not global / DEFAULT-by-omission).
        get_grid.assert_awaited_once_with(session, None, tournament_id=78)
        self.assertEqual(42, result["user_id"])
        self.assertEqual("Roster Player", result["user"]["name"])
        # division resolved against the effective grid rather than crashing.
        self.assertEqual(DEFAULT_GRID.resolve_division_number(1500), result["division"])


# Ids unused by any other test: the roster-slot getters this serializer drives are
# cache-backed and the cache outlives a module, so a shared workspace/tournament id
# would let this file warm an entry another file counts queries against.
def _tournament(tournament_id: int = 91_001) -> models.Tournament:
    tournament = models.Tournament(
        id=tournament_id,
        created_at=datetime.now(UTC),
        updated_at=None,
        workspace_id=91_004,
        name="Linked Tournament",
        slug="linked-tournament",
        description=None,
        is_league=False,
        is_finished=False,
        is_hidden=False,
        status=enums.TournamentStatus.LIVE,
        start_date=datetime.now(UTC),
        end_date=datetime.now(UTC),
        auto_transitions_enabled=True,
        allow_late_registration=False,
        discord_broadcasts_enabled=True,
        win_points=1.0,
        draw_points=0.5,
        loss_points=0.0,
        team_formation="balancer",
        division_grid_version_id=5,
        # Plain columns the serializer reads: unset on a detached instance means
        # a refresh attempt, not NULL.
        roster_slots_json=None,
        rules=None,
        cover_image_url=None,
        logo_url=None,
    )
    # Detached, so unloaded relationships report as unloaded instead of
    # triggering lazy IO against the fake session.
    make_transient_to_detached(tournament)
    return tournament


class _NullSession:
    """Answers the roster-shape/lock probes with "nothing found"."""

    async def scalar(self, statement: object) -> object:
        return None


class SerTournamentChallongeTests(IsolatedAsyncioTestCase):
    async def test_ser_tournament_emits_the_derived_challonge_link(self) -> None:
        tournament = _tournament()
        resolve = AsyncMock(return_value={tournament.id: (12345, "owt-64")})

        # Patched on `tournament.flows`: that module owns the resolution the admin
        # serializer must route through (`flows_service.tournament_read`).
        with patch.object(tournament_flows, "resolve_tournament_challonge", resolve):
            dumped = await registry.registry_service._ser_tournament(_NullSession(), tournament)

        # Resolved for THIS tournament, and threaded into the response the admin
        # Settings tab renders the Challonge field and badge from.
        resolve.assert_awaited_once()
        self.assertEqual([tournament.id], list(resolve.await_args.args[1]))
        self.assertEqual(12345, dumped["challonge_id"])
        self.assertEqual("owt-64", dumped["challonge_slug"])

    async def test_an_unlinked_tournament_stays_null(self) -> None:
        tournament = _tournament(tournament_id=91_002)

        with patch.object(tournament_flows, "resolve_tournament_challonge", AsyncMock(return_value={})):
            dumped = await registry.registry_service._ser_tournament(_NullSession(), tournament)

        self.assertIsNone(dumped["challonge_id"])
        self.assertIsNone(dumped["challonge_slug"])
