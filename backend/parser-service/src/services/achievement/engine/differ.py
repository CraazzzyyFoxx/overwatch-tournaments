"""Diff new evaluation results against stored ones.

Produces inserts and deletes to reconcile the stored state with the new evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.achievement import AchievementEvaluationResult, AchievementRule

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


async def diff_and_apply(
    session: AsyncSession,
    rule: AchievementRule,
    new_results: ResultSet,
    run_id: str,
    evaluation_slice: EvaluationSlice | None = None,
) -> DiffResult:
    """Compare new results with stored results and apply changes.

    Returns a DiffResult with counts for audit.
    """
    # Load existing results for this rule
    existing_query = sa.select(
        AchievementEvaluationResult.id,
        AchievementEvaluationResult.user_id,
        AchievementEvaluationResult.tournament_id,
        AchievementEvaluationResult.match_id,
    ).where(AchievementEvaluationResult.achievement_rule_id == rule.id)
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
        await session.execute(
            sa.delete(AchievementEvaluationResult).where(
                AchievementEvaluationResult.id.in_(ids_to_delete)
            )
        )

    # Apply insertions
    now = datetime.now(timezone.utc)
    inserts = []
    for key in to_add:
        user_id, tournament_id, match_id = _unpack_key(key)
        row = AchievementEvaluationResult(
            achievement_rule_id=rule.id,
            user_id=user_id,
            tournament_id=tournament_id,
            match_id=match_id,
            qualified_at=now,
            rule_version=rule.rule_version,
            run_id=run_id,
            evidence_json={"rule_slug": rule.slug, "rule_version": rule.rule_version},
        )
        session.add(row)
        inserts.append({"user_id": user_id, "tournament_id": tournament_id, "match_id": match_id})

    return DiffResult(to_insert=inserts, to_delete=ids_to_delete)


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
