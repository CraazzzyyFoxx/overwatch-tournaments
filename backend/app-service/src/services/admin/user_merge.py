from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

import sqlalchemy as sa
from cashews import cache
from shared.core.errors import BaseAPIException as HTTPException
from shared.core import http_status as status
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.core.social import normalize_social_handle

from src import models
from src.schemas.admin import user_merge as merge_schemas

REFERENCE_CONFIG: tuple[tuple[str, type, str], ...] = (
    ("tournament.player.user_id", models.Player, "user_id"),
    ("tournament.team.captain_id", models.Team, "captain_id"),
    ("matches.statistics.user_id", models.MatchStatistics, "user_id"),
    ("matches.kill_feed.killer_id", models.MatchKillFeed, "killer_id"),
    ("matches.kill_feed.victim_id", models.MatchKillFeed, "victim_id"),
    ("matches.assists.user_id", models.MatchEvent, "user_id"),
    ("matches.assists.related_user_id", models.MatchEvent, "related_user_id"),
    ("achievements.evaluation_result.user_id", models.AchievementEvaluationResult, "user_id"),
    ("achievements.override.user_id", models.AchievementOverride, "user_id"),
    ("achievements.user.user_id", models.AchievementUser, "user_id"),
    ("balancer.registration.user_id", models.BalancerRegistration, "user_id"),
    ("analytics.balance_player_snapshot.user_id", models.AnalyticsBalancePlayerSnapshot, "user_id"),
    ("log_processing.record.uploader_id", models.LogProcessingRecord, "uploader_id"),
)

OPTIONAL_REFERENCE_TABLES: dict[str, str] = {
    "achievements.user.user_id": 'achievements."user"',
}


@dataclass
class MergeContext:
    source: models.User
    target: models.User
    source_auth_links: int
    target_auth_links: int
    affected_counts: dict[str, int]


def empty_affected_counts() -> dict[str, int]:
    counts = {key: 0 for key, _, _ in REFERENCE_CONFIG}
    counts["auth.user_player.player_id"] = 0
    return counts


async def preview_merge(
    session: AsyncSession,
    request: merge_schemas.UserMergePreviewRequest,
) -> merge_schemas.UserMergePreviewResponse:
    _validate_merge_pair(request.source_user_id, request.target_user_id)
    context = await _load_merge_context(session, request.source_user_id, request.target_user_id)
    return _build_preview_from_context(context=context, request=request)


def _build_preview_from_context(
    context: MergeContext,
    request: merge_schemas.UserMergePreviewRequest,
) -> merge_schemas.UserMergePreviewResponse:
    target_dup_keys = {
        (account.provider, normalize_social_handle(account.provider, account.username))
        for account in context.target.social_accounts
    }
    source_summary = _build_user_summary(
        context.source,
        auth_links=context.source_auth_links,
        target_dup_keys=target_dup_keys,
    )
    target_summary = _build_user_summary(
        context.target,
        auth_links=context.target_auth_links,
        target_dup_keys=None,
    )

    has_auth_conflict = context.source_auth_links > 0 and context.target_auth_links > 0
    summary = None
    if has_auth_conflict:
        summary = "Merge blocked: both profiles already have auth links."

    preview = merge_schemas.UserMergePreviewResponse(
        source=source_summary,
        target=target_summary,
        conflicts=merge_schemas.UserMergeConflictSummary(
            has_auth_conflict=has_auth_conflict,
            summary=summary,
        ),
        affected_counts=dict(context.affected_counts),
        field_options=merge_schemas.UserMergeFieldOptions(
            name={"source": context.source.name, "target": context.target.name},
            avatar_url={
                "source": context.source.avatar_url,
                "target": context.target.avatar_url,
            },
        ),
        preview_fingerprint="",
    )
    preview.preview_fingerprint = _build_preview_fingerprint(preview)
    return preview


