"""P5.3: user_merge no longer has a plain ``tournament.player.user_id`` column to
reassign (contract step dropped it). ``_repoint_player_workspace_members`` is now
the sole mechanism that moves ``Player`` rows during a merge: it finds rows
anchored on the source's ``workspace_member`` and repoints each at the target's
membership for that row's own tournament's workspace -- otherwise
workspace-scoped analytics readers (INNER-JOIN on workspace_member_id) would
silently drop merged rows.

All four repoint/merge methods now issue **one set-based statement per resolved
target member** instead of one per row, so the shared-workspace cases below also
pin the statement count: two roster rows in one workspace must cost one UPDATE
reporting ``rowcount=2``, not two UPDATEs reporting 1 each.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

user_merge = importlib.import_module("src.services.admin.user_merge")
merges = user_merge.merges


def _rows(*values: tuple) -> Mock:
    result = Mock()
    result.all.return_value = list(values)
    return result


def _probe(*colliding_ids: int) -> Mock:
    """The set-based collision probe's result: ``.scalars().all()`` -> ids."""
    result = Mock()
    result.scalars.return_value.all.return_value = list(colliding_ids)
    return result


def _sql(session: Any, index: int) -> str:
    return str(session.execute.await_args_list[index].args[0]).upper()


class RepointPlayerWorkspaceMembersTests(IsolatedAsyncioTestCase):
    async def test_repoints_each_distinct_tournament_workspace_once(self) -> None:
        # Two Player rows owned by source_user_id: one in workspace 1
        # (tournament 10), one in workspace 2 (tournament 20).
        session = SimpleNamespace(
            execute=AsyncMock(side_effect=[_rows((101, 10, 1), (102, 20, 2)), Mock(rowcount=1), Mock(rowcount=1)])
        )

        members_by_workspace = {1: SimpleNamespace(id=901), 2: SimpleNamespace(id=902)}

        async def fake_get_or_create(_session, *, workspace_id, player_id):
            self.assertEqual(77, player_id)
            return members_by_workspace[workspace_id]

        with patch.object(
            user_merge, "get_or_create_workspace_member", AsyncMock(side_effect=fake_get_or_create)
        ) as get_or_create:
            moved = await merges._repoint_player_workspace_members(session, source_user_id=5, target_user_id=77)

        self.assertEqual(2, get_or_create.await_count)
        # First execute() call is the SELECT; the next two are the per-workspace UPDATEs.
        self.assertEqual(3, session.execute.await_count)
        self.assertEqual(2, moved)

    async def test_repoints_a_shared_workspace_in_one_bulk_update(self) -> None:
        # Two Player rows in different tournaments but the same workspace: the
        # workspace_member is resolved once and both rows move in a single
        # UPDATE ... WHERE id IN (...), which is what rowcount=2 reports.
        session = SimpleNamespace(execute=AsyncMock(side_effect=[_rows((201, 30, 5), (202, 31, 5)), Mock(rowcount=2)]))
        member = SimpleNamespace(id=555)

        with patch.object(
            user_merge, "get_or_create_workspace_member", AsyncMock(return_value=member)
        ) as get_or_create:
            moved = await merges._repoint_player_workspace_members(session, source_user_id=8, target_user_id=88)

        get_or_create.assert_awaited_once_with(session, workspace_id=5, player_id=88)
        self.assertEqual(2, session.execute.await_count)
        self.assertIn("UPDATE", _sql(session, 1))
        self.assertEqual(2, moved)

    async def test_repoints_noop_when_source_has_no_player_rows(self) -> None:
        session = SimpleNamespace(execute=AsyncMock(return_value=_rows()))

        with patch.object(user_merge, "get_or_create_workspace_member", AsyncMock()) as get_or_create:
            moved = await merges._repoint_player_workspace_members(session, source_user_id=9, target_user_id=99)

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

    The collision check is one set-based probe per workspace batch (returning
    the colliding source ids) rather than an ``EXISTS`` scalar per row.
    """

    async def test_repoints_row_with_no_target_collision(self) -> None:
        session = SimpleNamespace(
            execute=AsyncMock(side_effect=[_rows((101, 7, 10, None, 1)), _probe(), Mock(rowcount=1)])
        )
        member = SimpleNamespace(id=901)

        with patch.object(
            user_merge, "get_or_create_workspace_member", AsyncMock(return_value=member)
        ) as get_or_create:
            moved = await merges._merge_achievement_evaluation_results(session, source_user_id=5, target_user_id=77)

        get_or_create.assert_awaited_once_with(session, workspace_id=1, player_id=77)
        self.assertIn("UPDATE", _sql(session, 2))
        self.assertEqual(1, moved)

    async def test_drops_row_that_collides_with_existing_target_row(self) -> None:
        session = SimpleNamespace(
            execute=AsyncMock(side_effect=[_rows((101, 7, 10, None, 1)), _probe(101), Mock(rowcount=1)])
        )
        member = SimpleNamespace(id=901)

        with patch.object(user_merge, "get_or_create_workspace_member", AsyncMock(return_value=member)):
            moved = await merges._merge_achievement_evaluation_results(session, source_user_id=5, target_user_id=77)

        # After the SELECT and the collision probe, the write must be a DELETE.
        self.assertIn("DELETE", _sql(session, 2))
        self.assertEqual(1, moved)

    async def test_resolves_workspace_member_once_per_distinct_workspace(self) -> None:
        session = SimpleNamespace(
            execute=AsyncMock(
                side_effect=[
                    _rows((101, 7, 10, None, 1), (102, 8, None, None, 2)),
                    _probe(),
                    Mock(rowcount=1),
                    _probe(),
                    Mock(rowcount=1),
                ]
            )
        )
        members_by_workspace = {1: SimpleNamespace(id=901), 2: SimpleNamespace(id=902)}

        async def fake_get_or_create(_session, *, workspace_id, player_id):
            self.assertEqual(77, player_id)
            return members_by_workspace[workspace_id]

        with patch.object(
            user_merge, "get_or_create_workspace_member", AsyncMock(side_effect=fake_get_or_create)
        ) as get_or_create:
            moved = await merges._merge_achievement_evaluation_results(session, source_user_id=5, target_user_id=77)

        self.assertEqual(2, get_or_create.await_count)
        self.assertEqual(2, moved)

    async def test_noop_when_source_has_no_evaluation_result_rows(self) -> None:
        session = SimpleNamespace(execute=AsyncMock(return_value=_rows()))

        with patch.object(user_merge, "get_or_create_workspace_member", AsyncMock()) as get_or_create:
            moved = await merges._merge_achievement_evaluation_results(session, source_user_id=5, target_user_id=77)

        get_or_create.assert_not_awaited()
        self.assertEqual(0, moved)


class RepointAchievementOverrideWorkspaceMembersTests(IsolatedAsyncioTestCase):
    """P6: ``achievements.override`` moved to ``workspace_member_id``; unlike
    evaluation results it has no unique constraint to dedupe against, so rows
    are simply repointed -- one bulk UPDATE per distinct rule workspace, with
    no collision probe at all."""

    async def test_repoints_each_distinct_rule_workspace_once(self) -> None:
        session = SimpleNamespace(
            execute=AsyncMock(side_effect=[_rows((201, 1), (202, 2)), Mock(rowcount=1), Mock(rowcount=1)])
        )
        members_by_workspace = {1: SimpleNamespace(id=501), 2: SimpleNamespace(id=502)}

        async def fake_get_or_create(_session, *, workspace_id, player_id):
            self.assertEqual(77, player_id)
            return members_by_workspace[workspace_id]

        with patch.object(
            user_merge, "get_or_create_workspace_member", AsyncMock(side_effect=fake_get_or_create)
        ) as get_or_create:
            moved = await merges._repoint_achievement_override_workspace_members(
                session, source_user_id=5, target_user_id=77
            )

        self.assertEqual(2, get_or_create.await_count)
        self.assertEqual(3, session.execute.await_count)
        self.assertEqual(2, moved)

    async def test_repoints_a_shared_workspace_in_one_bulk_update(self) -> None:
        session = SimpleNamespace(execute=AsyncMock(side_effect=[_rows((201, 4), (202, 4)), Mock(rowcount=2)]))
        member = SimpleNamespace(id=504)

        with patch.object(
            user_merge, "get_or_create_workspace_member", AsyncMock(return_value=member)
        ) as get_or_create:
            moved = await merges._repoint_achievement_override_workspace_members(
                session, source_user_id=5, target_user_id=77
            )

        get_or_create.assert_awaited_once_with(session, workspace_id=4, player_id=77)
        self.assertEqual(2, session.execute.await_count)
        self.assertEqual(2, moved)

    async def test_noop_when_source_has_no_override_rows(self) -> None:
        session = SimpleNamespace(execute=AsyncMock(return_value=_rows()))

        with patch.object(user_merge, "get_or_create_workspace_member", AsyncMock()) as get_or_create:
            moved = await merges._repoint_achievement_override_workspace_members(
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
    unique constraint -- one set-based probe per workspace batch."""

    async def test_repoints_each_distinct_tournament_workspace_once(self) -> None:
        session = SimpleNamespace(
            execute=AsyncMock(
                side_effect=[
                    _rows((101, 10, 1), (102, 20, 2)),
                    _probe(),
                    Mock(rowcount=1),
                    _probe(),
                    Mock(rowcount=1),
                ]
            )
        )
        members_by_workspace = {1: SimpleNamespace(id=901), 2: SimpleNamespace(id=902)}

        async def fake_get_or_create(_session, *, workspace_id, player_id):
            self.assertEqual(77, player_id)
            return members_by_workspace[workspace_id]

        with patch.object(
            user_merge, "get_or_create_workspace_member", AsyncMock(side_effect=fake_get_or_create)
        ) as get_or_create:
            moved = await merges._repoint_registration_workspace_members(session, source_user_id=5, target_user_id=77)

        self.assertEqual(2, get_or_create.await_count)
        self.assertEqual(2, moved)

    async def test_repoints_a_shared_workspace_in_one_bulk_update(self) -> None:
        session = SimpleNamespace(
            execute=AsyncMock(side_effect=[_rows((201, 30, 5), (202, 31, 5)), _probe(), Mock(rowcount=2)])
        )
        member = SimpleNamespace(id=555)

        with patch.object(
            user_merge, "get_or_create_workspace_member", AsyncMock(return_value=member)
        ) as get_or_create:
            moved = await merges._repoint_registration_workspace_members(session, source_user_id=8, target_user_id=88)

        get_or_create.assert_awaited_once_with(session, workspace_id=5, player_id=88)
        self.assertEqual(3, session.execute.await_count)
        self.assertIn("UPDATE", _sql(session, 2))
        self.assertEqual(2, moved)

    async def test_skips_row_that_would_collide_with_existing_target_registration(self) -> None:
        """Target already has a live registration in the same tournament: the
        unique constraint on (tournament_id, workspace_member_id) would be
        violated by repointing, so the row is left alone (no UPDATE issued)."""
        session = SimpleNamespace(execute=AsyncMock(side_effect=[_rows((101, 10, 1)), _probe(101)]))
        member = SimpleNamespace(id=901)

        with patch.object(user_merge, "get_or_create_workspace_member", AsyncMock(return_value=member)):
            moved = await merges._repoint_registration_workspace_members(session, source_user_id=5, target_user_id=77)

        # Only the initial SELECT + the collision probe ran; no UPDATE.
        self.assertEqual(2, session.execute.await_count)
        self.assertEqual(0, moved)

    async def test_noop_when_source_has_no_registration_rows(self) -> None:
        session = SimpleNamespace(execute=AsyncMock(return_value=_rows()))

        with patch.object(user_merge, "get_or_create_workspace_member", AsyncMock()) as get_or_create:
            moved = await merges._repoint_registration_workspace_members(session, source_user_id=9, target_user_id=99)

        get_or_create.assert_not_awaited()
        session.execute.assert_awaited_once()
        self.assertEqual(0, moved)
