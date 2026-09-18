"""Read-side exposure of the resolved roster shape (D16).

``TournamentRead.roster_shape`` is an **opt-in entity**, not a required field:
``TournamentRead`` is nested in six other schemas (``EncounterRead.tournament``,
``TeamRead.tournament``, ``PlayerRead.tournament``, ``StandingRead.tournament``,
``AchievementRead.tournaments``, ``OwalStandings.days``) that are built from ORM
rows without a session at hand. Making it mandatory would force every one of
them to resolve the fallback chain, so ``to_pydantic`` fills it only when the
caller asks — exactly like ``division_grid_version``.

These stay DB-free: the workspace-level cache-backed getter is patched (or fed a
fake ``session.scalar``), so nothing touches Postgres or Redis. The tournament
level needs neither — it is a column on the row under test.
"""

from __future__ import annotations

import os
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

os.environ["DEBUG"] = "true"

from shared.domain.roster_shape import (  # noqa: E402
    DEFAULT_ROSTER_SHAPE,
    RosterShapeError,
    parse_roster_slots,
)
from src import models, schemas  # noqa: E402
from src.core import enums  # noqa: E402
from src.services.admin import registry  # noqa: E402
from src.services.tournament import flows as tournament_flows  # noqa: E402

_WORKSPACE_ID = 4


def _tournament(
    *,
    tournament_id: int = 1,
    roster_slots_json: dict[str, int] | None = None,
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
        win_points=1.0,
        draw_points=0.5,
        loss_points=0.0,
        team_formation="balancer",
        division_grid_version_id=5,
        roster_slots_json=roster_slots_json,
        # Plain columns the serializer reads: unset on a detached instance means
        # a refresh attempt, not NULL.
        cover_image_url=None,
        logo_url=None,
    )
    # Detached, so `_loaded_relationship` reports unloaded relationships instead
    # of triggering lazy IO against the fake session.
    make_transient_to_detached(tournament)
    return tournament


def _workspace_level(workspace_slots: dict[str, int] | None) -> AsyncMock:
    """Patched stand-in for the ONE cache-backed level getter the read path still uses.

    The tournament override is not fetched: it is a plain column on the row
    `to_pydantic` was already handed (`Tournament.roster_slots_json`, which the
    same response echoes verbatim), so reading it off the instance is both
    cheaper and fresher than a cache round-trip that could disagree with the
    column beside it. Only the workspace default lives on another row, and that
    is what stays cache-backed.
    """
    return AsyncMock(return_value=workspace_slots)


def _patched(get_workspace: AsyncMock) -> Any:
    return patch.object(tournament_flows, "get_workspace_roster_slots", get_workspace)


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
        if "registration_team" in rendered:
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
    workspace_slots: dict[str, int] | None = None,
    session: _LockProbeSession | None = None,
) -> tuple[schemas.TournamentRead, AsyncMock]:
    get_workspace = _workspace_level(workspace_slots)
    with _patched(get_workspace):
        read = await tournament_flows.flows_service.to_pydantic(
            cast(AsyncSession, session if session is not None else _LockProbeSession()),
            tournament,
            entities,
        )
    return read, get_workspace


