from shared.models.tenancy.workspace import WorkspaceMember


def test_member_anchored_on_player():
    cols = set(WorkspaceMember.__table__.columns.keys())
    assert "player_id" in cols
    assert "auth_user_id" not in cols
    assert "role" not in cols
    uniques = [c for c in WorkspaceMember.__table__.constraints if c.__class__.__name__ == "UniqueConstraint"]
    sets = [{col.name for col in u.columns} for u in uniques]
    assert {"workspace_id", "player_id"} in sets
    assert {"id", "workspace_id"} in sets


def test_member_player_fk_targets_players_user_cascade():
    col = WorkspaceMember.__table__.columns["player_id"]
    fk = next(iter(col.foreign_keys))
    assert fk.column.table.schema == "players"
    assert fk.column.table.name == "user"
    assert fk.ondelete == "CASCADE"


def test_member_player_relationship_exists():
    rel = WorkspaceMember.__mapper__.relationships["player"]
    assert rel.uselist is False
