"""Pure mapping tests for the hidden-tournaments data model (no DB)."""

from shared.models.tournament import TournamentPreviewAccess
from shared.models.tournament.tournament import Tournament


def test_preview_access_table_and_schema():
    t = TournamentPreviewAccess.__table__
    assert t.schema == "tournament"
    assert t.name == "tournament_preview_access"
    cols = {c.name for c in t.columns}
    assert {"tournament_id", "auth_user_id", "id", "created_at", "updated_at"} <= cols


def test_preview_access_unique_constraint():
    t = TournamentPreviewAccess.__table__
    uqs = [c for c in t.constraints if c.__class__.__name__ == "UniqueConstraint"]
    assert any({col.name for col in uq.columns} == {"tournament_id", "auth_user_id"} for uq in uqs)


def test_preview_access_foreign_keys():
    t = TournamentPreviewAccess.__table__
    targets = {fk.target_fullname for fk in t.foreign_keys}
    assert "tournament.tournament.id" in targets
    assert "auth.user.id" in targets


def test_tournament_is_hidden_column():
    col = Tournament.__table__.c.is_hidden
    assert col.nullable is False
    assert col.index is True