class RosterShapeResolutionTests(IsolatedAsyncioTestCase):
    async def test_no_override_and_no_workspace_default_yields_builtin_default(self) -> None:
        read, _ = await _read(_tournament(), ["roster_shape"])

        assert read.roster_shape is not None
        self.assertEqual("default", read.roster_shape.source)
        self.assertEqual({"tank": 1, "damage": 2, "support": 2}, read.roster_shape.slots)
        self.assertEqual(5, read.roster_shape.team_size)
        self.assertEqual(4, read.roster_shape.draft_rounds)
        self.assertIs(True, read.roster_shape.has_role_slots)
        self.assertEqual(0, read.roster_shape.flex_slots)

    async def test_workspace_default_only_is_reported_as_workspace(self) -> None:
        read, _ = await _read(
            _tournament(tournament_id=2),
            ["roster_shape"],
            workspace_slots={"tank": 2, "damage": 2, "support": 2},
        )

        assert read.roster_shape is not None
        self.assertEqual("workspace", read.roster_shape.source)
        self.assertEqual({"tank": 2, "damage": 2, "support": 2}, read.roster_shape.slots)
        self.assertEqual(6, read.roster_shape.team_size)

    async def test_tournament_override_wins_over_workspace_default(self) -> None:
        read, _ = await _read(
            _tournament(tournament_id=3, roster_slots_json={"tank": 1, "damage": 1, "support": 1}),
            ["roster_shape"],
            workspace_slots={"tank": 2, "damage": 2, "support": 2},
        )

        assert read.roster_shape is not None
        self.assertEqual("tournament", read.roster_shape.source)
        self.assertEqual({"tank": 1, "damage": 1, "support": 1}, read.roster_shape.slots)
        self.assertEqual(3, read.roster_shape.team_size)

    async def test_override_equal_to_workspace_default_still_reads_as_tournament(self) -> None:
        # `source` says where the value is STORED, not what it resolves to. An
        # admin must see the shape is pinned on the tournament rather than
        # inherited, otherwise editing the workspace default looks like it will
        # move this tournament -- and it will not.
        slots = {"tank": 1, "damage": 2, "support": 2}
        read, _ = await _read(
            _tournament(tournament_id=4, roster_slots_json=dict(slots)),
            ["roster_shape"],
            workspace_slots=dict(slots),
        )

        assert read.roster_shape is not None
        self.assertEqual("tournament", read.roster_shape.source)

    async def test_all_flex_roster_disables_role_slots(self) -> None:
        read, _ = await _read(
            _tournament(tournament_id=5, roster_slots_json={"flex": 6}),
            ["roster_shape"],
        )

        assert read.roster_shape is not None
        self.assertIs(False, read.roster_shape.has_role_slots)
        self.assertEqual(6, read.roster_shape.team_size)
        self.assertEqual(5, read.roster_shape.draft_rounds)
        self.assertEqual(6, read.roster_shape.flex_slots)
        self.assertEqual({"flex": 6}, read.roster_shape.slots)

    async def test_corrupt_stored_slots_raise_instead_of_degrading_to_default(self) -> None:
        # A stored map the parser rejects must surface, not silently become the
        # built-in 5v5: a tournament running the wrong roster size is worse than
        # a loud failure.
        with self.assertRaises(RosterShapeError) as caught:
            await _read(
                _tournament(tournament_id=6, roster_slots_json={"healer": 6}),
                ["roster_shape"],
            )

        self.assertEqual("roster_slots_unknown_code", caught.exception.code)


class RosterShapeOptInTests(IsolatedAsyncioTestCase):
    async def test_resolver_is_never_called_when_entity_not_requested(self) -> None:
        # THE opt-in guarantee. `TournamentRead` is nested in six other schemas
        # built from ORM rows without a session; if this ever becomes an
        # unconditional read, every one of them pays an extra lookup per row.
        read, get_workspace = await _read(
            _tournament(tournament_id=7, roster_slots_json={"flex": 6}),
            ["stages", "division_grid_version"],
        )

        self.assertIsNone(read.roster_shape)
        get_workspace.assert_not_awaited()

    async def test_nested_empty_entities_also_skip_the_resolver(self) -> None:
        # The nested callsites (`to_pydantic(session, team.tournament, [])`)
        # pass an empty list -- the exact path that must stay free of IO.
        read, get_workspace = await _read(
            _tournament(tournament_id=8, roster_slots_json={"flex": 6}),
            [],
        )

        self.assertIsNone(read.roster_shape)
        get_workspace.assert_not_awaited()

    async def test_roster_slots_json_column_is_always_exposed(self) -> None:
        # The raw override column is a plain column, not an entity: the admin
        # form needs to distinguish "no override" from "override equal to the
        # inherited value" without asking for the resolved shape.
        override = {"tank": 2, "damage": 2, "support": 2}
        with_entity, _ = await _read(
            _tournament(tournament_id=9, roster_slots_json=dict(override)),
            ["roster_shape"],
        )
        without_entity, _ = await _read(
            _tournament(tournament_id=10, roster_slots_json=dict(override)),
            [],
        )

        self.assertEqual(override, with_entity.roster_slots_json)
        self.assertEqual(override, without_entity.roster_slots_json)
        self.assertIsNone(without_entity.roster_shape)

    async def test_absent_override_serializes_as_none(self) -> None:
        read, _ = await _read(_tournament(tournament_id=11), [])

        self.assertIsNone(read.roster_slots_json)