async def execute_merge(
    session: AsyncSession,
    request: merge_schemas.UserMergeExecuteRequest,
    *,
    operator_auth_user_id: int | None,
) -> merge_schemas.UserMergeExecuteResponse:
    _validate_merge_pair(request.source_user_id, request.target_user_id)
    preview_request = merge_schemas.UserMergePreviewRequest(
        source_user_id=request.source_user_id,
        target_user_id=request.target_user_id,
    )
    preview = await preview_merge(session, preview_request)
    if preview.preview_fingerprint != request.preview_fingerprint:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Merge preview is stale. Refresh preview and try again.",
        )
    if preview.conflicts.has_auth_conflict:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=preview.conflicts.summary or "Merge blocked by auth-link conflict.",
        )

    context = await _load_merge_context(session, request.source_user_id, request.target_user_id)
    desired_name = _pick_field_value(
        request.field_policy.name,
        context.source.name,
        context.target.name,
    )
    desired_avatar_url = _pick_field_value(
        request.field_policy.avatar_url,
        context.source.avatar_url,
        context.target.avatar_url,
    )
    identity_result_raw = await apply_identity_selection(
        session,
        context.source,
        context.target,
        request.identity_selection,
    )
    affected_counts = empty_affected_counts()

    try:
        await session.flush()
        for reference_key, model, column_name in REFERENCE_CONFIG:
            if not await _reference_is_available(session, reference_key):
                continue
            if reference_key == "achievements.evaluation_result.user_id":
                affected_counts[reference_key] = await _merge_achievement_evaluation_results(
                    session,
                    source_user_id=context.source.id,
                    target_user_id=context.target.id,
                )
                continue
            affected_counts[reference_key] = await _reassign_reference(
                session,
                model,
                column_name,
                source_user_id=context.source.id,
                target_user_id=context.target.id,
            )

        affected_counts["auth.user_player.player_id"] = await _merge_auth_user_links(
            session,
            source_user_id=context.source.id,
            target_user_id=context.target.id,
            source_auth_links=context.source_auth_links,
            target_auth_links=context.target_auth_links,
        )

        await _delete_source_user_row(session, context.source.id)
        await session.flush()

        context.target.name = desired_name
        context.target.avatar_url = desired_avatar_url
        await session.flush()

        audit = models.UserMergeAudit(
            source_user_id=request.source_user_id,
            target_user_id=request.target_user_id,
            operator_auth_user_id=operator_auth_user_id,
            field_policy_json=request.field_policy.model_dump(mode="json"),
            moved_identity_ids_json=identity_result_raw["moved"],
            deduped_identity_ids_json=identity_result_raw["deduped"],
            affected_counts_json=affected_counts,
            preview_snapshot_json=preview.model_dump(mode="json"),
        )
        session.add(audit)
        await session.flush()
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    await _invalidate_merge_caches(
        source_user_id=request.source_user_id,
        target_user_id=request.target_user_id,
        preview=preview,
    )

    return merge_schemas.UserMergeExecuteResponse(
        deleted_source_user_id=request.source_user_id,
        surviving_target_user_id=request.target_user_id,
        affected_counts=affected_counts,
        identity_results=merge_schemas.UserMergeIdentityResult(**identity_result_raw),
        audit_id=audit.id,
    )


async def apply_identity_selection(
    session: AsyncSession,
    source: models.User,
    target: models.User,
    identity_selection: merge_schemas.UserMergeIdentitySelection,
) -> dict[str, list[int]]:
    """Move the selected source social accounts to the target, deduping on
    (provider, normalized handle). Moved accounts arrive non-primary; a single
    primary per affected provider is then ensured. Unselected source accounts are
    left on the source (and dropped when it is deleted)."""
    target_user_id = target.id
    selected_ids = set(identity_selection.social_account_ids)
    moved: list[int] = []
    deduped: list[int] = []
    target_keys = {
        (account.provider, normalize_social_handle(account.provider, account.username))
        for account in target.social_accounts
    }
    affected_providers: set[str] = set()

    for account in list(source.social_accounts):
        if account.id not in selected_ids:
            continue
        key = (account.provider, normalize_social_handle(account.provider, account.username))
        if key in target_keys:
            await session.delete(account)
            deduped.append(account.id)
            continue
        account.user_id = target_user_id
        account.is_primary = False
        target_keys.add(key)
        affected_providers.add(account.provider)
        moved.append(account.id)

    await session.flush()
    for provider in affected_providers:
        await _ensure_single_primary(session, target_user_id, provider)
    return {"moved": moved, "deduped": deduped}


