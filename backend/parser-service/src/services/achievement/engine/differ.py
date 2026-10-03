"""Diff new evaluation results against stored ones.

Produces inserts and deletes to reconcile the stored state with the new evaluation.
"""

from __future__ import annotations

from collections.abc import Mapping
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
        _user_id, tournament_id, _encounter_id, match_id = key
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


async def load_existing_results(
    session: AsyncSession,
    slices: Mapping[int, EvaluationSlice | None],
) -> dict[int, dict[tuple[int, ...], int]]:
    """Stored rows for every rule of a run: one query per distinct persist slice.

    Returns ``rule_id -> {key: evaluation_result.id}``; a rule with no stored
    rows is simply absent. The per-rule read this replaces ran inside each
    rule's savepoint and was most of the evaluation N+1 (Sentry
    OWT-TOURNAMENTS-2BW): stored rows are partitioned by
    ``achievement_rule_id``, so one ``IN`` per slice returns exactly the union
    of what those reads returned. Reading earlier in the transaction only
    widens the window in which a *concurrent* run inserts a row this one will
    also try to insert — already true per rule, and the reconcile insert is
    ``ON CONFLICT DO NOTHING``.
    """
    by_slice: dict[EvaluationSlice | None, list[int]] = {}
    for rule_id, evaluation_slice in slices.items():
        by_slice.setdefault(evaluation_slice, []).append(rule_id)

    existing: dict[int, dict[tuple[int, ...], int]] = {}
    for evaluation_slice, rule_ids in by_slice.items():
        query = (
            sa.select(
                AchievementEvaluationResult.achievement_rule_id,
                AchievementEvaluationResult.id,
                WorkspaceMember.player_id,
                AchievementEvaluationResult.tournament_id,
                AchievementEvaluationResult.encounter_id,
                AchievementEvaluationResult.match_id,
            )
            .select_from(AchievementEvaluationResult)
            .join(WorkspaceMember, WorkspaceMember.id == AchievementEvaluationResult.workspace_member_id)
            .where(AchievementEvaluationResult.achievement_rule_id.in_(rule_ids))
        )
        if evaluation_slice is not None:
            query = query.where(*evaluation_slice.query_filters())
        for rule_id, row_id, user_id, tournament_id, encounter_id, match_id in await session.execute(query):
            key = _make_key(user_id, tournament_id, encounter_id, match_id)
            existing.setdefault(rule_id, {})[key] = row_id
    return existing