class RosterShapeWiringTests(IsolatedAsyncioTestCase):
    async def test_levels_are_read_through_the_real_cache_backed_getters(self) -> None:
        # Drives the REAL `roster_shape_access` getter (unpatched) against a fake
        # session, so a wrong import or argument order in `to_pydantic` cannot hide
        # behind mocks. Exactly three round-trips, in order: the workspace level,
        # then the two shape-lock probes (draft, then teams). The tournament level
        # is NOT among them -- it comes off the already-loaded
        # `Tournament.roster_slots_json` column, so a fourth query here would mean
        # the serializer went back to the database for a value it already held.
        scalars = iter([None, None, None])
        calls: list[object] = []

        class _FakeSession:
            async def scalar(self, statement: object) -> object:
                calls.append(statement)
                return next(scalars)

        read = await tournament_flows.flows_service.to_pydantic(
            cast(AsyncSession, _FakeSession()),
            # Ids unused by any other test, so the session-scoped in-memory
            # cache from conftest cannot serve a stale entry.
            _tournament(tournament_id=90_001, roster_slots_json={"flex": 4}),
            ["roster_shape"],
        )

        assert read.roster_shape is not None
        self.assertEqual("tournament", read.roster_shape.source)
        self.assertEqual({"flex": 4}, read.roster_shape.slots)
        self.assertEqual(3, len(calls))


class RosterShapeReadSchemaTests(IsolatedAsyncioTestCase):
    async def test_from_shape_mirrors_the_domain_shape(self) -> None:
        shape = parse_roster_slots({"tank": 1, "flex": 3})
        read = schemas.RosterShapeRead.from_shape(shape, source="workspace")

        self.assertEqual(shape.slots, read.slots)
        self.assertEqual(shape.team_size, read.team_size)
        self.assertEqual(shape.flex_slots, read.flex_slots)
        self.assertEqual(shape.has_role_slots, read.has_role_slots)
        self.assertEqual(shape.draft_rounds, read.draft_rounds)
        self.assertEqual("workspace", read.source)

    def test_model_dump_json_emits_a_plain_json_object_for_slots(self) -> None:
        # `DEFAULT_ROSTER_SLOTS` is a `MappingProxyType`; a shape that leaked it
        # through serialized fine under type checking and blew up right here.
        read = schemas.RosterShapeRead.from_shape(DEFAULT_ROSTER_SHAPE, source="default")

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
        get_workspace = _workspace_level(None)
        tournament = _tournament(tournament_id=12, roster_slots_json={"tank": 2, "damage": 2, "support": 2})

        with _patched(get_workspace):
            dumped = await registry.registry_service._ser_tournament(
                cast(AsyncSession, _LockProbeSession(draft_status="picking")), tournament
            )

        self.assertIsNotNone(dumped["roster_shape"])
        self.assertEqual("tournament", dumped["roster_shape"]["source"])
        self.assertEqual({"tank": 2, "damage": 2, "support": 2}, dumped["roster_shape"]["slots"])
        self.assertEqual(6, dumped["roster_shape"]["team_size"])
        self.assertEqual({"tank": 2, "damage": 2, "support": 2}, dumped["roster_slots_json"])
        # The Settings tab needs the lock alongside the shape: without it the
        # editor stays enabled and the block only surfaces as a 400 on save.
        self.assertIs(True, dumped["roster_locked_by_draft"])
        # The shape branch really ran: the workspace fallback level is only
        # consulted when the serializer asked for the `roster_shape` entity.
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


class WorkspaceReadTests(IsolatedAsyncioTestCase):
    def test_workspace_read_exposes_its_default_slots(self) -> None:
        workspace = schemas.WorkspaceRead(
            id=_WORKSPACE_ID,
            slug="aq",
            name="AQ",
            description=None,
            icon_url=None,
            is_active=True,
            default_division_grid_version_id=None,
            default_roster_slots_json={"tank": 1, "flex": 4},
        )

        self.assertEqual({"tank": 1, "flex": 4}, workspace.default_roster_slots_json)
        # A workspace has nothing above the built-in default, so it exposes the
        # raw column only -- no resolved shape field.
        self.assertNotIn("roster_shape", schemas.WorkspaceRead.model_fields)

    def test_default_slots_are_optional(self) -> None:
        workspace = schemas.WorkspaceRead(
            id=_WORKSPACE_ID,
            slug="aq",
            name="AQ",
            description=None,
            icon_url=None,
            is_active=True,
            default_division_grid_version_id=None,
        )

        self.assertIsNone(workspace.default_roster_slots_json)
