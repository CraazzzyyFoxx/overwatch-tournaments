"""Pre-game chat membership: who the resolver says you are in an encounter room.

Only the resolver. Everything the shared service decides on top of a membership
-- spectator visibility, mutes, the throttle, sanitizing -- is covered once in
``backend/tests/test_chat_service.py`` and is not re-asserted here.

Fake-session style, like ``test_pick_ban_session.py``: the resolver's IO is the
encounter load, the visibility gate, the captain probe and the workspace lookup,
all of which are patched, so a hand-rolled session says more than a database.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


from shared.core.enums import EncounterFormat  # noqa: E402
from shared.core.errors import BaseAPIException as HTTPException  # noqa: E402
from shared.services.chat import SPECTATOR_ROLE, ChatRoom  # noqa: E402
from src.services.encounter import chat_access  # noqa: E402

ENCOUNTER_ID = 500
TOURNAMENT_ID = 42
WORKSPACE_ID = 9
ROOM = ChatRoom.encounter(ENCOUNTER_ID)


class _FakeSession:
    """The resolver never touches the session itself -- every read is patched."""


def _auth_user(
    *,
    organizer_of: tuple[int, ...] = (),
    roster_of: tuple[int, ...] = (),
    superuser: bool = False,
) -> SimpleNamespace:
    """``organizer_of`` is staff authority (a non-read grant in that
    workspace); ``roster_of`` is mere membership, which every tournament
    registrant has and which must buy nothing here."""
    return SimpleNamespace(
        id=7,
        username="fox",
        is_superuser=superuser,
        has_admin_panel_access=lambda ws: superuser or ws in organizer_of,
        is_workspace_member=lambda ws: superuser or ws in roster_of or ws in organizer_of,
    )


class _Ctx:
    """Patch set shared by every case: encounter load, tournament visibility,
    captain side, workspace and the in-tournament name lookup."""

    def __init__(self, *, captain_side: str | None, viewable: bool = True) -> None:
        side_mock = (
            AsyncMock(side_effect=HTTPException(status_code=403, detail="nope"))
            if captain_side is None
            else AsyncMock(return_value=captain_side)
        )
        viewable_mock = (
            AsyncMock(return_value=None)
            if viewable
            else AsyncMock(side_effect=HTTPException(status_code=403, detail="hidden"))
        )
        self._patches = [
            patch.object(
                chat_access.captain_service,
                "load_encounter_any_format",
                # A duel: the format decides which captaincy question is asked,
                # and a row in the database always carries one.
                AsyncMock(return_value=SimpleNamespace(id=ENCOUNTER_ID, format=EncounterFormat.DUEL)),
            ),
            patch.object(
                chat_access.visibility_resolvers.visibility_resolvers_service,
                "tournament_id_for_encounter",
                AsyncMock(return_value=TOURNAMENT_ID),
            ),
            patch.object(chat_access, "assert_tournament_viewable", viewable_mock),
            patch.object(chat_access.captain_service, "resolve_captain_side", side_mock),
            patch.object(chat_access.auth, "get_encounter_workspace_id", AsyncMock(return_value=WORKSPACE_ID)),
            patch.object(
                chat_access,
                "tournament_display_name",
                # Keyed on the encounter's tournament: a tag from another
                # tournament's registration must not name you here.
                AsyncMock(
                    side_effect=lambda _s, *, auth_user, tournament_id: "Fox#2112"
                    if tournament_id == TOURNAMENT_ID
                    else auth_user.username
                ),
            ),
        ]

    def __enter__(self) -> None:
        for p in self._patches:
            p.start()

    def __exit__(self, *exc: Any) -> None:
        for p in self._patches:
            p.stop()


async def _resolve(user: Any) -> Any:
    return await chat_access.encounter_chat_service.access.resolve(_FakeSession(), user, ROOM)


class EncounterChatAccessTest(IsolatedAsyncioTestCase):
    async def test_captain_of_home_writes_but_does_not_moderate(self) -> None:
        with _Ctx(captain_side="home"):
            membership = await _resolve(_auth_user())
        self.assertEqual(membership.role, "home")
        self.assertEqual(membership.display_name, "Fox#2112")
        self.assertTrue(membership.can_write)
        self.assertFalse(membership.can_moderate)

    async def test_workspace_organizer_is_staff_and_moderates(self) -> None:
        with _Ctx(captain_side=None):
            membership = await _resolve(_auth_user(organizer_of=(WORKSPACE_ID,)))
        self.assertEqual(membership.role, "staff")
        self.assertTrue(membership.can_write)
        self.assertTrue(membership.can_moderate)

    async def test_plain_workspace_member_is_only_a_spectator(self) -> None:
        # Signing up for a tournament creates the workspace_member row (and the
        # baseline ``member`` role) this used to read as staff, handing every
        # registrant the lobby code and the mute button.
        with _Ctx(captain_side=None):
            membership = await _resolve(_auth_user(roster_of=(WORKSPACE_ID,)))
        self.assertEqual(membership.role, SPECTATOR_ROLE)
        self.assertFalse(membership.can_write)
        self.assertFalse(membership.can_moderate)

    async def test_logged_in_stranger_is_a_read_only_spectator(self) -> None:
        # Not a captain, not in the owning workspace: allowed to SEE the room,
        # never to write in it. Whether seeing includes reading is the room's
        # setting, which ChatService -- not this resolver -- applies.
        with _Ctx(captain_side=None):
            membership = await _resolve(_auth_user())
        self.assertEqual(membership.role, SPECTATOR_ROLE)
        self.assertFalse(membership.can_write)
        self.assertFalse(membership.can_moderate)

    async def test_anonymous_caller_is_a_spectator(self) -> None:
        with _Ctx(captain_side=None):
            membership = await _resolve(None)
        self.assertEqual(membership.role, SPECTATOR_ROLE)
        self.assertFalse(membership.can_write)

    async def test_hidden_tournament_is_forbidden_before_any_membership(self) -> None:
        # The room must not even be acknowledged to an outsider.
        with _Ctx(captain_side="home", viewable=False), self.assertRaises(HTTPException) as caught:
            await _resolve(_auth_user())
        self.assertEqual(caught.exception.status_code, 403)