async def _resolve_member_ids(
    session: AsyncSession,
    *,
    workspace_id: int,
    player_ids: set[int],
) -> dict[int, int]:
    """``player_id -> workspace_member.id``, one SELECT for the whole batch.

    The per-player ``INSERT ... ON CONFLICT DO NOTHING RETURNING id`` this
    replaces ran once per newly qualifying player (Sentry
    OWT-TOURNAMENTS-2BW). Every player an evaluation sees is normally already
    anchored in the workspace, so one query answers the batch; only a genuinely
    new anchor falls back to ``get_or_create_workspace_member``, which also
    seeds the member's baseline RBAC role.
    """
    if not player_ids:
        return {}
    rows = await session.execute(
        sa.select(WorkspaceMember.player_id, WorkspaceMember.id).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.player_id.in_(sorted(player_ids)),
        )
    )
    # list() first: Result has .keys(), so dict(result) would treat it as a mapping.
    member_ids = dict(list(rows))
    for player_id in sorted(player_ids - member_ids.keys()):
        member = await get_or_create_workspace_member(session, workspace_id=workspace_id, player_id=player_id)
        member_ids[player_id] = member.id
    return member_ids


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
        evidence: dict[tuple[int, ...], dict] | None = None,
        existing: dict[tuple[int, ...], int] | None = None,
    ) -> DiffResult:
        """Compare new results with stored results and apply changes.

        ``new_results`` tuples carry the player identity (``players.user.id``,
        matching what the condition-tree evaluator already returns via
        ``WorkspaceMember.player_id``), never the raw ``workspace_member_id``.
        Stored rows are anchored on ``workspace_member_id``, so the diff keys off
        the player identity (joining back to ``WorkspaceMember`` to read it) and
        resolves/creates the target ``workspace_member`` row — scoped to the
        rule's own workspace — only when a row actually needs to be inserted.

        ``existing`` is the rule's stored rows (key → row id) when the caller
        already loaded them for the whole run (``load_existing_results``);
        without it the read happens here, one rule at a time.

        Returns a DiffResult with counts for audit.
        """
        if existing is None:
            existing = (await load_existing_results(session, {rule.id: evaluation_slice})).get(rule.id, {})

        existing_keys = set(existing)

        # Normalize new results to consistent key format
        grain = AchievementGrain(rule.grain)
        new_keys: dict[tuple[int, ...], tuple[int, ...]] = {}
        for result_tuple in new_results:
            key = _normalize_tuple(result_tuple, grain)
            if evaluation_slice is not None and not evaluation_slice.contains_key(key):
                continue
            new_keys[key] = result_tuple

        new_key_set = set(new_keys.keys())

        # Compute diff
        to_add = new_key_set - existing_keys
        to_remove = existing_keys - new_key_set

        # Apply deletions
        ids_to_delete = [existing[key] for key in to_remove]
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
        member_id_by_player = await _resolve_member_ids(
            session,
            workspace_id=rule.workspace_id,
            player_ids={_unpack_key(key)[0] for key in to_add},
        )
        for key in to_add:
            user_id, tournament_id, encounter_id, match_id = _unpack_key(key)
            # "Why this player": whatever the leaf that matched them recorded —
            # the measured value and the threshold it cleared, not just the slug.
            matched = (evidence or {}).get(new_keys[key]) or {}
            values.append(
                {
                    "achievement_rule_id": rule.id,
                    "workspace_member_id": member_id_by_player[user_id],
                    "tournament_id": tournament_id,
                    "encounter_id": encounter_id,
                    "match_id": match_id,
                    "qualified_at": now,
                    "rule_version": rule.rule_version,
                    "run_id": run_id,
                    "evidence_json": {"rule_slug": rule.slug, "rule_version": rule.rule_version, **matched},
                }
            )
            inserts.append(
                {
                    "user_id": user_id,
                    "tournament_id": tournament_id,
                    "encounter_id": encounter_id,
                    "match_id": match_id,
                }
            )

        if values:
            # ``_resolve_member_ids`` may have created member rows in this
            # session; flush them so the FK below resolves.
            await session.flush()
            await self.results_repo.bulk_upsert_ignore_conflicts(session, values)

        return DiffResult(to_insert=inserts, to_delete=ids_to_delete)


achievement_result_differ_service = AchievementResultDifferService()
diff_and_apply = achievement_result_differ_service.diff_and_apply


def _make_key(
    user_id: int,
    tournament_id: int | None,
    encounter_id: int | None,
    match_id: int | None,
) -> tuple[int, ...]:
    """Create a consistent hashable key from nullable fields."""
    return (user_id, tournament_id or 0, encounter_id or 0, match_id or 0)


def _normalize_tuple(t: tuple[int, ...], grain: AchievementGrain) -> tuple[int, ...]:
    """Normalize a result tuple to (user_id, tournament_id, encounter_id, match_id).

    ``user_encounter`` and ``user_match`` both arrive as 3-tuples; only the
    rule's grain says whether the third slot is a series or one of its maps.
    """
    if len(t) == 1:
        return (t[0], 0, 0, 0)
    if len(t) == 2:
        return (t[0], t[1], 0, 0)
    if grain is AchievementGrain.user_encounter:
        return (t[0], t[1], t[2], 0)
    return (t[0], t[1], 0, t[2])


def _unpack_key(key: tuple[int, ...]) -> tuple[int, int | None, int | None, int | None]:
    """Unpack key back to nullable values."""
    user_id = key[0]
    tournament_id = key[1] if key[1] != 0 else None
    encounter_id = key[2] if key[2] != 0 else None
    match_id = key[3] if key[3] != 0 else None
    return user_id, tournament_id, encounter_id, match_id
