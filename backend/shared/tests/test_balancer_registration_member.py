from shared.models.registration.registration import BalancerRegistration


def test_registration_anchored_on_workspace_member():
    cols = set(BalancerRegistration.__table__.columns.keys())
    assert "workspace_member_id" in cols
    assert "auth_user_id" not in cols
    assert "workspace_id" not in cols
    assert "user_id" in cols


def test_registration_workspace_member_column_nullable():
    col = BalancerRegistration.__table__.columns["workspace_member_id"]
    assert col.nullable is True


def test_registration_workspace_member_fk_targets_workspace_member_set_null():
    col = BalancerRegistration.__table__.columns["workspace_member_id"]
    fk = next(iter(col.foreign_keys))
    assert fk.column.table.name == "workspace_member"
    # workspace_member lives in the public schema (no dedicated "workspace" schema).
    assert fk.column.table.schema is None
    assert fk.ondelete == "SET NULL"


def test_registration_workspace_member_relationship_exists():
    rel = BalancerRegistration.__mapper__.relationships["workspace_member"]
    assert rel.uselist is False


def test_registration_no_auth_user_relationship():
    assert "auth_user" not in BalancerRegistration.__mapper__.relationships
    assert "workspace" not in BalancerRegistration.__mapper__.relationships


def test_registration_unique_index_on_tournament_and_workspace_member():
    indexes = [
        idx for idx in BalancerRegistration.__table__.indexes if idx.name == "uq_balancer_registration_user"
    ]
    assert len(indexes) == 1
    index = indexes[0]
    assert index.unique is True
    assert {col.name for col in index.columns} == {"tournament_id", "workspace_member_id"}
