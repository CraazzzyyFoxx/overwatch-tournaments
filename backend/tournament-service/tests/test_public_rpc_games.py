"""The three game-scoped RPC subjects, at the handler boundary.

A claim, a freeplay map choice and an admin correction all target ONE series
position, and each handler owes the service below it something the transport is
the only place to get wrong:

* ``captain_report_game`` must take the side from the CALLER. The body carries
  two scores and no side precisely so one captain can never file the other's
  claim; a handler that read a side out of the payload (or defaulted to "home")
  would let either captain settle a game alone.
* ``captain_select_game_map`` must refuse a game id that belongs to a different
  encounter. The id arrives as a bare path segment, so without that check any
  captain could rename the map of any game in the tournament.
* ``admin_game_result`` must fail the workspace permission BEFORE it corrects
  anything -- this is the one command that overwrites a confirmed result.

The services themselves are covered by ``test_encounter_games.py`` /
``test_game_correction.py``; here they are stubbed so only the wiring is under
test.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"

from tests._rpc_fakes import CapturingBroker, FakeSessionMaker, make_identity  # noqa: E402

public_rpc = importlib.import_module("src.rpc.public_rpc")
pick_ban_admin = importlib.import_module("src.rpc.pick_ban_admin")
helpers = importlib.import_module("src.rpc._helpers")

REPORT = "rpc.tournament.captain_report_game"
SELECT_MAP = "rpc.tournament.captain_select_game_map"
ADMIN_RESULT = "rpc.tournament.admin_game_result"

ENCOUNTER_ID = 31
#: Unequal to ``ENCOUNTER_ID`` and to every score below, so a handler that mixed
#: any two of them up still lands on a distinguishable value.
GAME_ID = 77
OTHER_ENCOUNTER_ID = 32
WORKSPACE_ID = 4
MAP_ID = 12

#: The caller captains AWAY. "home" is the value a handler that guessed instead
#: of resolving would most plausibly produce.
CALLER_SIDE = "away"

GRANTED = make_identity(
    workspaces=[
        {
            "workspace_id": WORKSPACE_ID,
            "rbac_roles": [],
            "rbac_permissions": [{"resource": "match", "action": "update"}],
        }
    ]
)
#: Present, active, and a member of the workspace -- but without `match.update`,
#: so the permission gate is the only thing that can stop it.
UNGRANTED = make_identity(
    workspaces=[
        {
            "workspace_id": WORKSPACE_ID,
            "rbac_roles": [],
            "rbac_permissions": [{"resource": "match", "action": "read"}],
        }
    ]
)


def _encounter(encounter_id: int = ENCOUNTER_ID):
    return SimpleNamespace(id=encounter_id, home_team_id=1, away_team_id=2)


def _handler(module, subject: str):
    broker = CapturingBroker()
    module.register(broker, SimpleNamespace(exception=lambda *a, **k: None))
    assert subject in broker.handlers, f"{subject} is not registered"
    return broker.handlers[subject]


class CaptainReportGameTests(IsolatedAsyncioTestCase):
    async def test_the_side_comes_from_the_caller_and_the_game_id_from_the_path(self) -> None:
        seen: dict = {}

        async def _submit(session, encounter, **kwargs):
            seen["encounter"] = encounter
            seen.update(kwargs)
            return {"disputed": False, "resolved": True, "game": {"id": GAME_ID}}

        async def _side(session, user, encounter):
            return CALLER_SIDE

        self.enterContext(patch.object(helpers.db, "async_session_maker", FakeSessionMaker()))
        self.enterContext(
            patch.object(public_rpc.captain_service, "_load_encounter", lambda s, i: _async(_encounter(i)))
        )
        self.enterContext(patch.object(public_rpc.captain_service, "resolve_captain_side", _side))
        self.enterContext(patch.object(public_rpc.map_report_service, "submit_map_report", _submit))

        envelope = await _handler(public_rpc, REPORT)(
            {
                "identity": GRANTED,
                "id": ENCOUNTER_ID,
                "game_id": str(GAME_ID),
                # A body that TRIES to name a side and a game of its own: neither
                # may reach the service.
                "payload": {"home_score": 2, "away_score": 1, "side": "home", "game_id": 999},
            },
            None,
        )

        self.assertTrue(envelope["ok"], envelope)
        self.assertEqual(CALLER_SIDE, seen["side"])
        self.assertEqual(GAME_ID, seen["game_id"])
        self.assertEqual(2, seen["home_score"])
        self.assertEqual(1, seen["away_score"])
        self.assertEqual(GRANTED["user_id"], seen["reporter_user_id"])
        self.assertEqual(ENCOUNTER_ID, seen["encounter"].id)
        self.assertEqual({"disputed": False, "resolved": True, "game": {"id": GAME_ID}}, envelope["data"])

    async def test_a_negative_score_never_reaches_the_service(self) -> None:
        async def _submit(session, encounter, **kwargs):  # pragma: no cover - must not run
            raise AssertionError("the service was called with an invalid body")

        async def _side(session, user, encounter):
            return CALLER_SIDE

        self.enterContext(patch.object(helpers.db, "async_session_maker", FakeSessionMaker()))
        self.enterContext(
            patch.object(public_rpc.captain_service, "_load_encounter", lambda s, i: _async(_encounter(i)))
        )
        self.enterContext(patch.object(public_rpc.captain_service, "resolve_captain_side", _side))
        self.enterContext(patch.object(public_rpc.map_report_service, "submit_map_report", _submit))

        envelope = await _handler(public_rpc, REPORT)(
            {
                "identity": GRANTED,
                "id": ENCOUNTER_ID,
                "game_id": str(GAME_ID),
                "payload": {"home_score": -1, "away_score": 0},
            },
            None,
        )

        self.assertFalse(envelope["ok"], envelope)
        self.assertEqual("unprocessable", envelope["error"]["code"])


class CaptainSelectGameMapTests(IsolatedAsyncioTestCase):
    def _wire(self, game, *, select=None):
        commits: list[int] = []
        session = SimpleNamespace(add=lambda _row: None, commit=lambda: _async(commits.append(1)))

        async def _get_for_update(_session, game_id):
            self.assertEqual(GAME_ID, game_id)
            return game

        async def _side(_session, _user, _encounter):
            return CALLER_SIDE

        self.enterContext(patch.object(helpers.db, "async_session_maker", FakeSessionMaker(session)))
        self.enterContext(
            patch.object(public_rpc.captain_service, "_load_encounter", lambda s, i: _async(_encounter(i)))
        )
        self.enterContext(patch.object(public_rpc.captain_service, "resolve_captain_side", _side))
        self.enterContext(
            patch.object(public_rpc.encounter_game_service.game_repo, "get_for_update", _get_for_update)
        )
        self.enterContext(patch.object(public_rpc.encounter_game_service, "select_map", select or _unused))
        self.enterContext(
            patch.object(public_rpc.encounter_game_service, "reports_by_game", lambda _s, games: _async({}))
        )
        return commits

    async def test_a_game_of_another_encounter_is_not_found_and_nothing_is_written(self) -> None:
        commits = self._wire(SimpleNamespace(id=GAME_ID, encounter_id=OTHER_ENCOUNTER_ID))

        envelope = await _handler(public_rpc, SELECT_MAP)(
            {
                "identity": GRANTED,
                "id": ENCOUNTER_ID,
                "game_id": str(GAME_ID),
                "payload": {"map_id": MAP_ID},
            },
            None,
        )

        self.assertFalse(envelope["ok"], envelope)
        self.assertEqual("not_found", envelope["error"]["code"])
        self.assertEqual([], commits)

    async def test_the_chosen_map_is_committed_and_the_game_comes_back(self) -> None:
        chosen: dict = {}

        async def _select(_session, encounter, game, *, map_id):
            chosen["encounter_id"] = encounter.id
            chosen["map_id"] = map_id
            game.map_id = map_id
            return game

        game = _game_row()
        commits = self._wire(game, select=_select)

        envelope = await _handler(public_rpc, SELECT_MAP)(
            {
                "identity": GRANTED,
                "id": ENCOUNTER_ID,
                "game_id": str(GAME_ID),
                "payload": {"map_id": MAP_ID},
            },
            None,
        )

        self.assertTrue(envelope["ok"], envelope)
        self.assertEqual({"encounter_id": ENCOUNTER_ID, "map_id": MAP_ID}, chosen)
        self.assertEqual(1, len(commits), "the map choice was never committed")
        self.assertEqual(MAP_ID, envelope["data"]["game"]["map_id"])
        self.assertEqual(GAME_ID, envelope["data"]["game"]["id"])


class AdminGameResultTests(IsolatedAsyncioTestCase):
    def _wire(self):
        calls: dict = {}

        async def _workspace_id(_session, encounter_id):
            self.assertEqual(ENCOUNTER_ID, encounter_id)
            return WORKSPACE_ID

        async def _correct(_session, encounter, **kwargs):
            calls["encounter_id"] = encounter.id
            calls.update(kwargs)
            return {"game": {"id": GAME_ID}, "rebuilt_rounds": [2]}

        async def _audit(_session, **kwargs):
            calls.setdefault("audits", []).append(kwargs)

        self.enterContext(patch.object(helpers.db, "async_session_maker", FakeSessionMaker()))
        self.enterContext(patch.object(pick_ban_admin.auth, "get_encounter_workspace_id", _workspace_id))
        self.enterContext(patch.object(pick_ban_admin, "_load_encounter", lambda s, i: _async(_encounter(i))))
        self.enterContext(patch.object(pick_ban_admin, "record_admin_audit", _audit))
        self.enterContext(patch.object(pick_ban_admin.game_correction_service, "correct", _correct))
        return calls

    async def test_without_match_update_nothing_is_corrected(self) -> None:
        calls = self._wire()

        envelope = await _handler(pick_ban_admin, ADMIN_RESULT)(
            {
                "identity": UNGRANTED,
                "id": ENCOUNTER_ID,
                "game_id": str(GAME_ID),
                "payload": {"home_score": 2, "away_score": 1, "reason": "replay review"},
            },
            None,
        )

        self.assertFalse(envelope["ok"], envelope)
        self.assertEqual("forbidden", envelope["error"]["code"])
        self.assertEqual({}, calls, "a refused caller still reached the correction or the journal")

    async def test_a_granted_caller_corrects_the_game_and_the_reason_is_journalled(self) -> None:
        calls = self._wire()

        envelope = await _handler(pick_ban_admin, ADMIN_RESULT)(
            {
                "identity": GRANTED,
                "id": ENCOUNTER_ID,
                "game_id": str(GAME_ID),
                "payload": {"home_score": 2, "away_score": 1, "reason": "replay review"},
            },
            None,
        )

        self.assertTrue(envelope["ok"], envelope)
        self.assertEqual(GAME_ID, calls["game_id"])
        self.assertEqual(ENCOUNTER_ID, calls["encounter_id"])
        self.assertEqual((2, 1), (calls["home_score"], calls["away_score"]))
        self.assertEqual("replay review", calls["reason"])
        self.assertEqual(GRANTED["user_id"], calls["actor_user_id"])
        self.assertEqual({"game": {"id": GAME_ID}, "rebuilt_rounds": [2]}, envelope["data"])

        audit = calls["audits"][0]
        self.assertEqual("encounter.game_result", audit["action"])
        self.assertEqual(WORKSPACE_ID, audit["workspace_id"])
        self.assertEqual(ENCOUNTER_ID, audit["entity_id"])
        self.assertEqual("replay review", audit["after"]["reason"])
        self.assertEqual(GAME_ID, audit["after"]["game_id"])

    async def test_a_correction_without_a_reason_is_refused(self) -> None:
        """The reason is what the audit journal exists for: an empty one is not a
        correction, it is an unexplained overwrite."""
        calls = self._wire()

        envelope = await _handler(pick_ban_admin, ADMIN_RESULT)(
            {
                "identity": GRANTED,
                "id": ENCOUNTER_ID,
                "game_id": str(GAME_ID),
                "payload": {"home_score": 2, "away_score": 1, "reason": ""},
            },
            None,
        )

        self.assertFalse(envelope["ok"], envelope)
        self.assertEqual("unprocessable", envelope["error"]["code"])
        self.assertNotIn("game_id", calls)


class AdminEncounterLoadTakesTheRowLock(IsolatedAsyncioTestCase):
    """Every admin handler in ``pick_ban_admin`` moves the live session or a game
    result, and the correction path re-derives the encounter score from its games.
    Reading the encounter unlocked lets a concurrent captain claim and an admin
    correction each materialise a score from a stale row, so the loader takes the
    same Encounter -> Game lock order the captain path uses (spec §7)."""

    async def test_the_admin_loader_selects_the_encounter_for_update(self) -> None:
        captured: list = []

        class _LockSession:
            async def scalar(self, statement):
                captured.append(statement)
                return _encounter()

        encounter = await pick_ban_admin._load_encounter(_LockSession(), ENCOUNTER_ID)

        self.assertEqual(ENCOUNTER_ID, encounter.id)
        self.assertIn("FOR UPDATE", str(captured[0]))
        # Without it the locked row is served from the identity map at whatever
        # version this session first saw, which defeats the lock.
        self.assertTrue(captured[0].get_execution_options().get("populate_existing"))


async def _unused(*args, **kwargs):  # pragma: no cover - replaced per test
    raise AssertionError("select_map was called unexpectedly")


def _game_row():
    """A game shaped the way ``EncounterGameService.serialize`` reads it."""
    return SimpleNamespace(
        id=GAME_ID,
        encounter_id=ENCOUNTER_ID,
        position=1,
        map_id=None,
        state=None,
        accepted_home_score=None,
        accepted_away_score=None,
        result_source=None,
        result_version=0,
        confirmed_at=None,
    )


class _Awaited:
    """``await``-able wrapper so a patched coroutine can be a plain lambda."""

    def __init__(self, value):
        self._value = value

    def __await__(self):
        async def _inner():
            return self._value

        return _inner().__await__()


def _async(value):
    return _Awaited(value)
