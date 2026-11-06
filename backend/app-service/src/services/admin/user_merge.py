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
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.core import http_status as status
from shared.core.errors import ApiExc, ApiHTTPException
from shared.core.errors import BaseAPIException as HTTPException
from shared.core.social import normalize_social_handle
from shared.messaging.config import WORKSPACE_MEMBER_CHANGED_QUEUE
from shared.messaging.outbox import enqueue_outbox_event
from shared.models.mix import CustomGameRoundMember
from shared.repository import SocialAccountRepository, UserMergeAuditRepository, get_or_create_workspace_member
from shared.repository.draft import ACTIVE_DRAFT_STATUSES
from shared.repository.stats import StatsMatchRepository
from shared.schemas.events import WorkspaceMemberChangedEvent
from shared.schemas.user_merge_auth import AuthMergeResult
from shared.services import user_cache
from shared.services.participant_result import write_participant_results
from shared.services.stats_evidence import capture_stats_evidence, owner_scopes, stage_stats_evidence
from src import schemas
from src.services.admin.auth_merge import apply_auth_merge, preview_auth_merge

__all__ = ("UserMergeService", "merges")

PLAYER_WORKSPACE_MEMBER_REFERENCE_KEY = "tournament.player.workspace_member_id"
EVALUATION_RESULT_MEMBER_REFERENCE_KEY = "achievements.evaluation_result.workspace_member_id"
OVERRIDE_MEMBER_REFERENCE_KEY = "achievements.override.workspace_member_id"
REGISTRATION_MEMBER_REFERENCE_KEY = "registration.registration.workspace_member_id"

