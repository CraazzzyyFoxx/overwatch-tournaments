"""Admin profile merge: preview, execute, and the reference repointing it implies.

``get_or_create_workspace_member`` is imported at module level and called
unqualified on purpose — the repoint methods resolve a member per *distinct
workspace*, and the tests patch this name to assert exactly that call pattern.

The four repoint/merge loops issue **one set-based statement per resolved target
member** rather than one per row: a source with 400 roster rows across two
workspaces costs 1 SELECT + 2 UPDATEs, not 400 UPDATEs. Those bulk UPDATEs are
deliberately not CRUD (no repository covers "repoint an arbitrary reference
table"), which is why they live on the service instead of behind a
``BaseRepository``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

import sqlalchemy as sa
from cashews import cache
from redis.asyncio import Redis
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.core.social import normalize_social_handle
from shared.rbac import RBAC_USER_KEY_PREFIX
from shared.repository import SocialAccountRepository, UserMergeAuditRepository, get_or_create_workspace_member
from shared.schemas.user_merge_auth import AuthMergeResult
from shared.services.auth_merge import apply_auth_merge, preview_auth_merge
from src import models, schemas
from src.services import user_cache

__all__ = ("UserMergeService", "merges")

PLAYER_WORKSPACE_MEMBER_REFERENCE_KEY = "tournament.player.workspace_member_id"
EVALUATION_RESULT_MEMBER_REFERENCE_KEY = "achievements.evaluation_result.workspace_member_id"
OVERRIDE_MEMBER_REFERENCE_KEY = "achievements.override.workspace_member_id"
REGISTRATION_MEMBER_REFERENCE_KEY = "balancer.registration.workspace_member_id"

# achievements.evaluation_result / achievements.override moved to
# workspace_member_id (P6), and balancer.registration followed (dbarch02
# dropped its user_id column): none of them are generic user_id columns
# anymore, so they are handled by dedicated workspace_member-aware
# counters/mergers (mirroring PLAYER_WORKSPACE_MEMBER_REFERENCE_KEY) instead
# of living in this table. The legacy achievements.user.user_id row was
# dropped too — its table was removed by l2g4h6i0j1k2, so it no longer needs
# a generic reassign here.
REFERENCE_CONFIG: tuple[tuple[str, type, str], ...] = (
    ("tournament.team.captain_id", models.Team, "captain_id"),
    ("matches.statistics.user_id", models.MatchStatistics, "user_id"),
    ("matches.kill_feed.killer_id", models.MatchKillFeed, "killer_id"),
    ("matches.kill_feed.victim_id", models.MatchKillFeed, "victim_id"),
    ("matches.event.user_id", models.MatchEvent, "user_id"),
    ("matches.event.related_user_id", models.MatchEvent, "related_user_id"),
    ("log_processing.record.uploader_id", models.LogProcessingRecord, "uploader_id"),
)


@dataclass
class MergeContext:
    source: models.User
    target: models.User
    source_auth_links: int
    target_auth_links: int
    affected_counts: dict[str, int]


def empty_affected_counts() -> dict[str, int]:
    counts = {key: 0 for key, _, _ in REFERENCE_CONFIG}
    counts[PLAYER_WORKSPACE_MEMBER_REFERENCE_KEY] = 0
    counts[EVALUATION_RESULT_MEMBER_REFERENCE_KEY] = 0
    counts[OVERRIDE_MEMBER_REFERENCE_KEY] = 0
    counts[REGISTRATION_MEMBER_REFERENCE_KEY] = 0
    counts["players.user.auth_user_id"] = 0
    return counts


def _build_preview_from_context(
    context: MergeContext,
    request: schemas.UserMergePreviewRequest,
) -> schemas.UserMergePreviewResponse:
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

    summary = None
    if context.source_auth_links > 0 and context.target_auth_links > 0:
        summary = "Both profiles have sign-in accounts. Review the auth merge plan and confirm account changes."

    preview = schemas.UserMergePreviewResponse(
        source=source_summary,
        target=target_summary,
        conflicts=schemas.UserMergeConflictSummary(
            has_auth_conflict=False,
            summary=summary,
        ),
        affected_counts=dict(context.affected_counts),
        field_options=schemas.UserMergeFieldOptions(
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


def _build_user_summary(
    user: models.User,
    *,
    auth_links: int,
    target_dup_keys: set[tuple[str, str]] | None,
) -> schemas.UserMergeUserSummary:
    return schemas.UserMergeUserSummary(
        id=user.id,
        name=user.name,
        avatar_url=user.avatar_url,
        social_accounts=_build_identity_options(user, target_dup_keys),
        auth_links=auth_links,
        auth_user_id=user.auth_user_id,
    )


def _build_identity_options(
    user: models.User,
    duplicate_keys: set[tuple[str, str]] | None = None,
) -> list[schemas.UserMergeIdentityOption]:
    items = []
    for account in sorted(user.social_accounts, key=lambda a: (a.provider, not a.is_primary, a.id)):
        key = (account.provider, normalize_social_handle(account.provider, account.username))
        items.append(
            schemas.UserMergeIdentityOption(
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


def _build_preview_fingerprint(preview: schemas.UserMergePreviewResponse) -> str:
    payload = preview.model_dump(mode="json")
    payload.pop("preview_fingerprint", None)
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _group_by_workspace(rows: Sequence[Sequence[int]]) -> dict[int, list[int]]:
    """``{workspace_id: [row_id, …]}`` from rows shaped ``(row_id, …, workspace_id)``.

    Every repoint SELECT below puts the row's own id first and the workspace it
    resolves to last, so one grouping serves all four. Insertion order is
    preserved: it keeps the ``get_or_create_workspace_member`` call sequence
    identical to the row order the SELECT returned, and each workspace's whole
    batch then moves in one statement.
    """
    grouped: dict[int, list[int]] = {}
    for row in rows:
        grouped.setdefault(row[-1], []).append(row[0])
    return grouped


class UserMergeService:
    def __init__(
        self,
        *,
        audits: UserMergeAuditRepository = UserMergeAuditRepository(),
        socials: SocialAccountRepository = SocialAccountRepository(),
    ) -> None:
        self.audits = audits
        self.socials = socials

    # ─── Preview / execute ───────────────────────────────────────────────────

    async def preview_merge(
        self,
        session: AsyncSession,
        request: schemas.UserMergePreviewRequest,
        *,
        operator_auth_user_id: int | None = None,
    ) -> schemas.UserMergePreviewResponse:
        _validate_merge_pair(request.source_user_id, request.target_user_id)
        context = await self._load_merge_context(session, request.source_user_id, request.target_user_id)
        preview = _build_preview_from_context(context=context, request=request)
        preview.auth_merge = await preview_auth_merge(
            session,
            context.source,
            context.target,
            request.auth_policy,
            operator_auth_user_id=operator_auth_user_id,
        )
        preview.conflicts.has_auth_conflict = bool(preview.auth_merge and preview.auth_merge.issues)
        preview.preview_fingerprint = _build_preview_fingerprint(preview)
        return preview

    async def execute_merge(
        self,
        session: AsyncSession,
        request: schemas.UserMergeExecuteRequest,
        *,
        operator_auth_user_id: int | None,
        auth_finalizer: Callable[[AuthMergeResult], Awaitable[None]] | None = None,
    ) -> schemas.UserMergeExecuteResponse:
        _validate_merge_pair(request.source_user_id, request.target_user_id)
        auth_result = None
        try:
            # Consistent ordering serializes competing merges without A->B/B->A deadlocks.
            await session.execute(
                select(models.User.id)
                .where(models.User.id.in_((request.source_user_id, request.target_user_id)))
                .order_by(models.User.id)
                .with_for_update()
            )
            preview = await self.preview_merge(
                session,
                schemas.UserMergePreviewRequest(
                    source_user_id=request.source_user_id,
                    target_user_id=request.target_user_id,
                    auth_policy=request.auth_policy,
                ),
                operator_auth_user_id=operator_auth_user_id,
            )
            if preview.preview_fingerprint != request.preview_fingerprint:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Merge preview is stale. Refresh preview and try again.",
                )
            context = await self._load_merge_context(session, request.source_user_id, request.target_user_id)
            desired_name = _pick_field_value(request.field_policy.name, context.source.name, context.target.name)
            desired_avatar_url = _pick_field_value(
                request.field_policy.avatar_url, context.source.avatar_url, context.target.avatar_url
            )
            if preview.auth_merge is not None:
                if auth_finalizer is None:
                    raise RuntimeError("Auth merge requires identity session finalization.")
                auth_result = await apply_auth_merge(
                    session,
                    context.source,
                    context.target,
                    preview.auth_merge,
                    confirm_auth_changes=request.confirm_auth_changes,
                    confirm_auth_deletion=request.confirm_auth_deletion,
                    confirm_permission_changes=request.confirm_permission_changes,
                    operator_auth_user_id=operator_auth_user_id,
                )

            identity_result_raw = await self.apply_identity_selection(
                session, context.source, context.target, request.identity_selection
            )
            affected_counts = empty_affected_counts()
            await session.flush()
            affected_counts[PLAYER_WORKSPACE_MEMBER_REFERENCE_KEY] = await self._repoint_player_workspace_members(
                session, source_user_id=context.source.id, target_user_id=context.target.id
            )
            affected_counts[EVALUATION_RESULT_MEMBER_REFERENCE_KEY] = await self._merge_achievement_evaluation_results(
                session, source_user_id=context.source.id, target_user_id=context.target.id
            )
            affected_counts[OVERRIDE_MEMBER_REFERENCE_KEY] = await self._repoint_achievement_override_workspace_members(
                session, source_user_id=context.source.id, target_user_id=context.target.id
            )
            for reference_key, model, column_name in REFERENCE_CONFIG:
                affected_counts[reference_key] = await self._reassign_reference(
                    session, model, column_name, source_user_id=context.source.id, target_user_id=context.target.id
                )
            affected_counts[REGISTRATION_MEMBER_REFERENCE_KEY] = await self._repoint_registration_workspace_members(
                session, source_user_id=context.source.id, target_user_id=context.target.id
            )
            affected_counts["players.user.auth_user_id"] = int(preview.source.auth_user_id is not None)
            if auth_result is not None:
                affected_counts.update(auth_result.transferred_counts)

            await self._delete_source_user_row(session, context.source.id)
            await session.flush()
            context.target.name = desired_name
            context.target.avatar_url = desired_avatar_url
            await session.flush()

            snapshot = preview.model_dump(mode="json")
            if auth_result is not None:
                snapshot["auth_execution"] = {
                    "confirm_auth_changes": request.confirm_auth_changes,
                    "confirm_auth_deletion": request.confirm_auth_deletion,
                    "confirm_permission_changes": request.confirm_permission_changes,
                    "result": auth_result.model_dump(mode="json"),
                    "affected_auth_user_ids": auth_result.affected_auth_user_ids,
                    "revoked_session_ids": auth_result.revoked_session_ids,
                }
            audit = models.UserMergeAudit(
                source_user_id=None,
                target_user_id=request.target_user_id,
                operator_auth_user_id=operator_auth_user_id,
                field_policy_json=request.field_policy.model_dump(mode="json"),
                moved_identity_ids_json=identity_result_raw["moved"],
                deduped_identity_ids_json=identity_result_raw["deduped"],
                affected_counts_json=affected_counts,
                preview_snapshot_json=snapshot,
            )
            await self.audits.create(session, audit)
            if auth_result is not None:
                # Fail closed before committing when identity cannot retire the old sessions.
                await auth_finalizer(auth_result)
            await session.commit()
        except Exception:
            await session.rollback()
            raise

        if auth_result is not None:
            await self._invalidate_auth_rbac_caches(auth_result.affected_auth_user_ids)
        await self._invalidate_merge_caches(
            source_user_id=request.source_user_id,
            target_user_id=request.target_user_id,
            preview=preview,
        )
        return schemas.UserMergeExecuteResponse(
            deleted_source_user_id=request.source_user_id,
            surviving_target_user_id=request.target_user_id,
            affected_counts=affected_counts,
            identity_results=schemas.UserMergeIdentityResult(**identity_result_raw),
            audit_id=audit.id,
            auth_merge=auth_result,
        )

    # ─── Identities ──────────────────────────────────────────────────────────

    async def apply_identity_selection(
        self,
        session: AsyncSession,
        source: models.User,
        target: models.User,
        identity_selection: schemas.UserMergeIdentitySelection,
    ) -> dict[str, list[int]]:
        """Move the selected source social accounts to the target, deduping on
        (provider, normalized handle). Moved accounts arrive non-primary; a single
        primary per affected provider is then ensured. When a selected source account
        is dropped as a duplicate of an unverified target account, its verification
        (and provider_user_id) is promoted onto the surviving target row so merging
        never regresses a verified identity to unverified. Unselected source accounts
        are left on the source (and dropped when it is deleted)."""
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
                existing = None
                if account.is_verified:
                    existing = next(
                        (
                            candidate
                            for candidate in target.social_accounts
                            if (candidate.provider, normalize_social_handle(candidate.provider, candidate.username))
                            == key
                        ),
                        None,
                    )
                # Read the losing row's identity out before handing it to the
                # repository: ``delete`` flushes, which is also exactly the flush
                # the promotion below needs — the partial unique index on
                # (provider, provider_user_id) never sees both rows holding the
                # same value at once.
                account_id = account.id
                account_provider_user_id = account.provider_user_id
                await self.socials.delete(session, account)
                deduped.append(account_id)
                if existing is not None and not existing.is_verified:
                    # The pre-existing target duplicate wins the row, but the source's
                    # proof of ownership must not be discarded just because it lost the
                    # dedup.
                    existing.is_verified = True
                    existing.provider_user_id = account_provider_user_id
                continue
            account.user_id = target_user_id
            account.is_primary = False
            target_keys.add(key)
            affected_providers.add(account.provider)
            moved.append(account.id)

        await session.flush()
        for provider in affected_providers:
            await self._ensure_single_primary(session, target_user_id, provider)
        return {"moved": moved, "deduped": deduped}

    async def _ensure_single_primary(self, session: AsyncSession, user_id: int, provider: str) -> None:
        rows = (
            (
                await session.execute(
                    select(models.SocialAccount)
                    .where(models.SocialAccount.user_id == user_id, models.SocialAccount.provider == provider)
                    .order_by(models.SocialAccount.created_at, models.SocialAccount.id)
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            return
        primaries = [row for row in rows if row.is_primary]
        if len(primaries) == 1:
            return
        keep = primaries[0] if primaries else rows[0]
        for row in rows:
            row.is_primary = row is keep
        await session.flush()

    # ─── Context + counts ────────────────────────────────────────────────────

    async def _load_merge_context(
        self,
        session: AsyncSession,
        source_user_id: int,
        target_user_id: int,
    ) -> MergeContext:
        source = await self._get_user_for_merge(session, source_user_id)
        target = await self._get_user_for_merge(session, target_user_id)
        source_auth_links = await self._count_auth_links(session, source_user_id)
        target_auth_links = await self._count_auth_links(session, target_user_id)
        affected_counts = await self._count_affected_rows(session, source_user_id)
        return MergeContext(
            source=source,
            target=target,
            source_auth_links=source_auth_links,
            target_auth_links=target_auth_links,
            affected_counts=affected_counts,
        )

    async def _get_user_for_merge(self, session: AsyncSession, user_id: int) -> models.User:
        result = await session.execute(
            select(models.User)
            .where(models.User.id == user_id)
            .options(selectinload(models.User.social_accounts))
            .execution_options(populate_existing=True)
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User {user_id} not found.",
            )
        return user

    async def _count_auth_links(self, session: AsyncSession, user_id: int) -> int:
        """0 or 1 — a player links to at most one auth user via ``auth_user_id``."""
        result = await session.execute(
            select(func.count())
            .select_from(models.User)
            .where(
                models.User.id == user_id,
                models.User.auth_user_id.is_not(None),
            )
        )
        return int(result.scalar_one())

    async def _count_affected_rows(self, session: AsyncSession, source_user_id: int) -> dict[str, int]:
        counts = empty_affected_counts()
        counts[PLAYER_WORKSPACE_MEMBER_REFERENCE_KEY] = await self._count_player_rows_for_source(
            session, source_user_id
        )
        counts[EVALUATION_RESULT_MEMBER_REFERENCE_KEY] = await self._count_workspace_member_rows_for_source(
            session, models.AchievementEvaluationResult, source_user_id
        )
        counts[OVERRIDE_MEMBER_REFERENCE_KEY] = await self._count_workspace_member_rows_for_source(
            session, models.AchievementOverride, source_user_id
        )
        counts[REGISTRATION_MEMBER_REFERENCE_KEY] = await self._count_workspace_member_rows_for_source(
            session, models.BalancerRegistration, source_user_id
        )
        for reference_key, model, column_name in REFERENCE_CONFIG:
            column = getattr(model, column_name)
            result = await session.execute(select(func.count()).select_from(model).where(column == source_user_id))
            counts[reference_key] = int(result.scalar_one())
        counts["players.user.auth_user_id"] = await self._count_auth_links(session, source_user_id)
        return counts

    async def _count_workspace_member_rows_for_source(
        self,
        session: AsyncSession,
        model: type,
        source_user_id: int,
    ) -> int:
        """Count rows of a ``workspace_member_id``-anchored model currently owned
        by ``source_user_id`` (joining through ``WorkspaceMember.player_id``)."""
        result = await session.execute(
            select(func.count())
            .select_from(model)
            .join(
                models.WorkspaceMember,
                models.WorkspaceMember.id == model.workspace_member_id,
            )
            .where(models.WorkspaceMember.player_id == source_user_id)
        )
        return int(result.scalar_one())

    async def _count_player_rows_for_source(self, session: AsyncSession, source_user_id: int) -> int:
        """Count ``tournament.player`` roster rows currently anchored on
        ``source_user_id``'s ``workspace_member`` (i.e. the rows a merge would move)."""
        result = await session.execute(
            select(func.count())
            .select_from(models.Player)
            .join(
                models.WorkspaceMember,
                models.WorkspaceMember.id == models.Player.workspace_member_id,
            )
            .where(models.WorkspaceMember.player_id == source_user_id)
        )
        return int(result.scalar_one())

    # ─── Reference repointing ────────────────────────────────────────────────

    async def _reassign_reference(
        self,
        session: AsyncSession,
        model: type,
        column_name: str,
        *,
        source_user_id: int,
        target_user_id: int,
    ) -> int:
        column = getattr(model, column_name)
        result = await session.execute(
            update(model).where(column == source_user_id).values({column_name: target_user_id})
        )
        return int(result.rowcount or 0)

    async def _repoint_player_workspace_members(
        self,
        session: AsyncSession,
        *,
        source_user_id: int,
        target_user_id: int,
    ) -> int:
        """Move every ``tournament.player`` roster row owned by ``source_user_id`` to
        ``target_user_id`` and return the number of rows moved.

        Contract step (iwrefac07) dropped ``tournament.player.user_id``, so
        ``workspace_member_id`` is a roster row's only identity anchor and this is
        the sole mechanism that moves ``Player`` rows during a merge (previously
        split between a generic ``user_id`` reassign and a workspace_member
        follow-up). A row is found by joining to the ``workspace_member`` it
        currently points at and checking that member's ``player_id`` against the
        source; each row's workspace is that row's own tournament's workspace
        (``tournament.workspace_id``), and it is repointed at the target's
        ``workspace_member`` in that same workspace — idempotently created if it
        doesn't exist yet.

        One UPDATE per distinct workspace, not per row.
        """
        rows = (
            await session.execute(
                select(models.Player.id, models.Player.tournament_id, models.Tournament.workspace_id)
                .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
                .join(
                    models.WorkspaceMember,
                    models.WorkspaceMember.id == models.Player.workspace_member_id,
                )
                .where(models.WorkspaceMember.player_id == source_user_id)
            )
        ).all()

        moved = 0
        for workspace_id, player_ids in _group_by_workspace(rows).items():
            member = await get_or_create_workspace_member(session, workspace_id=workspace_id, player_id=target_user_id)
            result = await session.execute(
                update(models.Player).where(models.Player.id.in_(player_ids)).values(workspace_member_id=member.id)
            )
            moved += int(result.rowcount or 0)

        return moved

    async def _delete_source_user_row(self, session: AsyncSession, source_user_id: int) -> None:
        # A set-based DELETE rather than an ORM instance delete: the row's dependents
        # are removed by the database's own ON DELETE rules, whereas an ORM cascade
        # would load and delete every loaded collection one row at a time.
        await session.execute(delete(models.User).where(models.User.id == source_user_id))

    async def _merge_achievement_evaluation_results(
        self,
        session: AsyncSession,
        *,
        source_user_id: int,
        target_user_id: int,
    ) -> int:
        """Repoint every ``achievements.evaluation_result`` row owned by
        ``source_user_id`` onto the target's ``workspace_member`` and return the
        number of rows moved (deletes + updates).

        P6 moved this table onto ``workspace_member_id``: a row's workspace is
        its own rule's workspace (``AchievementRule.workspace_id``), so — like
        ``_repoint_player_workspace_members`` — the target's member is
        resolved/created per workspace rather than assumed global. Rows that
        would collide with an existing target row on the unique key
        ``(achievement_rule_id, workspace_member_id, tournament_id, match_id)``
        are dropped instead of updated (the target already qualified).

        Per workspace: one existence probe, one DELETE, one UPDATE — not three
        statements per row.
        """
        result_model = models.AchievementEvaluationResult
        source_member = sa.orm.aliased(models.WorkspaceMember, name="source_member")
        rows = (
            await session.execute(
                select(
                    result_model.id,
                    result_model.achievement_rule_id,
                    result_model.tournament_id,
                    result_model.match_id,
                    models.AchievementRule.workspace_id,
                )
                .select_from(result_model)
                .join(
                    source_member,
                    source_member.id == result_model.workspace_member_id,
                )
                .join(
                    models.AchievementRule,
                    models.AchievementRule.id == result_model.achievement_rule_id,
                )
                .where(source_member.player_id == source_user_id)
            )
        ).all()

        existing = sa.orm.aliased(result_model, name="existing_result")
        moved = 0
        for workspace_id, row_ids in _group_by_workspace(rows).items():
            member = await get_or_create_workspace_member(session, workspace_id=workspace_id, player_id=target_user_id)
            target_member_id = member.id

            # One set-based probe for the whole batch instead of an EXISTS scalar
            # per row. A candidate collides iff the target member already holds a
            # row with the same (rule, tournament, match). Computing every
            # collision up front is safe because the candidates all still sit on
            # the *source* member, so no candidate can be its own — or another
            # candidate's — collision partner (the unique key includes
            # workspace_member_id).
            colliding = set(
                (
                    await session.execute(
                        select(result_model.id)
                        .select_from(result_model)
                        .join(
                            existing,
                            sa.and_(
                                existing.workspace_member_id == target_member_id,
                                existing.achievement_rule_id == result_model.achievement_rule_id,
                                existing.tournament_id.is_not_distinct_from(result_model.tournament_id),
                                existing.match_id.is_not_distinct_from(result_model.match_id),
                            ),
                        )
                        .where(result_model.id.in_(row_ids))
                    )
                )
                .scalars()
                .all()
            )

            to_drop = [row_id for row_id in row_ids if row_id in colliding]
            to_repoint = [row_id for row_id in row_ids if row_id not in colliding]

            if to_drop:
                result = await session.execute(delete(result_model).where(result_model.id.in_(to_drop)))
                moved += int(result.rowcount or 0)
            if to_repoint:
                result = await session.execute(
                    update(result_model)
                    .where(result_model.id.in_(to_repoint))
                    .values(workspace_member_id=target_member_id)
                )
                moved += int(result.rowcount or 0)

        return moved

    async def _repoint_achievement_override_workspace_members(
        self,
        session: AsyncSession,
        *,
        source_user_id: int,
        target_user_id: int,
    ) -> int:
        """Move every ``achievements.override`` row owned by ``source_user_id``
        onto the target's ``workspace_member`` and return the number of rows
        moved.

        Mirrors ``_merge_achievement_evaluation_results`` (each row's workspace
        comes from its own rule), but ``AchievementOverride`` carries no unique
        constraint on ``(rule, workspace_member, tournament, match)``, so rows
        are simply repointed — no dedupe/delete branch is needed, which makes
        this one bulk UPDATE per distinct workspace.
        """
        source_member = sa.orm.aliased(models.WorkspaceMember, name="source_override_member")
        rows = (
            await session.execute(
                select(models.AchievementOverride.id, models.AchievementRule.workspace_id)
                .select_from(models.AchievementOverride)
                .join(
                    source_member,
                    source_member.id == models.AchievementOverride.workspace_member_id,
                )
                .join(
                    models.AchievementRule,
                    models.AchievementRule.id == models.AchievementOverride.achievement_rule_id,
                )
                .where(source_member.player_id == source_user_id)
            )
        ).all()

        moved = 0
        for workspace_id, row_ids in _group_by_workspace(rows).items():
            member = await get_or_create_workspace_member(session, workspace_id=workspace_id, player_id=target_user_id)
            result = await session.execute(
                update(models.AchievementOverride)
                .where(models.AchievementOverride.id.in_(row_ids))
                .values(workspace_member_id=member.id)
            )
            moved += int(result.rowcount or 0)

        return moved

    async def _repoint_registration_workspace_members(
        self,
        session: AsyncSession,
        *,
        source_user_id: int,
        target_user_id: int,
    ) -> int:
        """Move every ``balancer.registration`` row anchored on ``source_user_id``'s
        ``workspace_member`` onto the target's ``workspace_member`` and return the
        number of rows moved.

        Mirrors ``_repoint_player_workspace_members`` (each row's workspace comes
        from its own tournament, via ``Tournament.workspace_id``, so the target's
        member is resolved/created per workspace). Registrations that are not
        member-anchored (``workspace_member_id IS NULL`` -- sheet-import rows) are
        excluded by the join and are correctly left untouched/NULL.

        ``balancer.registration.workspace_member_id`` has a live unique constraint
        on ``(tournament_id, workspace_member_id)``, so a row is skipped (left
        pointed at the source's member) if the target already has a live
        registration in that same tournament -- repointing it would collide. Such
        a row loses its member anchor when the source's ``User`` row is deleted
        afterwards (``workspace_member`` cascades, and this FK is
        ``ON DELETE SET NULL``), degrading to an unlinked registration rather than
        raising an ``IntegrityError`` or silently dropping the target's row.

        Per workspace: one collision probe and one UPDATE. Candidates cannot
        collide with *each other* — the same unique constraint allows the source
        member at most one live row per tournament, and soft-deleted rows are
        outside the partial index.
        """
        registration = models.BalancerRegistration
        rows = (
            await session.execute(
                select(
                    registration.id,
                    registration.tournament_id,
                    models.Tournament.workspace_id,
                )
                .select_from(registration)
                .join(
                    models.Tournament,
                    models.Tournament.id == registration.tournament_id,
                )
                .join(
                    models.WorkspaceMember,
                    models.WorkspaceMember.id == registration.workspace_member_id,
                )
                .where(models.WorkspaceMember.player_id == source_user_id)
            )
        ).all()

        existing = sa.orm.aliased(registration, name="existing_registration")
        moved = 0
        for workspace_id, registration_ids in _group_by_workspace(rows).items():
            member = await get_or_create_workspace_member(session, workspace_id=workspace_id, player_id=target_user_id)
            target_member_id = member.id

            colliding = set(
                (
                    await session.execute(
                        select(registration.id)
                        .select_from(registration)
                        .join(
                            existing,
                            sa.and_(
                                existing.tournament_id == registration.tournament_id,
                                existing.workspace_member_id == target_member_id,
                                existing.deleted_at.is_(None),
                                existing.id != registration.id,
                            ),
                        )
                        .where(registration.id.in_(registration_ids))
                    )
                )
                .scalars()
                .all()
            )

            to_repoint = [row_id for row_id in registration_ids if row_id not in colliding]
            if not to_repoint:
                continue

            result = await session.execute(
                update(registration).where(registration.id.in_(to_repoint)).values(workspace_member_id=target_member_id)
            )
            moved += int(result.rowcount or 0)

        return moved

    # ─── Cache invalidation ──────────────────────────────────────────────────
    async def _invalidate_auth_rbac_caches(self, auth_user_ids: list[int]) -> None:
        from src.core.config import settings

        redis = Redis.from_url(str(settings.redis_url), decode_responses=True)
        try:
            await redis.delete(*(f"{RBAC_USER_KEY_PREFIX}{user_id}" for user_id in auth_user_ids))
        finally:
            await redis.aclose()

    async def _invalidate_merge_caches(
        self,
        *,
        source_user_id: int,
        target_user_id: int,
        preview: schemas.UserMergePreviewResponse,
    ) -> None:
        patterns = {
            "backend:get_statistics_by_heroes_all_values*",
            # Global/cohort baselines can change even when the merged user is not
            # the subject, so compare responses need broad short-TTL invalidation.
            "backend:user_compare:v2:*",
            "backend:user_hero_compare:v2:*",
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
            # Precise per-user coverage for every registered user read-cache prefix
            # (incl. user_tournament_stats / user_matches_summary, which the broad
            # keyword patterns above miss). Single source of truth: services.user_cache.
            patterns.update(user_cache.user_cache_patterns(user_id))
        for identity in preview.source.social_accounts + preview.target.social_accounts:
            patterns.add(f"backend:*{identity.value}*")
            patterns.add(f"backend:*{identity.value.replace('#', '-')}*")
        for pattern in patterns:
            await cache.delete_match(pattern)


merges = UserMergeService()
