"""P5.2c: user_merge must keep ``tournament.player.workspace_member_id`` in
sync with the ``user_id`` re-point it already performs. When a losing
player's roster rows move source -> target, their workspace_member_id has
to follow into the target's membership for each row's own tournament's
workspace -- otherwise workspace-scoped analytics readers (INNER-JOIN on
workspace_member_id) silently drop merged rows.
"""

from __future__ import annotations

import importlib
import os
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

user_merge = importlib.import_module("src.services.admin.user_merge")


class RepointPlayerWorkspaceMembersTests(IsolatedAsyncioTestCase):
    async def test_repoints_each_distinct_tournament_workspace_once(self) -> None:
        # Two Player rows now owned by target_user_id: one in workspace 1
        # (tournament 10), one in workspace 2 (tournament 20).
        rows_result = Mock()
        rows_result.all.return_value = [
            (101, 10, 1),
            (102, 20, 2),
        ]
        update_result_1 = Mock()
        update_result_2 = Mock()
        session = SimpleNamespace(
            execute=AsyncMock(side_effect=[rows_result, update_result_1, update_result_2])
        )

        members_by_workspace = {1: SimpleNamespace(id=901), 2: SimpleNamespace(id=902)}

        async def fake_get_or_create(_session, *, workspace_id, player_id):
            self.assertEqual(77, player_id)
            return members_by_workspace[workspace_id]

        with patch.object(
            user_merge, "get_or_create_workspace_member", AsyncMock(side_effect=fake_get_or_create)
        ) as get_or_create:
            await user_merge._repoint_player_workspace_members(session, target_user_id=77)

        self.assertEqual(2, get_or_create.await_count)
        # First execute() call is the SELECT; the next two are the per-row UPDATEs.
        self.assertEqual(3, session.execute.await_count)

    async def test_repoints_reuses_resolved_member_for_shared_workspace(self) -> None:
        # Two Player rows in different tournaments but the same workspace: the
        # workspace_member should only be resolved once (get_or_create is
        # idempotent, but this also exercises the in-function memoization).
        rows_result = Mock()
        rows_result.all.return_value = [
            (201, 30, 5),
            (202, 31, 5),
        ]
        session = SimpleNamespace(
            execute=AsyncMock(side_effect=[rows_result, Mock(), Mock()])
        )
        member = SimpleNamespace(id=555)

        with patch.object(
            user_merge, "get_or_create_workspace_member", AsyncMock(return_value=member)
        ) as get_or_create:
            await user_merge._repoint_player_workspace_members(session, target_user_id=88)

        get_or_create.assert_awaited_once_with(session, workspace_id=5, player_id=88)

    async def test_repoints_noop_when_target_has_no_player_rows(self) -> None:
        rows_result = Mock()
        rows_result.all.return_value = []
        session = SimpleNamespace(execute=AsyncMock(return_value=rows_result))

        with patch.object(
            user_merge, "get_or_create_workspace_member", AsyncMock()
        ) as get_or_create:
            await user_merge._repoint_player_workspace_members(session, target_user_id=99)

        get_or_create.assert_not_awaited()
        session.execute.assert_awaited_once()


class ExecuteMergeWorkspaceMemberWiringTests(IsolatedAsyncioTestCase):
    async def test_execute_merge_repoints_workspace_members_right_after_player_user_id_reassign(self) -> None:
        """Real invocation of ``execute_merge`` (not a re-implementation of its
        loop) with every collaborator mocked, asserting the production
        function itself calls ``_repoint_player_workspace_members`` for
        ``tournament.player.user_id`` and for no other reference key."""
        merge_schemas = user_merge.merge_schemas
        request = merge_schemas.UserMergeExecuteRequest(
            source_user_id=5,
            target_user_id=6,
            preview_fingerprint="fp-1",
            field_policy=merge_schemas.UserMergeFieldPolicy(),
            identity_selection=merge_schemas.UserMergeIdentitySelection(),
        )
        preview = merge_schemas.UserMergePreviewResponse(
            source=merge_schemas.UserMergeUserSummary(id=5, name="Source", social_accounts=[]),
            target=merge_schemas.UserMergeUserSummary(id=6, name="Target", social_accounts=[]),
            conflicts=merge_schemas.UserMergeConflictSummary(has_auth_conflict=False),
            affected_counts=user_merge.empty_affected_counts(),
            field_options=merge_schemas.UserMergeFieldOptions(
                name={"source": "Source", "target": "Target"},
                avatar_url={"source": None, "target": None},
            ),
            preview_fingerprint="fp-1",
        )
        context = user_merge.MergeContext(
            source=SimpleNamespace(id=5, name="Source", avatar_url=None, auth_user_id=None),
            target=SimpleNamespace(id=6, name="Target", avatar_url=None, auth_user_id=None),
            source_auth_links=0,
            target_auth_links=0,
            affected_counts=user_merge.empty_affected_counts(),
        )

        session = SimpleNamespace(
            flush=AsyncMock(),
            commit=AsyncMock(),
            rollback=AsyncMock(),
            add=Mock(side_effect=lambda audit: setattr(audit, "id", 1)),
        )

        reference_calls: list[str] = []

        async def fake_reassign(_session, model, column_name, *, source_user_id, target_user_id):
            reference_calls.append(f"reassign:{model.__name__}.{column_name}")
            return 1

        repoint_calls: list[int] = []

        async def fake_repoint(_session, *, target_user_id):
            repoint_calls.append(target_user_id)

        with (
            patch.object(user_merge, "preview_merge", AsyncMock(return_value=preview)),
            patch.object(user_merge, "_load_merge_context", AsyncMock(return_value=context)),
            patch.object(
                user_merge, "apply_identity_selection", AsyncMock(return_value={"moved": [], "deduped": []})
            ),
            patch.object(user_merge, "_reference_is_available", AsyncMock(return_value=True)),
            patch.object(user_merge, "_reassign_reference", AsyncMock(side_effect=fake_reassign)),
            patch.object(
                user_merge, "_repoint_player_workspace_members", AsyncMock(side_effect=fake_repoint)
            ),
            patch.object(user_merge, "_merge_achievement_evaluation_results", AsyncMock(return_value=0)),
            patch.object(user_merge, "_merge_auth_user_links", AsyncMock(return_value=0)),
            patch.object(user_merge, "_delete_source_user_row", AsyncMock()),
            patch.object(user_merge, "_invalidate_merge_caches", AsyncMock()),
            # NOTE: app-service's `src.models` package does not currently
            # re-export `UserMergeAudit` from `shared.models.user_merge_audit`
            # (pre-existing gap, unrelated to P5.2c) -- stub it so this test can
            # exercise execute_merge() without tripping over that separate bug.
            patch.object(user_merge.models, "UserMergeAudit", Mock(side_effect=lambda **kw: SimpleNamespace(**kw)), create=True),
        ):
            response = await user_merge.execute_merge(session, request, operator_auth_user_id=None)

        self.assertEqual(6, response.surviving_target_user_id)
        # The repoint fires exactly once, right after tournament.player.user_id
        # is reassigned -- not for any other reference in REFERENCE_CONFIG.
        # tournament.player.user_id is REFERENCE_CONFIG's first entry, so its
        # reassignment (and the repoint immediately following it) must be first.
        self.assertEqual([6], repoint_calls)
        self.assertEqual("reassign:Player.user_id", reference_calls[0])
        self.assertEqual(1, reference_calls.count("reassign:Player.user_id"))