async def _ensure_single_primary(session: AsyncSession, user_id: int, provider: str) -> None:
    rows = (
        await session.execute(
            select(models.SocialAccount)
            .where(models.SocialAccount.user_id == user_id, models.SocialAccount.provider == provider)
            .order_by(models.SocialAccount.created_at, models.SocialAccount.id)
        )
    ).scalars().all()
    if not rows:
        return
    primaries = [row for row in rows if row.is_primary]
    if len(primaries) == 1:
        return
    keep = primaries[0] if primaries else rows[0]
    for row in rows:
        row.is_primary = row is keep
    await session.flush()


async def _load_merge_context(
    session: AsyncSession,
    source_user_id: int,
    target_user_id: int,
) -> MergeContext:
    source = await _get_user_for_merge(session, source_user_id)
    target = await _get_user_for_merge(session, target_user_id)
    source_auth_links = await _count_auth_links(session, source_user_id)
    target_auth_links = await _count_auth_links(session, target_user_id)
    affected_counts = await _count_affected_rows(session, source_user_id)
    return MergeContext(
        source=source,
        target=target,
        source_auth_links=source_auth_links,
        target_auth_links=target_auth_links,
        affected_counts=affected_counts,
    )


async def _get_user_for_merge(session: AsyncSession, user_id: int) -> models.User:
    result = await session.execute(
        select(models.User)
        .where(models.User.id == user_id)
        .options(selectinload(models.User.social_accounts))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {user_id} not found.",
        )
    return user


async def _count_auth_links(session: AsyncSession, user_id: int) -> int:
    result = await session.execute(
        select(func.count(models.AuthUserPlayer.id)).where(
            models.AuthUserPlayer.player_id == user_id
        )
    )
    return int(result.scalar_one())


async def _count_affected_rows(session: AsyncSession, source_user_id: int) -> dict[str, int]:
    counts = empty_affected_counts()
    for reference_key, model, column_name in REFERENCE_CONFIG:
        if not await _reference_is_available(session, reference_key):
            continue
        column = getattr(model, column_name)
        result = await session.execute(select(func.count()).select_from(model).where(column == source_user_id))
        counts[reference_key] = int(result.scalar_one())
    result = await session.execute(
        select(func.count()).select_from(models.AuthUserPlayer).where(
            models.AuthUserPlayer.player_id == source_user_id
        )
    )
    counts["auth.user_player.player_id"] = int(result.scalar_one())
    return counts


async def _reference_is_available(session: AsyncSession, reference_key: str) -> bool:
    table_name = OPTIONAL_REFERENCE_TABLES.get(reference_key)
    if table_name is None:
        return True
    return await _table_exists(session, table_name)


async def _table_exists(session: AsyncSession, table_name: str) -> bool:
    result = await session.execute(
        sa.text(f"SELECT to_regclass('{table_name}') IS NOT NULL")
    )
    return bool(result.scalar())


def _build_user_summary(
    user: models.User,
    *,
    auth_links: int,
    target_dup_keys: set[tuple[str, str]] | None,
) -> merge_schemas.UserMergeUserSummary:
    return merge_schemas.UserMergeUserSummary(
        id=user.id,
        name=user.name,
        avatar_url=user.avatar_url,
        social_accounts=_build_identity_options(user, target_dup_keys),
        auth_links=auth_links,
    )


def _build_identity_options(
    user: models.User,
    duplicate_keys: set[tuple[str, str]] | None = None,
) -> list[merge_schemas.UserMergeIdentityOption]:
    items = []
    for account in sorted(user.social_accounts, key=lambda a: (a.provider, not a.is_primary, a.id)):
        key = (account.provider, normalize_social_handle(account.provider, account.username))
        items.append(
            merge_schemas.UserMergeIdentityOption(
                id=account.id,
                provider=account.provider,
                value=account.username,
                duplicate_on_target=duplicate_keys is not None and key in duplicate_keys,
            )
        )
    return items


