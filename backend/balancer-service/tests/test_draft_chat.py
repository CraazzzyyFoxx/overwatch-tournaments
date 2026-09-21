"""Who the draft room lets in — ``DraftChatAccess`` only.

The resolver answers a domain question and nothing else; every room POLICY rule
on top of it (spectator read toggle, mutes, throttle, delete rights) is
``ChatService``'s and is pinned once in ``backend/tests/test_chat_service.py``.
So the two collaborators that are not the resolver -- the repositories and the
shared hidden-tournament gate -- are substituted here, and what is left is the
decision this module actually owns.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"
for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from shared.core.errors import BaseAPIException as HTTPException  # noqa: E402
from shared.services.chat import SPECTATOR_ROLE, ChatRoom  # noqa: E402
from src.services.draft import chat_access  # noqa: E402

SESSION_ID = 42
OTHER_SESSION_ID = 43
WORKSPACE_ID = 5

# ``has_admin_panel_access`` is the staff gate, NOT ``is_workspace_member``: a
# workspace_member row exists for every tournament registrant, so ROSTER is a
# player who must stay a spectator here.
CAPTAIN = SimpleNamespace(id=7, username="cap_account", has_admin_panel_access=lambda _ws: False)
STAFF = SimpleNamespace(id=1, username="organizer", has_admin_panel_access=lambda ws: ws == WORKSPACE_ID)
VIEWER = SimpleNamespace(id=99, username="viewer", has_admin_panel_access=lambda _ws: False)
ROSTER = SimpleNamespace(
    id=100,
    username="player",
    # Read-only workspace ``member``/``player`` role: on the roster, no
    # non-read grant anywhere.
    has_admin_panel_access=lambda _ws: False,
    is_workspace_member=lambda ws: ws == WORKSPACE_ID,
)


class _Sessions:
    async def get(self, _session: Any, id: int) -> Any:
        if id not in (SESSION_ID, OTHER_SESSION_ID):
            return None
        return SimpleNamespace(id=id, tournament_id=11, workspace_id=WORKSPACE_ID)


class _Teams:
    """``CAPTAIN`` captains a team of ``captained_session`` and nothing else."""

    def __init__(self, captained_session: int) -> None:
        self.captained_session = captained_session

    async def list_by_session(self, _session: Any, session_id: int) -> list[Any]:
        captain_id = CAPTAIN.id if session_id == self.captained_session else None
        return [SimpleNamespace(captain_auth_user_id=captain_id)]


class _Users:
    async def get_by_auth_user_id(self, _session: Any, auth_user_id: int) -> Any:
        return SimpleNamespace(name="Pharah") if auth_user_id == CAPTAIN.id else None


def _access(*, captained_session: int = SESSION_ID) -> chat_access.DraftChatAccess:
    return chat_access.DraftChatAccess(
        sessions_repo=_Sessions(),
        teams_repo=_Teams(captained_session),
        user_repo=_Users(),
    )


async def _viewable(*_args: Any, **_kwargs: Any) -> Any:
    return SimpleNamespace(id=11)


class DraftChatAccessTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        # The hidden-tournament gate is shared and tested where it lives; here
        # it is the "this room is viewable at all" precondition.
        patcher = patch.object(chat_access, "assert_tournament_viewable", _viewable)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.room = ChatRoom.draft(SESSION_ID)

    async def test_captain_of_this_session_writes_as_captain(self) -> None:
        membership = await _access().resolve(object(), CAPTAIN, self.room)

        self.assertEqual(membership.role, "captain")
        self.assertTrue(membership.can_write)
        self.assertFalse(membership.can_moderate)
        # The linked player's name, not the auth account's login.
        self.assertEqual(membership.display_name, "Pharah")

    async def test_captain_of_another_session_is_only_a_spectator_here(self) -> None:
        """R3: the room is the session. Captaining a re-seeded draft, or the
        next tournament's, buys nothing in this conversation."""
        membership = await _access(captained_session=OTHER_SESSION_ID).resolve(object(), CAPTAIN, self.room)

        self.assertEqual(membership.role, SPECTATOR_ROLE)
        self.assertFalse(membership.can_write)

    async def test_workspace_organizer_moderates(self) -> None:
        membership = await _access().resolve(object(), STAFF, self.room)

        self.assertEqual(membership.role, "staff")
        self.assertTrue(membership.can_write)
        self.assertTrue(membership.can_moderate)
        # Staff need not be a player: the auth account's name is the floor.
        self.assertEqual(membership.display_name, "organizer")

    async def test_plain_workspace_member_is_only_a_spectator(self) -> None:
        """Registering for a tournament creates a workspace_member row and the
        baseline ``member`` role, which must not confer moderation."""
        membership = await _access().resolve(object(), ROSTER, self.room)

        self.assertEqual(membership.role, SPECTATOR_ROLE)
        self.assertFalse(membership.can_write)
        self.assertFalse(membership.can_moderate)

    async def test_anonymous_visitor_is_a_spectator(self) -> None:
        membership = await _access().resolve(object(), None, self.room)

        self.assertEqual(membership.role, SPECTATOR_ROLE)
        self.assertFalse(membership.can_write)
        self.assertFalse(membership.can_moderate)

    async def test_signed_in_outsider_is_a_spectator(self) -> None:
        membership = await _access().resolve(object(), VIEWER, self.room)

        self.assertEqual(membership.role, SPECTATOR_ROLE)
        self.assertFalse(membership.can_write)

    async def test_unknown_session_is_refused_without_disclosing_it(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            await _access().resolve(object(), STAFF, ChatRoom.draft(404404))

        self.assertEqual(caught.exception.status_code, 403)
