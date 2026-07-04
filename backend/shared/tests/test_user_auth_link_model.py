from shared.models.identity.auth_user import AuthUser
from shared.models.identity.user import User


def test_user_has_unique_nullable_auth_user_id():
    col = User.__table__.columns["auth_user_id"]
    assert col.nullable is True
    assert col.unique is True
    fk = next(iter(col.foreign_keys))
    assert fk.column.table.schema == "auth"
    assert fk.column.table.name == "user"


def test_authuser_player_relationship_is_scalar():
    rel = AuthUser.__mapper__.relationships["player"]
    assert rel.uselist is False
