"""Read-side exposure of the resolved roster shape (D16).

``TournamentRead.roster_shape`` is an **opt-in entity**, not a required field:
``TournamentRead`` is nested in five other schemas (``EncounterRead.tournament``,
``TeamRead.tournament``, ``PlayerRead.tournament``, ``StandingRead.tournament``,
``AchievementRead.tournaments``) that are built from ORM
rows without a session at hand. Making it mandatory would force every one of
them to resolve the fallback chain, so ``to_pydantic`` fills it only when the
caller asks — exactly like ``division_grid_version``.

The bulk team-format projection is patched so these serializer tests remain DB-free.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import make_transient_to_detached

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


from shared import models
from shared.core import enums  # noqa: E402
from shared.domain.roster_shape import RosterShape  # noqa: E402
from src import schemas  # noqa: E402
from src.services.admin import registry  # noqa: E402
from src.services.tournament import flows as tournament_flows  # noqa: E402

_WORKSPACE_ID = 4
DEFAULT_ROSTER_SHAPE = RosterShape(entries=(("tank", 1), ("damage", 2), ("support", 2)))


def _tournament(
    *,
    tournament_id: int = 1,
    draft_format_json: dict | None = None,
) -> models.Tournament:
    tournament = models.Tournament(
        id=tournament_id,
        created_at=datetime.now(UTC),
        updated_at=None,
        workspace_id=_WORKSPACE_ID,
        name=f"Tournament {tournament_id}",
        slug=f"tournament-{tournament_id}",
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
        discord_dms_enabled=True,
        logs_official=False,
        pov_stream_delay_s=0,
        win_points=1.0,
        draw_points=0.5,
        loss_points=0.0,
        team_formation="balancer",
        division_grid_version_id=5,
        discipline="overwatch",
        draft_format_json=draft_format_json,
        # Plain columns the serializer reads: unset on a detached instance means
        # a refresh attempt, not NULL.
        cover_image_url=None,
        rules=None,
        logo_url=None,
    )
    # Detached, so `_loaded_relationship` reports unloaded relationships instead
    # of triggering lazy IO against the fake session.
    make_transient_to_detached(tournament)
    return tournament


def _patched(get_shapes: AsyncMock) -> Any:
    return patch.object(tournament_flows, "tournament_shape_reads", get_shapes)


class _LockProbeSession:
    """Answers the two shape-lock probes independently, and counts them.

    With the workspace level getter patched, the roster-shape branch issues exactly
    two queries: ``has_unfinished_draft_session`` and ``has_registered_teams``.
    Dispatching on the table named in the statement (rather than returning one
    canned value) is what lets each lock be asserted on its own — a fake that
    answered both the same way would pass even if the flags were swapped.
    """

    def __init__(self, *, draft_status: str | None = None, team_status: str | None = None) -> None:
        self.draft_status = draft_status
        self.team_status = team_status
        self.scalar_calls: list[Any] = []
        self.execute_calls: list[Any] = []

    async def scalar(self, statement: Any) -> Any:
        self.scalar_calls.append(statement)
        rendered = str(statement)
        if "registration.team" in rendered:
            return self.team_status
        return self.draft_status

    async def execute(self, statement: Any) -> Any:
        """No ``challonge_source`` rows — this fake covers the roster-shape branch only.

        The admin serializer also derives the Challonge ids/slugs (they come from
        ``challonge_source``, not from a tournament column), so it reaches for
        ``execute``; an unlinked tournament is the case these tests describe.
        """
        self.execute_calls.append(statement)

        class _Empty:
            def all(self) -> list[Any]:
                return []

        return _Empty()


async def _read(
    tournament: models.Tournament,
    entities: list[str],
    *,
    session: _LockProbeSession | None = None,
) -> tuple[schemas.TournamentRead, AsyncMock]:
    get_workspace = AsyncMock(
        return_value={tournament.id: schemas.RosterShapeRead.from_shape(DEFAULT_ROSTER_SHAPE, source="tournament")}
    )
    with _patched(get_workspace):
        read = await tournament_flows.flows_service.to_pydantic(
            cast(AsyncSession, session if session is not None else _LockProbeSession()),
            tournament,
            entities,
        )
    return read, get_workspace


class RosterShapeOptInTests(IsolatedAsyncioTestCase):
    async def test_resolver_is_never_called_when_entity_not_requested(self) -> None:
        # THE opt-in guarantee. `TournamentRead` is nested in six other schemas
        # built from ORM rows without a session; if this ever becomes an
        # unconditional read, every one of them pays an extra lookup per row.
        read, get_workspace = await _read(
            _tournament(tournament_id=7),
            ["stages", "division_grid_version"],
        )

        self.assertIsNone(read.roster_shape)
        get_workspace.assert_not_awaited()

    async def test_nested_empty_entities_also_skip_the_resolver(self) -> None:
        # The nested callsites (`to_pydantic(session, team.tournament, [])`)
        # pass an empty list -- the exact path that must stay free of IO.
        read, get_workspace = await _read(
            _tournament(tournament_id=8),
            [],
        )

        self.assertIsNone(read.roster_shape)
        get_workspace.assert_not_awaited()

    async def test_absent_override_serializes_as_none(self) -> None:
        read, _ = await _read(_tournament(tournament_id=11), [])

        self.assertIsNone(read.roster_shape)


class RosterShapeReadSchemaTests(IsolatedAsyncioTestCase):
    async def test_from_shape_mirrors_the_domain_shape(self) -> None:
        shape = RosterShape(entries=tuple({"tank": 1, "flex": 3}.items()))
        read = schemas.RosterShapeRead.from_shape(shape, source="workspace")

        self.assertEqual(shape.slots, read.slots)
        self.assertEqual(shape.team_size, read.team_size)
        self.assertEqual(shape.flex_slots, read.flex_slots)
        self.assertEqual(shape.has_role_slots, read.has_role_slots)
        self.assertEqual(shape.draft_rounds, read.draft_rounds)
        self.assertEqual("workspace", read.source)

    def test_model_dump_json_emits_a_plain_json_object_for_slots(self) -> None:
        read = schemas.RosterShapeRead.from_shape(DEFAULT_ROSTER_SHAPE, source="preset")

        payload = read.model_dump_json()
        self.assertIn('"slots":{"tank":1,"damage":2,"support":2}', payload.replace(" ", ""))

        dumped = read.model_dump(mode="json")
        self.assertIs(dict, type(dumped["slots"]))
        self.assertEqual({"tank": 1, "damage": 2, "support": 2}, dumped["slots"])

    def test_source_is_constrained_to_the_three_levels(self) -> None:
        with self.assertRaises(ValueError):
            schemas.RosterShapeRead.from_shape(DEFAULT_ROSTER_SHAPE, source="guesswork")


class AdminTournamentSerializerTests(IsolatedAsyncioTestCase):
    async def test_ser_tournament_fills_the_resolved_shape(self) -> None:
        # The admin Settings tab reads the tournament through this serializer.
        # Without the entity it would render an empty roster form and nobody
        # would notice until a human opened the page.
        tournament = _tournament(tournament_id=12)
        get_workspace = AsyncMock(
            return_value={
                tournament.id: schemas.RosterShapeRead.from_shape(
                    RosterShape(entries=(("tank", 2), ("damage", 2), ("support", 2))), source="tournament"
                )
            }
        )

        with _patched(get_workspace):
            dumped = await registry.registry_service._ser_tournament(
                cast(AsyncSession, _LockProbeSession(draft_status="picking")), tournament
            )

        self.assertIsNotNone(dumped["roster_shape"])
        self.assertEqual("tournament", dumped["roster_shape"]["source"])
        self.assertEqual({"tank": 2, "damage": 2, "support": 2}, dumped["roster_shape"]["slots"])
        self.assertEqual(6, dumped["roster_shape"]["team_size"])
        self.assertNotIn("roster_slots_json", dumped)
        # The Settings tab needs the lock alongside the shape: without it the
        # editor stays enabled and the block only surfaces as a 400 on save.
        self.assertIs(True, dumped["roster_locked_by_draft"])
        # The serializer requested the bulk team-format projection.
        get_workspace.assert_awaited_once()


class RosterLockedTests(IsolatedAsyncioTestCase):
    """Both lock flags mirror their write-path guards, opt-in like the shape."""

    async def test_unfinished_session_locks_the_shape(self) -> None:
        session = _LockProbeSession(draft_status="picking")
        read, _ = await _read(_tournament(tournament_id=20), ["roster_shape"], session=session)

        self.assertIs(True, read.roster_locked_by_draft)
        # A draft must not be reported as a team lock.
        self.assertIs(False, read.roster_locked_by_teams)
        self.assertEqual(2, len(session.scalar_calls))

    async def test_a_registered_team_locks_the_shape(self) -> None:
        # The other half: members hold slots assigned from the current shape, so
        # changing it would invalidate their rosters.
        session = _LockProbeSession(team_status="forming")
        read, _ = await _read(_tournament(tournament_id=24), ["roster_shape"], session=session)

        self.assertIs(True, read.roster_locked_by_teams)
        self.assertIs(False, read.roster_locked_by_draft)

    async def test_both_locks_can_be_set_at_once(self) -> None:
        session = _LockProbeSession(draft_status="picking", team_status="complete")
        read, _ = await _read(_tournament(tournament_id=25), ["roster_shape"], session=session)

        self.assertIs(True, read.roster_locked_by_draft)
        self.assertIs(True, read.roster_locked_by_teams)

    async def test_terminal_session_does_not_lock_the_shape(self) -> None:
        # A cancelled/completed session is invisible to the guard's
        # `status NOT IN (...)` filter, so the probe comes back empty -- exactly
        # what Postgres returns for a terminal row.
        for terminal in ("cancelled", "completed"):
            with self.subTest(status=terminal):
                session = _LockProbeSession(draft_status=None)
                read, _ = await _read(_tournament(tournament_id=21), ["roster_shape"], session=session)

                self.assertIs(False, read.roster_locked_by_draft)
                compiled = str(session.scalar_calls[0].compile(compile_kwargs={"literal_binds": True}))
                self.assertIn(terminal, compiled)

    async def test_no_sessions_at_all_does_not_lock_the_shape(self) -> None:
        session = _LockProbeSession(draft_status=None)
        read, _ = await _read(_tournament(tournament_id=22), ["roster_shape"], session=session)

        self.assertIs(False, read.roster_locked_by_draft)

    async def test_probe_is_never_issued_when_the_entity_is_not_requested(self) -> None:
        # Same opt-in reason as `roster_shape`, but this one costs a real query:
        # the six nested `TournamentRead` callsites must not pay for it per row.
        for entities in ([], ["stages", "division_grid_version"]):
            with self.subTest(entities=entities):
                session = _LockProbeSession(draft_status="picking")
                read, _ = await _read(_tournament(tournament_id=23), entities, session=session)

                self.assertIsNone(read.roster_locked_by_draft)
                self.assertEqual([], session.scalar_calls)
