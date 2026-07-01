from shared.models.team import Player


def test_player_has_workspace_member_column_alongside_user_id():
    cols = set(Player.__table__.columns.keys())
    assert "workspace_member_id" in cols
    # Expand step: user_id must still be present (dropped only at CONTRACT).
    assert "user_id" in cols


def test_player_workspace_member_column_nullable():
    col = Player.__table__.columns["workspace_member_id"]
    assert col.nullable is True


def test_player_user_id_column_still_not_null():
    col = Player.__table__.columns["user_id"]
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


def test_player_user_relationship_still_exists():
    rel = Player.__mapper__.relationships["user"]
    assert rel.uselist is False


def test_player_existing_indexes_untouched():
    index_names = {idx.name for idx in Player.__table__.indexes}
    assert "ix_player_user_tournament" in index_names
    assert "ix_player_team_user" in index_names
    assert "ix_player_user_not_sub" in index_names
    assert "ix_player_tournament_role_sub_role" in index_names
    # SQLAlchemy auto-derives this name from the schema-qualified table (tournament.player).
    assert "ix_tournament_player_workspace_member_id" in index_names
