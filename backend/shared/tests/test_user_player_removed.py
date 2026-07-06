import pytest

from shared.core import db


def test_authuserplayer_class_no_longer_importable():
    with pytest.raises(ImportError):
        from shared.models.identity.auth_user import AuthUserPlayer  # noqa: F401


def test_auth_user_player_table_absent_from_metadata():
    table_names = {(table.schema, table.name) for table in db.Base.metadata.tables.values()}
    assert ("auth", "user_player") not in table_names
