"""Diff new evaluation results against stored ones.

Produces inserts and deletes to reconcile the stored state with the new evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.achievements.achievement import AchievementEvaluationResult, AchievementGrain, AchievementRule
from shared.models.tenancy.workspace import WorkspaceMember
from shared.repository.support import AchievementEvaluationResultRepository
from shared.repository.workspace import get_or_create_workspace_member

ResultSet = set[tuple[int, ...]]


@dataclass(frozen=True)
class DiffResult:
    to_insert: list[dict]
    to_delete: list[int]  # IDs of evaluation_result rows to remove


@dataclass(frozen=True)
class EvaluationSlice:
    """Scope a diff to a single tournament or match."""

    tournament_id: int | None = None
    match_id: int | None = None

    def query_filters(self) -> list[sa.ColumnElement[bool]]:
        filters: list[sa.ColumnElement[bool]] = []
        if self.tournament_id is not None:
            filters.append(AchievementEvaluationResult.tournament_id == self.tournament_id)
        if self.match_id is not None:
            filters.append(AchievementEvaluationResult.match_id == self.match_id)
        return filters

    def contains_key(self, key: tuple[int, ...]) -> bool:
        _user_id, tournament_id, match_id = key
        if self.tournament_id is not None and tournament_id != self.tournament_id:
            return False
        if self.match_id is not None and match_id != self.match_id:
            return False
        return True


def persist_slice_for_grain(
    grain: AchievementGrain | str,
    *,
    tournament_id: int | None,
    match_id: int | None,
) -> EvaluationSlice | None:
    """Persist-scope for one rule. The trigger slice is not the result grain.

    A tournament event may recompute a global (``user``) rule; those keys
    normalize to ``tournament_id=0`` and would be dropped by a tournament
    slice. Tournament- and match-grain rows stay sliced so a run for one
    tournament cannot delete another tournament's stored results.
    """
    resolved = AchievementGrain(grain)
    if resolved is AchievementGrain.user:
        return None
    if resolved is AchievementGrain.user_match and match_id is not None:
        return EvaluationSlice(tournament_id=tournament_id, match_id=match_id)
    if tournament_id is not None:
        return EvaluationSlice(tournament_id=tournament_id)
    return None


class AchievementResultDifferService:
    def __init__(
        self, *, results_repo: AchievementEvaluationResultRepository = AchievementEvaluationResultRepository()
    ) -> None:
        self.results_repo = results_repo

    async def diff_and_apply(
        self,
        session: AsyncSession,
        rule: AchievementRule,
        new_results: ResultSet,
        run_id: str,
        evaluation_slice: EvaluationSlice | None = None,
    ) -> DiffResult:
        """Compare new results with stored results and apply changes.

        ``new_results`` tuples carry the player identity (``players.user.id``,
        matching what the condition-tree evaluator already returns via
        ``WorkspaceMember.player_id``), never the raw ``workspace_member_id``.
        Stored rows are anchored on ``workspace_member_id``, so the diff keys off
        the player identity (joining back to ``WorkspaceMember`` to read it) and
        resolves/creates the target ``workspace_member`` row — scoped to the
        rule's own workspace — only when a row actually needs to be inserted.

        Returns a DiffResult with counts for audit.
        """
        # Load existing results for this rule, resolving each row's player
        # identity through its workspace_member so the diff key is unchanged.
        existing_query = (
            sa.select(
                AchievementEvaluationResult.id,
                WorkspaceMember.player_id,
                AchievementEvaluationResult.tournament_id,
                AchievementEvaluationResult.match_id,
            )
            .select_from(AchievementEvaluationResult)
            .join(WorkspaceMember, WorkspaceMember.id == AchievementEvaluationResult.workspace_member_id)
            .where(AchievementEvaluationResult.achievement_rule_id == rule.id)
        )
        if evaluation_slice is not None:
            existing_query = existing_query.where(*evaluation_slice.query_filters())

        existing_rows = await session.execute(existing_query)

        # Build lookup: tuple → row_id
        existing_map: dict[tuple[int, ...], int] = {}
        for row_id, user_id, tournament_id, match_id in existing_rows:
            key = _make_key(user_id, tournament_id, match_id)
            existing_map[key] = row_id

        existing_keys = set(existing_map.keys())

        # Normalize new results to consistent key format
        new_keys: dict[tuple[int, ...], tuple[int, ...]] = {}
        for result_tuple in new_results:
            key = _normalize_tuple(result_tuple)
            if evaluation_slice is not None and not evaluation_slice.contains_key(key):
                continue
            new_keys[key] = result_tuple

        new_key_set = set(new_keys.keys())

        # Compute diff
        to_add = new_key_set - existing_keys
        to_remove = existing_keys - new_key_set

        # Apply deletions
        ids_to_delete = [existing_map[key] for key in to_remove]
        if ids_to_delete:
            await self.results_repo.bulk_delete_by_ids(session, ids_to_delete)

        # Apply insertions.
        #
        # The read-diff-write above is not atomic: two runs for the same workspace
        # (e.g. two EncounterCompletedEvents for one tournament) read the same
        # ``existing_map`` and then insert the same rows, tripping the
        # ``uq_eval_result_dedup_coalesced`` unique index and failing the whole run.
        # A single INSERT ... ON CONFLICT DO NOTHING makes the reconcile idempotent
        # and replaces N ORM inserts with one statement. The conflict target must
        # repeat the index's COALESCE expressions verbatim (see migration perfidx05)
        # — the plain UniqueConstraint is NULL-blind and never matches for
        # tournament/global-grain rows.
        now = datetime.now(UTC)
        inserts = []
        values: list[dict] = []
        member_id_by_player: dict[int, int] = {}
        for key in to_add:
            user_id, tournament_id, match_id = _unpack_key(key)
            if user_id not in member_id_by_player:
                member = await get_or_create_workspace_member(
                    session, workspace_id=rule.workspace_id, player_id=user_id
                )
                member_id_by_player[user_id] = member.id
            values.append(
                {
                    "achievement_rule_id": rule.id,
                    "workspace_member_id": member_id_by_player[user_id],
                    "tournament_id": tournament_id,
                    "match_id": match_id,
                    "qualified_at": now,
                    "rule_version": rule.rule_version,
                    "run_id": run_id,
                    "evidence_json": {"rule_slug": rule.slug, "rule_version": rule.rule_version},
                }
            )
            inserts.append({"user_id": user_id, "tournament_id": tournament_id, "match_id": match_id})

        if values:
            # get_or_create_workspace_member may have created member rows in this
            # session; flush them so the FK below resolves.
            await session.flush()
            await self.results_repo.bulk_upsert_ignore_conflicts(session, values)

        return DiffResult(to_insert=inserts, to_delete=ids_to_delete)


achievement_result_differ_service = AchievementResultDifferService()
diff_and_apply = achievement_result_differ_service.diff_and_apply


def _make_key(user_id: int, tournament_id: int | None, match_id: int | None) -> tuple[int, ...]:
    """Create a consistent hashable key from nullable fields."""
    return (user_id, tournament_id or 0, match_id or 0)


def _normalize_tuple(t: tuple[int, ...]) -> tuple[int, ...]:
    """Normalize variable-length result tuple to (user_id, tournament_id, match_id)."""
    if len(t) == 1:
        return (t[0], 0, 0)
    if len(t) == 2:
        return (t[0], t[1], 0)
    return (t[0], t[1], t[2])


def _unpack_key(key: tuple[int, ...]) -> tuple[int, int | None, int | None]:
    """Unpack key back to nullable values."""
    user_id = key[0]
    tournament_id = key[1] if key[1] != 0 else None
    match_id = key[2] if key[2] != 0 else None
    return user_id, tournament_id, match_id
