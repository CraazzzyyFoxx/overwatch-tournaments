from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlparse

import sqlalchemy as sa

from shared.clients import S3Client
from shared.clients.s3.upload import upload_asset
from shared.models.achievements.achievement import AchievementRule
from src import models
from src.services.achievement.engine.validation import validate_rule_definition

EXPORT_SCHEMA_VERSION = 1


@dataclass(slots=True)
class PortableAchievementRule:
    slug: str
    name: str
    description_ru: str
    description_en: str
    image_url: str | None
    hero_id: int | None
    category: str
    scope: str
    grain: str
    condition_tree: dict[str, Any]
    depends_on: list[str]
    enabled: bool
    rule_version: int
    min_tournament_id: int | None

    @classmethod
    def from_model(cls, rule: AchievementRule) -> PortableAchievementRule:
        return cls(
            slug=rule.slug,
            name=rule.name,
            description_ru=rule.description_ru,
            description_en=rule.description_en,
            image_url=rule.image_url,
            hero_id=rule.hero_id,
            category=str(rule.category),
            scope=str(rule.scope),
            grain=str(rule.grain),
            condition_tree=rule.condition_tree or {},
            depends_on=list(rule.depends_on or []),
            enabled=bool(rule.enabled),
            rule_version=int(rule.rule_version),
            min_tournament_id=rule.min_tournament_id,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.name,
            "description_ru": self.description_ru,
            "description_en": self.description_en,
            "image_url": self.image_url,
            "hero_id": self.hero_id,
            "category": self.category,
            "scope": self.scope,
            "grain": self.grain,
            "condition_tree": self.condition_tree,
            "depends_on": self.depends_on,
            "enabled": self.enabled,
            "rule_version": self.rule_version,
            "min_tournament_id": self.min_tournament_id,
        }


def build_export_payload(
    workspace: models.Workspace,
    rules: list[AchievementRule],
) -> dict[str, Any]:
    return {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "exported_at": datetime.now(UTC).isoformat(),
        "source_workspace": {
            "id": workspace.id,
            "slug": workspace.slug,
            "name": workspace.name,
        },
        "rules": [PortableAchievementRule.from_model(rule).as_dict() for rule in rules],
    }


async def load_rules_for_workspace(
    session,
    workspace_id: int,
    *,
    slugs: list[str] | None = None,
) -> list[AchievementRule]:
    query = sa.select(AchievementRule).where(AchievementRule.workspace_id == workspace_id)
    if slugs is not None:
        if not slugs:
            return []
        query = query.where(AchievementRule.slug.in_(slugs))
    query = query.order_by(AchievementRule.category, AchievementRule.slug)
    result = await session.execute(query)
    return list(result.scalars())


async def hero_exists(session, hero_id: int) -> bool:
    hero = await session.get(models.Hero, hero_id)
    return hero is not None


def extract_s3_key_from_public_url(public_url: str | None, image_url: str | None) -> str | None:
    if not public_url or not image_url:
        return None
    normalized_public = public_url.rstrip("/")
    if image_url.startswith(f"{normalized_public}/"):
        return image_url.removeprefix(f"{normalized_public}/")

    public_parts = urlparse(normalized_public)
    image_parts = urlparse(image_url)
    if (
        public_parts.scheme,
        public_parts.netloc,
    ) == (
        image_parts.scheme,
        image_parts.netloc,
    ):
        prefix_path = public_parts.path.rstrip("/")
        if image_parts.path.startswith(f"{prefix_path}/"):
            return image_parts.path.removeprefix(f"{prefix_path}/")
    return None


def guess_content_type_from_key(key: str) -> str:
    suffix = PurePosixPath(key).suffix.lower()
    return {
        ".webp": "image/webp",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
    }.get(suffix, "application/octet-stream")


def workspace_achievement_asset_prefix(source_workspace_slug: str) -> str:
    """The only S3 prefix a source workspace's achievement assets may live under."""
    return f"assets/achievements/{source_workspace_slug}/"


def _asset_key_is_within_workspace(key: str | None, workspace_prefix: str) -> bool:
    """Reject anything that is not a safe object key strictly under the source
    workspace's achievement-asset prefix.

    This is the guard for review finding C3 (S3-IDOR): the client-supplied
    ``image_url`` is turned into an S3 key and copied into the target workspace,
    so an unvalidated key would let an importer read *any* object in the shared
    bucket (match logs, avatars, other tenants' assets). The trailing slash on
    ``workspace_prefix`` prevents sibling-prefix confusion (``source`` vs
    ``source-evil``), and rejecting ``.``/``..``/empty path segments blocks
    traversal-style keys.
    """
    if not key:
        return False
    if any(segment in ("", ".", "..") for segment in key.split("/")):
        return False
    return key.startswith(workspace_prefix)


