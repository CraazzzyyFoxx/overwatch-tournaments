"""P5.3: user_merge no longer has a plain ``tournament.player.user_id`` column to
reassign (contract step dropped it). ``_repoint_player_workspace_members`` is now
the sole mechanism that moves ``Player`` rows during a merge: it finds rows
anchored on the source's ``workspace_member`` and repoints each at the target's
membership for that row's own tournament's workspace -- otherwise
workspace-scoped analytics readers (INNER-JOIN on workspace_member_id) would
silently drop merged rows.
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
        # Two Player rows owned by source_user_id: one in workspace 1
        # (tournament 10), one in workspace 2 (tournament 20).
        rows_result = Mock()
        rows_result.all.return_value = [
            (101, 10, 1),
            (102, 20, 2),
        ]
        update_result_1 = Mock(rowcount=1)
        update_result_2 = Mock(rowcount=1)
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
            moved = await user_merge._repoint_player_workspace_members(
                session, source_user_id=5, target_user_id=77
            )

        self.assertEqual(2, get_or_create.await_count)
        # First execute() call is the SELECT; the next two are the per-row UPDATEs.
        self.assertEqual(3, session.execute.await_count)
        self.assertEqual(2, moved)

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
            execute=AsyncMock(side_effect=[rows_result, Mock(rowcount=1), Mock(rowcount=1)])
        )
        member = SimpleNamespace(id=555)

        with patch.object(
            user_merge, "get_or_create_workspace_member", AsyncMock(return_value=member)
        ) as get_or_create:
            moved = await user_merge._repoint_player_workspace_members(
                session, source_user_id=8, target_user_id=88
            )

        get_or_create.assert_awaited_once_with(session, workspace_id=5, player_id=88)
        self.assertEqual(2, moved)

    async def test_repoints_noop_when_source_has_no_player_rows(self) -> None:
        rows_result = Mock()
        rows_result.all.return_value = []
        session = SimpleNamespace(execute=AsyncMock(return_value=rows_result))

        with patch.object(
            user_merge, "get_or_create_workspace_member", AsyncMock()
        ) as get_or_create:
            moved = await user_merge._repoint_player_workspace_members(
                session, source_user_id=9, target_user_id=99
            )

        get_or_create.assert_not_awaited()
        session.execute.assert_awaited_once()
        self.assertEqual(0, moved)


class MergeAchievementEvaluationResultsTests(IsolatedAsyncioTestCase):
    """P6: ``achievements.evaluation_result`` moved to ``workspace_member_id``.

    Mirrors ``_repoint_player_workspace_members``: each row's workspace comes
    from its own rule (``AchievementRule.workspace_id``), so the target's
    workspace_member is resolved/created per workspace, and rows colliding
    with an existing target row (same rule/tournament/match) are dropped
    instead of updated.
    """

    async def test_repoints_row_with_no_target_collision(self) -> None:
        rows_result = Mock()
        rows_result.all.return_value = [(101, 7, 10, None, 1)]
        duplicate_scalar = False
        update_result = Mock(rowcount=1)
        session = SimpleNamespace(
            execute=AsyncMock(side_effect=[rows_result, update_result]),
            scalar=AsyncMock(return_value=duplicate_scalar),
        )
        member = SimpleNamespace(id=901)

        with patch.object(
            user_merge, "get_or_create_workspace_member", AsyncMock(return_value=member)
        ) as get_or_create:
            moved = await user_merge._merge_achievement_evaluation_results(
                session, source_user_id=5, target_user_id=77
            )

        get_or_create.assert_awaited_once_with(session, workspace_id=1, player_id=77)
        self.assertEqual(1, moved)

    async def test_drops_row_that_collides_with_existing_target_row(self) -> None:
        rows_result = Mock()
        rows_result.all.return_value = [(101, 7, 10, None, 1)]
        delete_result = Mock(rowcount=1)
        session = SimpleNamespace(
            execute=AsyncMock(side_effect=[rows_result, delete_result]),
            scalar=AsyncMock(return_value=True),
        )
        member = SimpleNamespace(id=901)

        with patch.object(
            user_merge, "get_or_create_workspace_member", AsyncMock(return_value=member)
        ):
            moved = await user_merge._merge_achievement_evaluation_results(
                session, source_user_id=5, target_user_id=77
            )

        # Second execute() call must be a DELETE, not an UPDATE.
        second_call_sql = str(session.execute.await_args_list[1].args[0])
        self.assertIn("DELETE", second_call_sql.upper())
        self.assertEqual(1, moved)

    async def test_resolves_workspace_member_once_per_distinct_workspace(self) -> None:
        rows_result = Mock()
        rows_result.all.return_value = [
            (101, 7, 10, None, 1),
            (102, 8, None, None, 2),
        ]
        session = SimpleNamespace(
            execute=AsyncMock(side_effect=[rows_result, Mock(rowcount=1), Mock(rowcount=1)]),
            scalar=AsyncMock(return_value=False),
        )
        members_by_workspace = {1: SimpleNamespace(id=901), 2: SimpleNamespace(id=902)}

        async def fake_get_or_create(_session, *, workspace_id, player_id):
            self.assertEqual(77, player_id)
            return members_by_workspace[workspace_id]

        with patch.object(
            user_merge, "get_or_create_workspace_member", AsyncMock(side_effect=fake_get_or_create)
        ) as get_or_create:
            moved = await user_merge._merge_achievement_evaluation_results(
                session, source_user_id=5, target_user_id=77
            )

        self.assertEqual(2, get_or_create.await_count)
        self.assertEqual(2, moved)

    async def test_noop_when_source_has_no_evaluation_result_rows(self) -> None:
        rows_result = Mock()
        rows_result.all.return_value = []
        session = SimpleNamespace(execute=AsyncMock(return_value=rows_result))

        with patch.object(
            user_merge, "get_or_create_workspace_member", AsyncMock()
        ) as get_or_create:
            moved = await user_merge._merge_achievement_evaluation_results(
                session, source_user_id=5, target_user_id=77
            )

        get_or_create.assert_not_awaited()
        self.assertEqual(0, moved)


class RepointAchievementOverrideWorkspaceMembersTests(IsolatedAsyncioTestCase):
    """P6: ``achievements.override`` moved to ``workspace_member_id``; unlike
    evaluation results it has no unique constraint to dedupe against, so rows
    are simply repointed."""

    async def test_repoints_each_distinct_rule_workspace_once(self) -> None:
        rows_result = Mock()
        rows_result.all.return_value = [
            (201, 1),
            (202, 2),
        ]
        update_result_1 = Mock(rowcount=1)
        update_result_2 = Mock(rowcount=1)
        session = SimpleNamespace(
            execute=AsyncMock(side_effect=[rows_result, update_result_1, update_result_2])
        )
        members_by_workspace = {1: SimpleNamespace(id=501), 2: SimpleNamespace(id=502)}

        async def fake_get_or_create(_session, *, workspace_id, player_id):
            self.assertEqual(77, player_id)
            return members_by_workspace[workspace_id]

        with patch.object(
            user_merge, "get_or_create_workspace_member", AsyncMock(side_effect=fake_get_or_create)
        ) as get_or_create:
            moved = await user_merge._repoint_achievement_override_workspace_members(
                session, source_user_id=5, target_user_id=77
            )

        self.assertEqual(2, get_or_create.await_count)
        self.assertEqual(2, moved)

    async def test_noop_when_source_has_no_override_rows(self) -> None:
        rows_result = Mock()
        rows_result.all.return_value = []
        session = SimpleNamespace(execute=AsyncMock(return_value=rows_result))

        with patch.object(
            user_merge, "get_or_create_workspace_member", AsyncMock()
        ) as get_or_create:
            moved = await user_merge._repoint_achievement_override_workspace_members(
                session, source_user_id=5, target_user_id=77
            )

        get_or_create.assert_not_awaited()
        self.assertEqual(0, moved)


class RepointRegistrationWorkspaceMembersTests(IsolatedAsyncioTestCase):
    """``balancer.registration.workspace_member_id`` is ``ON DELETE SET NULL``:
    a registration still anchored on the source's ``workspace_member`` would
    otherwise be silently nulled out once the source ``User`` row is deleted
    (the ``workspace_member`` cascades). Mirrors ``_repoint_player_workspace_members``,
    plus a collision guard against the ``(tournament_id, workspace_member_id)``
    unique constraint."""

    async def test_repoints_each_distinct_tournament_workspace_once(self) -> None:
        rows_result = Mock()
        rows_result.all.return_value = [
            (101, 10, 1),
            (102, 20, 2),
        ]
        session = SimpleNamespace(
            execute=AsyncMock(side_effect=[rows_result, Mock(rowcount=1), Mock(rowcount=1)]),
            scalar=AsyncMock(return_value=False),
        )
        members_by_workspace = {1: SimpleNamespace(id=901), 2: SimpleNamespace(id=902)}

        async def fake_get_or_create(_session, *, workspace_id, player_id):
            self.assertEqual(77, player_id)
            return members_by_workspace[workspace_id]

        with patch.object(
            user_merge, "get_or_create_workspace_member", AsyncMock(side_effect=fake_get_or_create)
        ) as get_or_create:
            moved = await user_merge._repoint_registration_workspace_members(
                session, source_user_id=5, target_user_id=77
            )

        self.assertEqual(2, get_or_create.await_count)
        self.assertEqual(2, moved)

    async def test_repoints_reuses_resolved_member_for_shared_workspace(self) -> None:
        rows_result = Mock()
        rows_result.all.return_value = [
            (201, 30, 5),
            (202, 31, 5),
        ]
        session = SimpleNamespace(
            execute=AsyncMock(side_effect=[rows_result, Mock(rowcount=1), Mock(rowcount=1)]),
            scalar=AsyncMock(return_value=False),
        )
        member = SimpleNamespace(id=555)

        with patch.object(
            user_merge, "get_or_create_workspace_member", AsyncMock(return_value=member)
        ) as get_or_create:
            moved = await user_merge._repoint_registration_workspace_members(
                session, source_user_id=8, target_user_id=88
            )

        get_or_create.assert_awaited_once_with(session, workspace_id=5, player_id=88)
        self.assertEqual(2, moved)

    async def test_skips_row_that_would_collide_with_existing_target_registration(self) -> None:
        """Target already has a live registration in the same tournament: the
        unique constraint on (tournament_id, workspace_member_id) would be
        violated by repointing, so the row is left alone (no UPDATE issued)."""
        rows_result = Mock()
        rows_result.all.return_value = [(101, 10, 1)]
        session = SimpleNamespace(
            execute=AsyncMock(side_effect=[rows_result]),
            scalar=AsyncMock(return_value=True),
        )
        member = SimpleNamespace(id=901)

        with patch.object(
            user_merge, "get_or_create_workspace_member", AsyncMock(return_value=member)
        ):
            moved = await user_merge._repoint_registration_workspace_members(
                session, source_user_id=5, target_user_id=77
            )

        # Only the initial SELECT + the collision-check scalar() ran; no UPDATE.
        self.assertEqual(1, session.execute.await_count)
        self.assertEqual(0, moved)

    async def test_noop_when_source_has_no_registration_rows(self) -> None:
        rows_result = Mock()
        rows_result.all.return_value = []
        session = SimpleNamespace(execute=AsyncMock(return_value=rows_result))

        with patch.object(
            user_merge, "get_or_create_workspace_member", AsyncMock()
        ) as get_or_create:
            moved = await user_merge._repoint_registration_workspace_members(
                session, source_user_id=9, target_user_id=99
            )

        get_or_create.assert_not_awaited()
        session.execute.assert_awaited_once()
        self.assertEqual(0, moved)


class ExecuteMergeWorkspaceMemberWiringTests(IsolatedAsyncioTestCase):
    async def test_execute_merge_repoints_player_workspace_members_before_reference_config_loop(self) -> None:
        """Real invocation of ``execute_merge`` (not a re-implementation of its
        loop) with every collaborator mocked, asserting the production
        function itself calls ``_repoint_player_workspace_members`` exactly
        once (it is no longer part of REFERENCE_CONFIG at all -- Player has no
        plain user-id column left to reassign generically)."""
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

        repoint_calls: list[tuple[int, int]] = []

        async def fake_repoint(_session, *, source_user_id, target_user_id):
            repoint_calls.append((source_user_id, target_user_id))
            return 3

        registration_repoint_calls: list[tuple[int, int]] = []

        async def fake_registration_repoint(_session, *, source_user_id, target_user_id):
            registration_repoint_calls.append((source_user_id, target_user_id))
            return 2

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
            patch.object(
                user_merge, "_repoint_achievement_override_workspace_members", AsyncMock(return_value=0)
            ),
            patch.object(
                user_merge,
                "_repoint_registration_workspace_members",
                AsyncMock(side_effect=fake_registration_repoint),
            ),
            patch.object(user_merge, "_merge_auth_user_links", AsyncMock(return_value=0)),
            patch.object(user_merge, "_delete_source_user_row", AsyncMock()),
            patch.object(user_merge, "_invalidate_merge_caches", AsyncMock()),
        ):
            response = await user_merge.execute_merge(session, request, operator_auth_user_id=None)

        self.assertEqual(6, response.surviving_target_user_id)
        # The repoint fires exactly once, with (source, target) from the request --
        # and "tournament.player.user_id" is no longer a REFERENCE_CONFIG entry at all.
        self.assertEqual([(5, 6)], repoint_calls)
        self.assertNotIn("reassign:Player.user_id", reference_calls)
        self.assertEqual(3, response.affected_counts[user_merge.PLAYER_WORKSPACE_MEMBER_REFERENCE_KEY])
        # Registration workspace_member repoint fires once, right after the
        # generic REFERENCE_CONFIG loop. Since dbarch02 dropped
        # balancer.registration.user_id, the repoint is the SOLE mechanism that
        # moves registrations — the generic loop must not touch the table.
        self.assertEqual([(5, 6)], registration_repoint_calls)
        self.assertNotIn("reassign:BalancerRegistration.user_id", reference_calls)
        self.assertEqual(2, response.affected_counts[user_merge.REGISTRATION_MEMBER_REFERENCE_KEY])
