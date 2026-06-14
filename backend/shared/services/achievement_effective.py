from __future__ import annotations

from typing import Iterable

import sqlalchemy as sa

from shared.models.achievement import (
    AchievementEvaluationResult,
    AchievementOverride,
    AchievementOverrideAction,
    AchievementRule,
)


def override_applies_to_scope(
    override_tournament_id: int | None,
    override_match_id: int | None,
    candidate_tournament_id: int | None,
    candidate_match_id: int | None,
) -> bool:
    """Return True when an override applies to a candidate result scope."""
    if override_match_id is not None:
        return override_match_id == candidate_match_id

    if override_tournament_id is not None:
        return override_tournament_id == candidate_tournament_id

    return True


def override_applies_to_scope_sql(
    override_tournament_id: sa.ColumnElement,
    override_match_id: sa.ColumnElement,
    candidate_tournament_id: sa.ColumnElement,
    candidate_match_id: sa.ColumnElement,
) -> sa.ColumnElement[bool]:
    """SQL expression equivalent of :func:`override_applies_to_scope`."""
    return sa.or_(
        sa.and_(
            override_match_id.is_not(None),
            override_match_id == candidate_match_id,
        ),
        sa.and_(
            override_match_id.is_(None),
            override_tournament_id.is_not(None),
            override_tournament_id == candidate_tournament_id,
        ),
        sa.and_(
            override_match_id.is_(None),
            override_tournament_id.is_(None),
        ),
    )


def build_effective_achievement_rows_subquery(
    *,
    workspace_id: int | None = None,
    achievement_rule_ids: Iterable[int] | None = None,
    user_ids: Iterable[int] | None = None,
    name: str = "effective_achievement_rows",
) -> sa.Subquery:
    """Build a reusable subquery for effective achievement rows.

    Effective rows are:
      evaluation_result
      UNION grant overrides
      MINUS revoke overrides scoped by global/tournament/match precedence
    """
    achievement_rule_ids = list(achievement_rule_ids or [])
    user_ids = list(user_ids or [])

    evaluation_rows = sa.select(
        AchievementEvaluationResult.achievement_rule_id.label("achievement_rule_id"),
        AchievementEvaluationResult.user_id.label("user_id"),
        AchievementEvaluationResult.tournament_id.label("tournament_id"),
        AchievementEvaluationResult.match_id.label("match_id"),
        AchievementEvaluationResult.qualified_at.label("qualified_at"),
    ).select_from(AchievementEvaluationResult)

    grant_rows = sa.select(
        AchievementOverride.achievement_rule_id.label("achievement_rule_id"),
        AchievementOverride.user_id.label("user_id"),
        AchievementOverride.tournament_id.label("tournament_id"),
        AchievementOverride.match_id.label("match_id"),
        AchievementOverride.created_at.label("qualified_at"),
    ).select_from(AchievementOverride).where(
        AchievementOverride.action == AchievementOverrideAction.grant
    )

    if workspace_id is not None:
        evaluation_rows = evaluation_rows.join(
            AchievementRule,
            AchievementRule.id == AchievementEvaluationResult.achievement_rule_id,
        ).where(AchievementRule.workspace_id == workspace_id)
        grant_rows = grant_rows.join(
            AchievementRule,
            AchievementRule.id == AchievementOverride.achievement_rule_id,
        ).where(AchievementRule.workspace_id == workspace_id)

    if achievement_rule_ids:
        evaluation_rows = evaluation_rows.where(
            AchievementEvaluationResult.achievement_rule_id.in_(achievement_rule_ids)
        )
        grant_rows = grant_rows.where(
            AchievementOverride.achievement_rule_id.in_(achievement_rule_ids)
        )

    if user_ids:
        evaluation_rows = evaluation_rows.where(
            AchievementEvaluationResult.user_id.in_(user_ids)
        )
        grant_rows = grant_rows.where(
            AchievementOverride.user_id.in_(user_ids)
        )

    candidates = evaluation_rows.union_all(grant_rows).subquery(f"{name}_candidates")

    revoke_override = sa.orm.aliased(AchievementOverride, name="revoke_override")
    revoke_match = sa.exists(
        sa.select(1)
        .select_from(revoke_override)
        .where(
            revoke_override.action == AchievementOverrideAction.revoke,
            revoke_override.achievement_rule_id == candidates.c.achievement_rule_id,
            revoke_override.user_id == candidates.c.user_id,
            override_applies_to_scope_sql(
                revoke_override.tournament_id,
                revoke_override.match_id,
                candidates.c.tournament_id,
                candidates.c.match_id,
            ),
        )
    )

    effective_rows = (
        sa.select(
            candidates.c.achievement_rule_id,
            candidates.c.user_id,
            candidates.c.tournament_id,
            candidates.c.match_id,
            sa.func.max(candidates.c.qualified_at).label("qualified_at"),
        )
        .where(~revoke_match)
        .group_by(
            candidates.c.achievement_rule_id,
            candidates.c.user_id,
            candidates.c.tournament_id,
            candidates.c.match_id,
        )
    )

    return effective_rows.subquery(name)