def _pick_field_value(choice: str, source_value: str | None, target_value: str | None) -> str | None:
    return source_value if choice == "source" else target_value


def _validate_merge_pair(source_user_id: int, target_user_id: int) -> None:
    if source_user_id == target_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Source and target user must be different.",
        )


def _build_preview_fingerprint(preview: merge_schemas.UserMergePreviewResponse) -> str:
    payload = preview.model_dump(mode="json")
    payload.pop("preview_fingerprint", None)
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


async def _reassign_reference(
    session: AsyncSession,
    model: type,
    column_name: str,
    *,
    source_user_id: int,
    target_user_id: int,
) -> int:
    column = getattr(model, column_name)
    result = await session.execute(
        update(model)
        .where(column == source_user_id)
        .values({column_name: target_user_id})
    )
    return int(result.rowcount or 0)


async def _delete_source_user_row(session: AsyncSession, source_user_id: int) -> None:
    await session.execute(
        delete(models.User).where(models.User.id == source_user_id)
    )


async def _merge_achievement_evaluation_results(
    session: AsyncSession,
    *,
    source_user_id: int,
    target_user_id: int,
) -> int:
    source_result = sa.orm.aliased(models.AchievementEvaluationResult)
    target_result = sa.orm.aliased(models.AchievementEvaluationResult)
    duplicate_source_ids = (
        select(source_result.id)
        .where(
            source_result.user_id == source_user_id,
            sa.exists(
                select(target_result.id).where(
                    target_result.user_id == target_user_id,
                    target_result.achievement_rule_id == source_result.achievement_rule_id,
                    target_result.tournament_id.is_not_distinct_from(source_result.tournament_id),
                    target_result.match_id.is_not_distinct_from(source_result.match_id),
                )
            ),
        )
    )
    delete_result = await session.execute(
        delete(models.AchievementEvaluationResult).where(
            models.AchievementEvaluationResult.id.in_(duplicate_source_ids)
        )
    )
    update_result = await session.execute(
        update(models.AchievementEvaluationResult)
        .where(models.AchievementEvaluationResult.user_id == source_user_id)
        .values(user_id=target_user_id)
    )
    return int(delete_result.rowcount or 0) + int(update_result.rowcount or 0)


async def _merge_auth_user_links(
    session: AsyncSession,
    *,
    source_user_id: int,
    target_user_id: int,
    source_auth_links: int,
    target_auth_links: int,
) -> int:
    if source_auth_links == 0:
        return 0
    if target_auth_links > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Merge blocked: target profile already has auth links.",
        )
    result = await session.execute(
        update(models.AuthUserPlayer)
        .where(models.AuthUserPlayer.player_id == source_user_id)
        .values(player_id=target_user_id)
    )
    return int(result.rowcount or 0)


async def _invalidate_merge_caches(
    *,
    source_user_id: int,
    target_user_id: int,
    preview: merge_schemas.UserMergePreviewResponse,
) -> None:
    patterns = {
        "backend:get_statistics_by_heroes_all_values*",
    }
    for user_id in (source_user_id, target_user_id):
        patterns.update(
            {
                f"backend:*users*{user_id}*",
                f"backend:*profile*{user_id}*",
                f"backend:*compare*{user_id}*",
                f"backend:*tournaments*{user_id}*",
                f"backend:*maps*{user_id}*",
                f"backend:*encounters*{user_id}*",
                f"backend:*heroes*{user_id}*",
                f"backend:*teammates*{user_id}*",
            }
        )
    for identity in preview.source.social_accounts + preview.target.social_accounts:
        patterns.add(f"backend:*{identity.value}*")
        patterns.add(f"backend:*{identity.value.replace('#', '-')}*")
    for pattern in patterns:
        await cache.delete_match(pattern)