# Generic player-id columns, one set-based UPDATE each. References keyed by
# ``workspace_member_id`` (roster, evaluation_result, override, registration)
# have dedicated workspace_member-aware counters/mergers instead.
REFERENCE_CONFIG: tuple[tuple[str, type, str], ...] = (
    ("tournament.team.captain_id", models.Team, "captain_id"),
    ("stats.ingest_job.uploader_user_id", models.IngestJob, "uploader_user_id"),
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
    counts.update(stats_matches=0, stats_players=0, stats_facts=0, stats_events=0)
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
        preview.conflicts.stats_member_history_conflicts = await self._stats_conflicts(
            session,
            request.source_user_id,
            request.target_user_id,
        )
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
            await session.execute(
                select(models.WorkspaceMember.id)
                .where(
                    models.WorkspaceMember.player_id.in_((request.source_user_id, request.target_user_id)),
                )
                .order_by(models.WorkspaceMember.id)
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
            if preview.conflicts.stats_member_history_conflicts:
                raise HTTPException(status_code=409, detail="stats_member_history_conflict")
            if running := await self._running_draft_seat_conflicts(
                session, request.source_user_id, request.target_user_id
            ):
                raise ApiHTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=[
                        ApiExc(
                            code="merge_draft_seat_conflict",
                            msg=f"Both players hold a seat in running draft session(s) {running}: the merge would "
                            "make one person two seats there. Cancel the draft or remove one seat, then merge.",
                        )
                    ],
                )
            if preview.preview_fingerprint != request.preview_fingerprint:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Merge preview is stale. Refresh preview and try again.",
                )
            context = await self._load_merge_context(session, request.source_user_id, request.target_user_id)
            identity_map = await self._stats_identity_map(session, context.source.id, context.target.id)
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

            stats_captures = await self._capture_stats_merge(
                session,
                context.source.id,
                context.target.id,
                identity_map,
            )
            if await self._stats_conflicts(session, context.source.id, context.target.id):
                raise HTTPException(status_code=409, detail="stats_member_history_conflict")
            identity_result_raw = await self.apply_identity_selection(
                session, context.source, context.target, request.identity_selection
            )
            affected_counts = empty_affected_counts()
            affected_counts.update(
                {
                    key: preview.affected_counts[key]
                    for key in (
                        "stats_matches",
                        "stats_players",
                        "stats_facts",
                        "stats_events",
                    )
                }
            )
            # Move unshared member ids before generic repoint helpers can fabricate
            # target memberships. Existing target members remain a disjoint merge.
            await self._move_source_members(session, source_user_id=context.source.id, target_user_id=context.target.id)
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

            # Remove only now-unreferenced duplicate memberships before sealing
            # their transition; source-user cascades cannot erase unaudited history.
            await session.execute(
                sa.delete(models.WorkspaceMember).where(
                    models.WorkspaceMember.player_id == context.source.id,
                )
            )
            await session.flush()
            context.target.name = desired_name
            context.target.avatar_url = desired_avatar_url
            await session.flush()
            stats_audit_ids = []
            for scopes, before, mapping in stats_captures:
                after = await capture_stats_evidence(session, scopes=scopes, identity_map=mapping)
                stats_audit = await stage_stats_evidence(
                    session,
                    operation="stats.member_merge",
                    before=before,
                    after=after,
                    workspace_id=None,
                    entity_type="user",
                    entity_id=request.target_user_id,
                    source="admin",
                    identity_map=mapping,
                )
                stats_audit_ids.append(stats_audit.id)
            await self._delete_source_user_row(session, context.source.id)
            await session.flush()

            snapshot = preview.model_dump(mode="json")
            snapshot["stats_evidence"] = {
                "source_user_id": request.source_user_id,
                "target_user_id": request.target_user_id,
                "identity_map": identity_map,
                "audit_ids": stats_audit_ids,
            }
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
                if auth_result.affected_auth_user_ids:
                    # identity drops these users' cached RBAC once the relay
                    # delivers it, i.e. only after this commit.
                    await enqueue_outbox_event(
                        session,
                        WorkspaceMemberChangedEvent(
                            auth_user_ids=auth_result.affected_auth_user_ids,
                            change="merged",
                            source_service="app-service",
                        ),
                        exchange="",
                        routing_key=WORKSPACE_MEMBER_CHANGED_QUEUE.name,
                    )
                # Fail closed before committing when identity cannot retire the old sessions.
                await auth_finalizer(auth_result)
            await session.commit()
        except Exception:
            await session.rollback()
            raise

        # Both users' read caches, and every compare cache (global/cohort baselines move even when the merged user is
        # not the subject).
        await user_cache.invalidate_user_caches(request.source_user_id, request.target_user_id)
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
            session, models.Registration, source_user_id
        )
        for reference_key, model, column_name in REFERENCE_CONFIG:
            column = getattr(model, column_name)
            result = await session.execute(select(func.count()).select_from(model).where(column == source_user_id))
            counts[reference_key] = int(result.scalar_one())
        counts["players.user.auth_user_id"] = await self._count_auth_links(session, source_user_id)
        members = select(models.WorkspaceMember.id).where(models.WorkspaceMember.player_id == source_user_id)
        player, fact, event = models.StatsMatchPlayer, models.StatsFact, models.StatsEvent
        counts["stats_matches"] = int(
            await session.scalar(
                select(func.count(sa.distinct(player.match_id))).where(
                    player.workspace_member_id.in_(members),
                )
            )
            or 0
        )
        for key, model, predicate in (
            ("stats_players", player, player.workspace_member_id.in_(members)),
            ("stats_facts", fact, fact.workspace_member_id.in_(members)),
            ("stats_events", event, sa.or_(event.actor_member_id.in_(members), event.target_member_id.in_(members))),
        ):
            counts[key] = int(await session.scalar(select(func.count()).select_from(model).where(predicate)) or 0)
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
        values = {column_name: target_user_id}
        if model is models.IngestJob:
            # Uploader identity is a hint change, not a lifecycle transition.
            values["updated_at"] = model.updated_at
        result = await session.execute(sa.update(model).where(column == source_user_id).values(values))
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

        One UPDATE per distinct workspace, not per row. The moved rows' tournaments get their results rewritten: the
        source member's would cascade away with its membership.
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
                sa.update(models.Player).where(models.Player.id.in_(player_ids)).values(workspace_member_id=member.id)
            )
            moved += int(result.rowcount or 0)

        for tournament_id in sorted({int(row[1]) for row in rows}):
            await write_participant_results(session, tournament_id)

        return moved

    async def _stats_identity_map(self, session: AsyncSession, source_id: int, target_id: int) -> list[dict]:
        member = models.WorkspaceMember
        rows = (
            await session.execute(
                select(member.id, member.workspace_id, member.player_id)
                .where(
                    member.player_id.in_((source_id, target_id)),
                )
                .order_by(member.workspace_id, member.id)
            )
        ).all()
        targets = {workspace: member_id for member_id, workspace, user_id in rows if user_id == target_id}
        return [
            {
                "workspace_id": workspace,
                "source_member_id": member_id,
                "target_member_id": targets.get(workspace, member_id),
                "mode": "retain" if workspace in targets else "move",
                "source_user_id": source_id,
                "target_user_id": target_id,
            }
            for member_id, workspace, user_id in rows
            if user_id == source_id
        ]

    async def _stats_conflicts(self, session: AsyncSession, source_id: int, target_id: int) -> list[dict]:
        source = sa.orm.aliased(models.WorkspaceMember)
        target = sa.orm.aliased(models.WorkspaceMember)
        observed = sa.orm.aliased(models.StatsMatchPlayer)
        other = sa.orm.aliased(models.StatsMatchPlayer)
        rows = await session.execute(
            select(
                source.workspace_id,
                source.id.label("source_member_id"),
                target.id.label("target_member_id"),
                observed.match_id,
            )
            .select_from(source)
            .join(target, target.workspace_id == source.workspace_id)
            .join(observed, observed.workspace_member_id == source.id)
            .join(other, sa.and_(other.match_id == observed.match_id, other.workspace_member_id == target.id))
            .where(source.player_id == source_id, target.player_id == target_id)
            .order_by(source.workspace_id, observed.match_id)
        )
        return [dict(row) for row in rows.mappings()]

    async def _capture_stats_merge(
        self,
        session: AsyncSession,
        source_id: int,
        target_id: int,
        identity_map: list[dict],
    ) -> list[tuple]:
        captures = []

        async def capture(owners, mapping):
            scopes = [scope for kind, key in owners for scope in owner_scopes(kind, (key,))]
            before = await capture_stats_evidence(session, scopes=scopes, identity_map=mapping)
            captures.append((scopes, before, mapping))

        # Keep each retain pair together: both owners count against the limit,
        # while a move has one owner. Every original member appears exactly once.
        owners, mapping = [], []
        for entry in identity_map:
            member_ids = sorted({entry["source_member_id"], entry["target_member_id"]})
            if len(owners) + len(member_ids) > 100:
                await capture(owners, mapping)
                owners, mapping = [], []
            owners.extend(("member", member_id) for member_id in member_ids)
            mapping.append(entry)
        if owners:
            await capture(owners, mapping)

        # A global player has at most one source member per workspace. A batch
        # of 100 matches therefore needs at most 100 applicable member mappings.
        by_workspace = {entry["workspace_id"]: entry for entry in identity_map}
        player, match = models.StatsMatchPlayer, models.StatsMatch
        source_members = select(models.WorkspaceMember.id).where(models.WorkspaceMember.player_id == source_id)
        matches = select(player.match_id).where(player.workspace_member_id.in_(source_members))
        stream = await session.stream(
            select(match.id, match.workspace_id)
            .where(
                match.id.in_(matches),
            )
            .order_by(match.id)
            .execution_options(yield_per=100)
        )
        async for batch in stream.partitions(100):
            mapping = [by_workspace[workspace_id] for workspace_id in sorted({row.workspace_id for row in batch})]
            await capture([("match", row.id) for row in batch], mapping)
        await stream.close()

        # Job hints rewrite only the global uploader pair, never memberships.
        stream = await session.stream_scalars(
            select(models.IngestJob.id)
            .where(
                models.IngestJob.uploader_user_id == source_id,
            )
            .order_by(models.IngestJob.id)
            .execution_options(yield_per=100)
        )
        async for batch in stream.partitions(100):
            await capture(
                [("job", job_id) for job_id in batch],
                [
                    {"source_user_id": source_id, "target_user_id": target_id},
                ],
            )
        await stream.close()
        return captures

    async def _running_draft_seat_conflicts(self, session: AsyncSession, source_id: int, target_id: int) -> list[int]:
        """Draft sessions still running (setup to paused) that seat both players.

        ``_move_source_members`` moves the source's seats onto the survivor's member, so there they would become one
        person with two usable seats. A finished draft's two seats are history and move as they are.
        """
        source_seat = sa.orm.aliased(models.DraftPlayer)
        target_seat = sa.orm.aliased(models.DraftPlayer)
        source_member = sa.orm.aliased(models.WorkspaceMember)
        target_member = sa.orm.aliased(models.WorkspaceMember)
        return list(
            (
                await session.scalars(
                    select(models.DraftSession.id)
                    .join(source_seat, source_seat.session_id == models.DraftSession.id)
                    .join(source_member, source_member.id == source_seat.workspace_member_id)
                    .join(target_seat, target_seat.session_id == models.DraftSession.id)
                    .join(target_member, target_member.id == target_seat.workspace_member_id)
                    .where(
                        source_member.player_id == source_id,
                        target_member.player_id == target_id,
                        models.DraftSession.status.in_(ACTIVE_DRAFT_STATUSES),
                    )
                    .distinct()
                    .order_by(models.DraftSession.id)
                )
            ).all()
        )

    async def _move_source_members(self, session: AsyncSession, *, source_user_id: int, target_user_id: int) -> None:
        """Hand the source player's ``workspace_member`` rows to the survivor.

        Roster snapshots (``encounter.team_member``) hang on a member row with no
        cascade, so the source row cannot simply vanish with the player. Per
        workspace: when the survivor has no member row there, the source row is
        re-pointed at the survivor (``player_id``) and keeps its history. When
        the survivor already has one, the source's roster seats move onto it;
        a seat that would duplicate a seat the survivor already holds (same
        participation, or both active in the same encounter) is dropped, since
        it is the same person twice. The now seat-free source row is the one
        duplicate-identity row the user delete cascades away. The same holds for
        ``mix.round_member`` rows (one per round and member) and ``draft.player``
        seats (a mix seat has no registration to fall back to).
        """
        source_rows = (
            await session.execute(
                select(models.WorkspaceMember.id, models.WorkspaceMember.workspace_id).where(
                    models.WorkspaceMember.player_id == source_user_id
                )
            )
        ).all()
        if not source_rows:
            return
        target_members = dict(
            (
                await session.execute(
                    select(models.WorkspaceMember.workspace_id, models.WorkspaceMember.id).where(
                        models.WorkspaceMember.player_id == target_user_id,
                        models.WorkspaceMember.workspace_id.in_([workspace_id for _id, workspace_id in source_rows]),
                    )
                )
            ).all()
        )
        seat = models.EncounterTeamMember
        survivor_seat = sa.orm.aliased(models.EncounterTeamMember)
        for source_member_id, workspace_id in source_rows:
            target_member_id = target_members.get(workspace_id)
            if target_member_id is None:
                await session.execute(
                    sa.update(models.WorkspaceMember)
                    .where(models.WorkspaceMember.id == source_member_id)
                    .values(player_id=target_user_id)
                    .execution_options(synchronize_session=False)
                )
                continue
            await StatsMatchRepository().merge_member_history(
                session,
                source_member_id=source_member_id,
                target_member_id=target_member_id,
            )
            duplicate = (
                sa.exists()
                .where(
                    survivor_seat.workspace_member_id == target_member_id,
                    sa.or_(
                        survivor_seat.encounter_team_id == seat.encounter_team_id,
                        sa.and_(
                            survivor_seat.active.is_(True),
                            seat.active.is_(True),
                            survivor_seat.encounter_id == seat.encounter_id,
                        ),
                    ),
                )
                .correlate(seat)
            )
            await session.execute(
                sa.delete(seat)
                .where(seat.workspace_member_id == source_member_id, duplicate)
                .execution_options(synchronize_session=False)
            )
            await session.execute(
                sa.update(seat)
                .where(seat.workspace_member_id == source_member_id)
                .values(workspace_member_id=target_member_id)
                .execution_options(synchronize_session=False)
            )
            # Mix-round rows hang on the member the same way: one per (round, member). On a collision
            # the seated (non-busy) row wins, so the seat the survivor keeps never pairs with a busy row; on
            # a tie (both busy or both seated) the survivor's row wins.
            round_member = CustomGameRoundMember
            other_round = sa.orm.aliased(CustomGameRoundMember)
            await session.execute(
                sa.delete(round_member)
                .where(
                    round_member.workspace_member_id == target_member_id,
                    round_member.busy.is_(True),
                    sa.exists()
                    .where(
                        other_round.workspace_member_id == source_member_id,
                        other_round.encounter_id == round_member.encounter_id,
                        other_round.busy.is_(False),
                    )
                    .correlate(round_member),
                )
                .execution_options(synchronize_session=False)
            )
            await session.execute(
                sa.delete(round_member)
                .where(
                    round_member.workspace_member_id == source_member_id,
                    sa.exists()
                    .where(
                        other_round.workspace_member_id == target_member_id,
                        other_round.encounter_id == round_member.encounter_id,
                    )
                    .correlate(round_member),
                )
                .execution_options(synchronize_session=False)
            )
            await session.execute(
                sa.update(round_member)
                .where(round_member.workspace_member_id == source_member_id)
                .values(workspace_member_id=target_member_id)
                .execution_options(synchronize_session=False)
            )
            # Draft seats hang on the member the same way; a seat is moved, never dropped, because picks name it. Two
            # seats of one person in a running draft were refused up front (``_running_draft_seat_conflicts``).
            await session.execute(
                sa.update(models.DraftPlayer)
                .where(models.DraftPlayer.workspace_member_id == source_member_id)
                .values(workspace_member_id=target_member_id)
                .execution_options(synchronize_session=False)
            )

    async def _delete_source_user_row(self, session: AsyncSession, source_user_id: int) -> None:
        # A set-based DELETE rather than an ORM instance delete: the row's dependents
        # are removed by the database's own ON DELETE rules, whereas an ORM cascade
        # would load and delete every loaded collection one row at a time.
        await session.execute(sa.delete(models.User).where(models.User.id == source_user_id))

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
                result = await session.execute(sa.delete(result_model).where(result_model.id.in_(to_drop)))
                moved += int(result.rowcount or 0)
            if to_repoint:
                result = await session.execute(
                    sa.update(result_model)
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
                sa.update(models.AchievementOverride)
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
        """Move every ``registration.registration`` row anchored on ``source_user_id``'s
        ``workspace_member`` onto the target's ``workspace_member`` and return the
        number of rows moved.

        Mirrors ``_repoint_player_workspace_members`` (each row's workspace comes
        from its own tournament, via ``Tournament.workspace_id``, so the target's
        member is resolved/created per workspace). Registrations that are not
        member-anchored (``workspace_member_id IS NULL`` -- sheet-import rows) are
        excluded by the join and are correctly left untouched/NULL.

        ``registration.registration.workspace_member_id`` has a live unique constraint
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
        registration = models.Registration
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
                sa.update(registration)
                .where(registration.id.in_(to_repoint))
                .values(workspace_member_id=target_member_id)
            )
            moved += int(result.rowcount or 0)

        return moved


merges = UserMergeService()
