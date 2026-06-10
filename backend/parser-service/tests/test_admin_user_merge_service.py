from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "parser-service"))

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ["DEBUG"] = "false"

merge_service = importlib.import_module("src.services.admin.user_merge")
merge_schemas = importlib.import_module("src.schemas.admin.user_merge")


class AdminUserMergeServiceTests(IsolatedAsyncioTestCase):
    async def test_preview_rejects_same_source_and_target(self) -> None:
        request = merge_schemas.UserMergePreviewRequest(
            source_user_id=7,
            target_user_id=7,
        )

        with self.assertRaises(Exception) as ctx:
            await merge_service.preview_merge(SimpleNamespace(), request)

        self.assertEqual(400, ctx.exception.status_code)
        self.assertIn("different", ctx.exception.detail)

    async def test_preview_reports_auth_conflict_when_both_users_have_auth_links(self) -> None:
        preview = merge_service._build_preview_from_context(  # type: ignore[attr-defined]
            context=SimpleNamespace(
                source=SimpleNamespace(
                    id=10,
                    name="Source",
                    avatar_url=None,
                    discord=[],
                    battle_tag=[],
                    twitch=[],
                ),
                target=SimpleNamespace(
                    id=20,
                    name="Target",
                    avatar_url=None,
                    discord=[],
                    battle_tag=[],
                    twitch=[],
                ),
                source_auth_links=2,
                target_auth_links=1,
                affected_counts=merge_service.empty_affected_counts(),
            ),
            request=merge_schemas.UserMergePreviewRequest(source_user_id=10, target_user_id=20),
        )

        self.assertTrue(preview.conflicts.has_auth_conflict)
        self.assertIn("auth", preview.conflicts.summary.lower())

    async def test_empty_affected_counts_covers_all_expected_reference_keys(self) -> None:
        counts = merge_service.empty_affected_counts()

        self.assertEqual(
            {
                "tournament.player.user_id",
                "tournament.team.captain_id",
                "matches.statistics.user_id",
                "matches.kill_feed.killer_id",
                "matches.kill_feed.victim_id",
                "matches.assists.user_id",
                "matches.assists.related_user_id",
                "achievements.evaluation_result.user_id",
                "achievements.override.user_id",
                "achievements.user.user_id",
                "balancer.registration.user_id",
                "analytics.balance_player_snapshot.user_id",
                "log_processing.record.uploader_id",
                "auth.user_player.player_id",
            },
            set(counts.keys()),
        )

    async def test_execute_rejects_stale_preview_fingerprint(self) -> None:
        request = merge_schemas.UserMergeExecuteRequest(
            source_user_id=10,
            target_user_id=20,
            preview_fingerprint="stale-fingerprint",
            field_policy=merge_schemas.UserMergeFieldPolicy(name="target", avatar_url="target"),
            identity_selection=merge_schemas.UserMergeIdentitySelection(),
        )

        with patch.object(
            merge_service,
            "preview_merge",
            AsyncMock(
                return_value=merge_schemas.UserMergePreviewResponse(
                    source=merge_schemas.UserMergeUserSummary(
                        id=10,
                        name="Source",
                        avatar_url=None,
                        discord=[],
                        battle_tag=[],
                        twitch=[],
                        auth_links=0,
                    ),
                    target=merge_schemas.UserMergeUserSummary(
                        id=20,
                        name="Target",
                        avatar_url=None,
                        discord=[],
                        battle_tag=[],
                        twitch=[],
                        auth_links=0,
                    ),
                    conflicts=merge_schemas.UserMergeConflictSummary(
                        has_auth_conflict=False,
                        summary=None,
                    ),
                    affected_counts=merge_service.empty_affected_counts(),
                    field_options=merge_schemas.UserMergeFieldOptions(
                        name={"source": "Source", "target": "Target"},
                        avatar_url={"source": None, "target": None},
                    ),
                    preview_fingerprint="fresh-fingerprint",
                )
            ),
        ):
            with self.assertRaises(Exception) as ctx:
                await merge_service.execute_merge(SimpleNamespace(), request, operator_auth_user_id=99)

        self.assertEqual(409, ctx.exception.status_code)
        self.assertIn("stale", ctx.exception.detail.lower())

    async def test_apply_identity_selection_moves_selected_rows_and_dedupes_duplicates(self) -> None:
        source = SimpleNamespace(
            discord=[
                SimpleNamespace(id=1, user_id=10, name="move-me"),
                SimpleNamespace(id=2, user_id=10, name="duplicate"),
            ],
            battle_tag=[],
            twitch=[],
        )
        target = SimpleNamespace(
            discord=[SimpleNamespace(id=3, user_id=20, name="duplicate")],
            battle_tag=[],
            twitch=[],
        )
        session = SimpleNamespace(delete=AsyncMock())
        identity_selection = merge_schemas.UserMergeIdentitySelection(discord_ids=[1, 2])

        result = await merge_service.apply_identity_selection(session, source, target, identity_selection)

        self.assertEqual(20, source.discord[0].user_id)
        self.assertEqual([1], result["moved"]["discord"])
        self.assertEqual([2], result["deduped"]["discord"])
        session.delete.assert_awaited_once_with(source.discord[1])

    async def test_reference_is_unavailable_when_legacy_achievement_table_missing(self) -> None:
        session = SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(scalar=lambda: False))
        )

        is_available = await merge_service._reference_is_available(session, "achievements.user.user_id")  # type: ignore[attr-defined]

        self.assertFalse(is_available)
