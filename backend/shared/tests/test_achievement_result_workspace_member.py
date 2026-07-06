"""P6: achievement RESULT tables (``AchievementEvaluationResult``,
``AchievementOverride``) moved off ``user_id`` onto ``workspace_member_id``.

Pure model-metadata tests (no DB connection) mirroring the precedent set by
``test_player_workspace_member_contract.py`` for the ``tournament.player``
contract step: verify the column swap, the FK target/cascade, and the updated
unique constraint.
"""

import pytest

from shared.core import db
from shared.models.achievements.achievement import (
    AchievementEvaluationResult,
    AchievementOverride,
)


def test_evaluation_result_has_workspace_member_column_and_no_user_id():
    cols = set(AchievementEvaluationResult.__table__.columns.keys())
    assert "workspace_member_id" in cols
    assert "user_id" not in cols


def test_evaluation_result_workspace_member_column_not_nullable():
    col = AchievementEvaluationResult.__table__.columns["workspace_member_id"]
    assert col.nullable is False


def test_evaluation_result_workspace_member_fk_targets_public_workspace_member_cascade():
    col = AchievementEvaluationResult.__table__.columns["workspace_member_id"]
    fk = next(iter(col.foreign_keys))
    assert fk.column.table.name == "workspace_member"
    # workspace_member lives in the public schema (no dedicated "workspace" schema).
    assert fk.column.table.schema is None
    assert fk.ondelete == "CASCADE"


def test_evaluation_result_workspace_member_relationship_exists():
    rel = AchievementEvaluationResult.__mapper__.relationships["workspace_member"]
    assert rel.uselist is False


def test_evaluation_result_user_relationship_no_longer_exists():
    assert "user" not in AchievementEvaluationResult.__mapper__.relationships


def test_evaluation_result_unique_constraint_uses_workspace_member_id():
    constraints = {
        c.name: [col.name for col in c.columns]
        for c in AchievementEvaluationResult.__table__.constraints
        if c.name == "uq_eval_result_rule_user_tournament_match"
    }
    assert constraints["uq_eval_result_rule_user_tournament_match"] == [
        "achievement_rule_id",
        "workspace_member_id",
        "tournament_id",
        "match_id",
    ]


def test_override_has_workspace_member_column_and_no_user_id():
    cols = set(AchievementOverride.__table__.columns.keys())
    assert "workspace_member_id" in cols
    assert "user_id" not in cols


def test_override_workspace_member_column_not_nullable():
    col = AchievementOverride.__table__.columns["workspace_member_id"]
    assert col.nullable is False


def test_override_workspace_member_fk_targets_public_workspace_member_cascade():
    col = AchievementOverride.__table__.columns["workspace_member_id"]
    fk = next(iter(col.foreign_keys))
    assert fk.column.table.name == "workspace_member"
    assert fk.column.table.schema is None
    assert fk.ondelete == "CASCADE"


def test_override_workspace_member_relationship_exists():
    rel = AchievementOverride.__mapper__.relationships["workspace_member"]
    assert rel.uselist is False


def test_override_user_relationship_no_longer_exists():
    assert "user" not in AchievementOverride.__mapper__.relationships


def test_legacy_achievement_models_removed():
    """The old ``Achievement``/``AchievementUser`` models were dropped by
    ``l2g4h6i0j1k2`` and removed from the codebase."""
    with pytest.raises(ImportError):
        from shared.models.achievements.achievement import (  # noqa: F401
            AchievementUser,
        )

    table_names = {(table.schema, table.name) for table in db.Base.metadata.tables.values()}
    assert ("achievements", "user") not in table_names
    assert ("achievements", "achievement") not in table_names
