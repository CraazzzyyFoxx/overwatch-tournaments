"""P6: ``build_effective_achievement_rows_subquery`` reads from
``AchievementEvaluationResult``/``AchievementOverride`` via ``workspace_member_id``
now, but every consumer (rarity counts, per-user pagination, revoke matching)
still expects the union to expose a player id under ``user_id``.

These are compile-shape tests (no live DB): they assert the built subquery
compiles cleanly against the postgres dialect and that
``workspace_member.player_id`` is what actually lands under the ``user_id``
alias in both UNION branches, and that the revoke-exists correlation also
joins its own ``workspace_member`` rather than comparing raw FK columns.
"""

from sqlalchemy.dialects import postgresql

from shared.services.achievement_effective import build_effective_achievement_rows_subquery


def _compiled(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


def test_compiles_cleanly_against_postgres_dialect():
    subq = build_effective_achievement_rows_subquery()
    # Compiling must not raise (ambiguous FROM / missing join path / etc.).
    sql = _compiled(subq.select())
    assert "effective_achievement_rows" in sql


def test_evaluation_branch_exposes_workspace_member_player_id_as_user_id():
    subq = build_effective_achievement_rows_subquery()
    sql = _compiled(subq.select())
    assert "eval_member.player_id AS user_id" in sql
    assert "eval_member.id = achievements.evaluation_result.workspace_member_id" in sql


def test_grant_branch_exposes_workspace_member_player_id_as_user_id():
    subq = build_effective_achievement_rows_subquery()
    sql = _compiled(subq.select())
    assert "grant_member.player_id AS user_id" in sql
    assert "grant_member.id = achievements.override.workspace_member_id" in sql


def test_revoke_exists_correlates_through_its_own_workspace_member():
    subq = build_effective_achievement_rows_subquery()
    sql = _compiled(subq.select())
    assert "revoke_member.id = revoke_override.workspace_member_id" in sql
    # Revoke matching compares player identity, not the raw FK column.
    assert "revoke_member.player_id = effective_achievement_rows_candidates.user_id" in sql


def test_user_ids_filter_applies_to_player_identity_not_raw_fk():
    subq = build_effective_achievement_rows_subquery(user_ids=[42])
    sql = _compiled(subq.select())
    assert "eval_member.player_id IN" in sql
    assert "grant_member.player_id IN" in sql


def test_workspace_filter_still_scopes_via_achievement_rule():
    subq = build_effective_achievement_rows_subquery(workspace_id=7)
    sql = _compiled(subq.select())
    assert "achievements.rule.workspace_id = " in sql


def test_output_columns_are_unchanged_shape():
    """Consumers pattern-match on ``.c.<name>`` — the exposed column set must
    stay exactly {achievement_rule_id, user_id, tournament_id, match_id,
    qualified_at}, regardless of the underlying join rewrite."""
    subq = build_effective_achievement_rows_subquery()
    assert set(subq.c.keys()) == {
        "achievement_rule_id",
        "user_id",
        "tournament_id",
        "match_id",
        "qualified_at",
    }
