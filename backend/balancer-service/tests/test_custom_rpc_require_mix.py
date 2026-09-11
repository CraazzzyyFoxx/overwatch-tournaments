from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"
for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from shared.core.errors import BaseAPIException as HTTPException  # noqa: E402
from src.rpc.custom import _require_mix, _require_workspace_admin  # noqa: E402


def _user(is_member: bool = True, is_admin: bool = False) -> MagicMock:
    user = MagicMock()
    user.is_workspace_member.return_value = is_member
    user.is_workspace_admin.return_value = is_admin
    return user


class RequireMixTests(TestCase):
    """``_require_mix`` no longer gates ``update``/``delete`` on the coarse
    workspace-level ``custom_game`` permission: a co-host who only holds the
    plain ``member`` role used to 403 here, before ``CustomGameService._writable``
    -- the actual per-game host-or-co-host grant -- ever got a look. Only
    ``create`` still checks the role permission, since a brand-new mix has no
    per-game grant yet to fall back on.
    """

    def test_read_needs_only_membership(self) -> None:
        with patch("src.rpc.custom.c.require_workspace_permission") as perm:
            _require_mix({}, _user(True), 1, "read")
        perm.assert_not_called()

    def test_read_rejects_a_non_member(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            _require_mix({}, _user(False), 1, "read")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_create_still_checks_the_workspace_role(self) -> None:
        data = {"workspace_id": 1}
        user = _user(True)
        with patch("src.rpc.custom.c.require_workspace_permission") as perm:
            _require_mix(data, user, 1, "create")
        perm.assert_called_once_with(data, user, 1, "custom_game", "create")

    def test_create_rejects_a_non_member_before_checking_the_role(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            _require_mix({}, _user(False), 1, "create")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_update_skips_the_workspace_role_check(self) -> None:
        with patch("src.rpc.custom.c.require_workspace_permission") as perm:
            _require_mix({}, _user(True), 1, "update")
        perm.assert_not_called()

    def test_delete_skips_the_workspace_role_check(self) -> None:
        with patch("src.rpc.custom.c.require_workspace_permission") as perm:
            _require_mix({}, _user(True), 1, "delete")
        perm.assert_not_called()

    def test_update_still_rejects_a_non_member(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            _require_mix({}, _user(False), 1, "update")
        self.assertEqual(ctx.exception.status_code, 403)


class RequireWorkspaceAdminTests(TestCase):
    """``set_discord_channel`` and ``hard_delete`` need more than host-or-co-host:
    one destroys rows, the other points the workspace's Discord somewhere else.
    """

    def test_admin_passes(self) -> None:
        _require_workspace_admin(_user(is_admin=True), 1)

    def test_plain_host_is_rejected(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            _require_workspace_admin(_user(is_admin=False), 1)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail, "Workspace admin required")
