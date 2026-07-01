from shared.models.team import Player


def test_player_has_workspace_member_column_and_no_user_id():
    cols = set(Player.__table__.columns.keys())
    assert "workspace_member_id" in cols
    # Contract step: user_id is dropped.
    assert "user_id" not in cols


def test_player_workspace_member_column_not_nullable():
    col = Player.__table__.columns["workspace_member_id"]
    assert col.nullable is False


def test_player_workspace_member_fk_targets_workspace_member_cascade():
    col = Player.__table__.columns["workspace_member_id"]
    fk = next(iter(col.foreign_keys))
    assert fk.column.table.name == "workspace_member"
    # workspace_member lives in the public schema (no dedicated "workspace" schema).
    assert fk.column.table.schema is None
    assert fk.ondelete == "CASCADE"


def test_player_workspace_member_relationship_exists():
    rel = Player.__mapper__.relationships["workspace_member"]
    assert rel.uselist is False


def test_player_user_relationship_no_longer_exists():
    assert "user" not in Player.__mapper__.relationships


def test_player_old_user_indexes_dropped():
    index_names = {idx.name for idx in Player.__table__.indexes}
    assert "ix_player_user_tournament" not in index_names
    assert "ix_player_team_user" not in index_names
    assert "ix_player_user_not_sub" not in index_names
    # Expand-step index (superseded by the composite contract indexes below).
    assert "ix_tournament_player_workspace_member_id" not in index_names


def test_player_new_workspace_member_indexes_present():
    index_names = {idx.name for idx in Player.__table__.indexes}
    assert "ix_player_workspace_member_tournament" in index_names
    assert "ix_player_team_workspace_member" in index_names
    assert "ix_player_member_not_sub" in index_names
    assert "ix_player_tournament_role_sub_role" in index_names


def test_player_member_not_sub_index_is_partial_on_is_substitution_false():
    index_names = {idx.name: idx for idx in Player.__table__.indexes}
    idx = index_names["ix_player_member_not_sub"]
    assert [c.name for c in idx.columns] == ["workspace_member_id", "tournament_id"]
    assert idx.dialect_options["postgresql"]["where"] is not None
