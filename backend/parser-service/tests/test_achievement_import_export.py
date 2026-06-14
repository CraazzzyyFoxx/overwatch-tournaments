from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
PARSER_SERVICE_ROOT = REPO_BACKEND_ROOT / "parser-service"

for candidate in (str(REPO_BACKEND_ROOT), str(PARSER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("CHALLONGE_USERNAME", "test")
os.environ.setdefault("CHALLONGE_API_KEY", "test")
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost")
os.environ.setdefault("S3_BUCKET_NAME", "test")

from shared.models.achievement import AchievementRule  # noqa: E402
from shared.models.workspace import Workspace  # noqa: E402

from src.services.achievement.import_export import (  # noqa: E402
    PortableAchievementRule,
    build_export_payload,
    copy_workspace_achievement_image,
    import_portable_rules,
)


class ExportPayloadTests(TestCase):
    def test_build_export_payload_contains_only_definition_fields(self) -> None:
        workspace = Workspace(id=7, slug="source-ws", name="Source")
        rule = AchievementRule(
            id=42,
            workspace_id=7,
            slug="alpha",
            name="Alpha",
            description_ru="RU",
            description_en="EN",
            image_url="http://cdn/assets/achievements/source-ws/alpha.webp",
            hero_id=3,
            category="overall",
            scope="global",
            grain="user",
            condition_tree={"type": "match_win"},
            depends_on=["matches.match"],
            enabled=True,
            rule_version=5,
            min_tournament_id=12,
        )

        payload = build_export_payload(workspace, [rule])

        self.assertEqual(1, payload["schema_version"])
        self.assertEqual({"id", "slug", "name"}, set(payload["source_workspace"]))
        self.assertEqual(
            {
                "slug",
                "name",
                "description_ru",
                "description_en",
                "image_url",
                "hero_id",
                "category",
                "scope",
                "grain",
                "condition_tree",
                "depends_on",
                "enabled",
                "rule_version",
                "min_tournament_id",
            },
            set(payload["rules"][0]),
        )


class CopyImageTests(IsolatedAsyncioTestCase):
    async def test_copy_workspace_achievement_image_rewrites_asset_into_target_workspace(self) -> None:
        s3 = SimpleNamespace(
            _public_url="http://cdn/bucket",
            get_object=AsyncMock(return_value=b"img-bytes"),
            head_object=AsyncMock(return_value={"ContentType": "image/webp"}),
            list_objects=AsyncMock(return_value=[]),
        )
        source_workspace = Workspace(id=1, slug="source", name="Source")
        target_workspace = Workspace(id=2, slug="target", name="Target")

        with patch(
            "src.services.achievement.import_export.upload_asset",
            AsyncMock(return_value=SimpleNamespace(success=True, public_url="http://cdn/bucket/assets/achievements/target/alpha.webp", error=None)),
        ) as upload_mock:
            copied_url, warning = await copy_workspace_achievement_image(
                s3,
                source_workspace=source_workspace,
                target_workspace=target_workspace,
                slug="alpha",
                image_url="http://cdn/bucket/assets/achievements/source/alpha.webp",
            )

        self.assertEqual("http://cdn/bucket/assets/achievements/target/alpha.webp", copied_url)
        self.assertIsNone(warning)
        upload_mock.assert_awaited_once()


class ImportRulesTests(IsolatedAsyncioTestCase):
    async def test_import_portable_rules_upserts_by_slug_and_rewrites_image_url(self) -> None:
        target_workspace = Workspace(id=10, slug="target", name="Target")
        source_workspace = Workspace(id=20, slug="source", name="Source")
        existing = AchievementRule(
            workspace_id=10,
            slug="existing",
            name="Old",
            description_ru="Old RU",
            description_en="Old EN",
            image_url=None,
            hero_id=None,
            category="overall",
            scope="global",
            grain="user",
            condition_tree={"type": "old"},
            depends_on=[],
            enabled=False,
            rule_version=1,
            min_tournament_id=None,
        )

        class FakeSession:
            def __init__(self) -> None:
                self.added: list[AchievementRule] = []

            def add(self, obj: AchievementRule) -> None:
                self.added.append(obj)

        session = FakeSession()
        payloads = [
            PortableAchievementRule(
                slug="existing",
                name="Existing Updated",
                description_ru="RU1",
                description_en="EN1",
                image_url="http://cdn/bucket/assets/achievements/source/existing.webp",
                hero_id=7,
                category="match",
                scope="match",
                grain="user_match",
                condition_tree={"type": "match_win"},
                depends_on=["matches.match"],
                enabled=True,
                rule_version=3,
                min_tournament_id=5,
            ),
            PortableAchievementRule(
                slug="new-rule",
                name="New Rule",
                description_ru="RU2",
                description_en="EN2",
                image_url=None,
                hero_id=None,
                category="match",
                scope="match",
                grain="user_match",
                condition_tree={"type": "match_win"},
                depends_on=[],
                enabled=True,
                rule_version=1,
                min_tournament_id=None,
            ),
        ]

        with patch(
            "src.services.achievement.import_export.load_rules_for_workspace",
            AsyncMock(return_value=[existing]),
        ), patch(
            "src.services.achievement.import_export.hero_exists",
            AsyncMock(return_value=True),
        ), patch(
            "src.services.achievement.import_export.copy_workspace_achievement_image",
            AsyncMock(return_value=("http://cdn/bucket/assets/achievements/target/existing.webp", None)),
        ):
            result = await import_portable_rules(
                session,
                s3=SimpleNamespace(),
                target_workspace=target_workspace,
                rules=payloads,
                source_workspace=source_workspace,
            )

        self.assertEqual({"created": 1, "updated": 1, "warnings": []}, result)
        self.assertEqual("Existing Updated", existing.name)
        self.assertEqual("http://cdn/bucket/assets/achievements/target/existing.webp", existing.image_url)
        self.assertEqual(1, len(session.added))
        self.assertEqual("new-rule", session.added[0].slug)

    async def test_import_portable_rules_raises_on_validation_errors(self) -> None:
        target_workspace = Workspace(id=10, slug="target", name="Target")
        payload = PortableAchievementRule(
            slug="broken",
            name="Broken",
            description_ru="RU",
            description_en="EN",
            image_url=None,
            hero_id=None,
            category="overall",
            scope="global",
            grain="user",
            condition_tree={"type": "bad"},
            depends_on=[],
            enabled=True,
            rule_version=1,
            min_tournament_id=None,
        )

        with patch(
            "src.services.achievement.import_export.validate_rule_definition",
            return_value=(["invalid rule"], None),
        ):
            with self.assertRaises(ValueError) as ctx:
                await import_portable_rules(
                    session=SimpleNamespace(add=lambda _obj: None),
                    s3=None,
                    target_workspace=target_workspace,
                    rules=[payload],
                    source_workspace=None,
                )

        self.assertEqual([{"slug": "broken", "errors": ["invalid rule"]}], ctx.exception.args[0])