async def find_workspace_achievement_asset_key(
    s3: S3Client,
    *,
    source_workspace_slug: str,
    slug: str,
    image_url: str | None,
) -> str | None:
    """Resolve the S3 key of a source-workspace achievement asset.

    The returned key is ALWAYS constrained to the source workspace's own
    achievement-asset prefix and must be a real object owned by that workspace:
    the authoritative allow-list is ``s3.list_objects(prefix)``. A client-supplied
    ``image_url`` may only *select* among those existing keys — it can never
    introduce an arbitrary key (see review finding C3).
    """
    workspace_prefix = workspace_achievement_asset_prefix(source_workspace_slug)
    available_keys = set(await s3.list_objects(workspace_prefix))
    if not available_keys:
        return None

    key_from_url = extract_s3_key_from_public_url(getattr(s3, "_public_url", None), image_url)
    if (
        key_from_url
        and _asset_key_is_within_workspace(key_from_url, workspace_prefix)
        and key_from_url in available_keys
    ):
        return key_from_url

    slug_prefix = f"{workspace_prefix}{slug}."
    matching = sorted(key for key in available_keys if key.startswith(slug_prefix))
    return matching[0] if matching else None


async def copy_workspace_achievement_image(
    s3: S3Client,
    *,
    source_workspace: models.Workspace,
    target_workspace: models.Workspace,
    slug: str,
    image_url: str | None,
) -> tuple[str | None, str | None]:
    if not image_url:
        return None, None

    source_key = await find_workspace_achievement_asset_key(
        s3,
        source_workspace_slug=source_workspace.slug,
        slug=slug,
        image_url=image_url,
    )
    if not source_key:
        return None, f"Image asset for '{slug}' was not found in workspace '{source_workspace.slug}'"

    content = await s3.get_object(source_key)
    if content is None:
        return None, f"Image asset for '{slug}' could not be read from storage"

    head = await s3.head_object(source_key)
    content_type = (head or {}).get("ContentType") or guess_content_type_from_key(source_key)
    upload_result = await upload_asset(
        s3,
        asset_type="achievements",
        slug=slug,
        file_data=content,
        content_type=content_type,
        workspace_slug=target_workspace.slug,
    )
    if not upload_result.success:
        return None, f"Image asset for '{slug}' could not be copied: {upload_result.error}"

    return upload_result.public_url, None


def _apply_rule_data(
    rule: AchievementRule,
    payload: PortableAchievementRule,
    *,
    hero_id: int | None,
    image_url: str | None,
) -> AchievementRule:
    rule.slug = payload.slug
    rule.name = payload.name
    rule.description_ru = payload.description_ru
    rule.description_en = payload.description_en
    rule.image_url = image_url
    rule.hero_id = hero_id
    rule.category = payload.category
    rule.scope = payload.scope
    rule.grain = payload.grain
    rule.condition_tree = payload.condition_tree
    rule.depends_on = payload.depends_on
    rule.enabled = payload.enabled
    rule.rule_version = payload.rule_version
    rule.min_tournament_id = payload.min_tournament_id
    return rule


async def import_portable_rules(
    session,
    s3: S3Client | None,
    *,
    target_workspace: models.Workspace,
    rules: list[PortableAchievementRule],
    source_workspace: models.Workspace | None = None,
) -> dict[str, Any]:
    validation_errors: list[dict[str, Any]] = []
    for payload in rules:
        errors, _inferred_grain = validate_rule_definition(payload.condition_tree, payload.grain)
        if errors:
            validation_errors.append({"slug": payload.slug, "errors": errors})
    if validation_errors:
        raise ValueError(validation_errors)

    existing_rules = {
        rule.slug: rule
        for rule in await load_rules_for_workspace(
            session,
            target_workspace.id,
            slugs=[payload.slug for payload in rules],
        )
    }

    created = 0
    updated = 0
    warnings: list[dict[str, str]] = []

    for payload in rules:
        hero_id = payload.hero_id
        if hero_id is not None and not await hero_exists(session, hero_id):
            warnings.append(
                {
                    "slug": payload.slug,
                    "message": f"Hero #{hero_id} does not exist in target environment; hero link was cleared",
                }
            )
            hero_id = None

        next_image_url: str | None = None
        if payload.image_url:
            if source_workspace is None or s3 is None:
                warnings.append(
                    {
                        "slug": payload.slug,
                        "message": "Image source workspace is unavailable; image was not imported",
                    }
                )
            else:
                next_image_url, image_warning = await copy_workspace_achievement_image(
                    s3,
                    source_workspace=source_workspace,
                    target_workspace=target_workspace,
                    slug=payload.slug,
                    image_url=payload.image_url,
                )
                if image_warning:
                    warnings.append({"slug": payload.slug, "message": image_warning})

        existing = existing_rules.get(payload.slug)
        if existing is None:
            rule = AchievementRule(workspace_id=target_workspace.id)
            _apply_rule_data(rule, payload, hero_id=hero_id, image_url=next_image_url)
            session.add(rule)
            existing_rules[payload.slug] = rule
            created += 1
            continue

        _apply_rule_data(existing, payload, hero_id=hero_id, image_url=next_image_url)
        updated += 1

    return {
        "created": created,
        "updated": updated,
        "warnings": warnings,
    }
