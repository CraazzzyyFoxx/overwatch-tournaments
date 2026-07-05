"""Model-metadata tests for the ``map_veto_config_map`` child table (dbarch05).

Pure metadata tests (no DB connection): verify the JSON ``map_pool_ids`` array
was normalized into a proper FK child table, that ``MapVetoConfig`` no longer
declares the JSON column, and that the ``map_pool`` relationship links them.
"""

from shared.models.tournament.encounter_map import (
    MapVetoConfig,
    MapVetoConfigMap,
)


def test_map_veto_config_no_longer_has_map_pool_ids_column():
    cols = set(MapVetoConfig.__table__.columns.keys())
    assert "map_pool_ids" not in cols
    # veto_sequence_json is template-shaped and intentionally kept.
    assert "veto_sequence_json" in cols


def test_child_table_name_and_schema():
    assert MapVetoConfigMap.__table__.name == "map_veto_config_map"
    assert MapVetoConfigMap.__table__.schema == "tournament"


def test_child_columns_present():
    cols = set(MapVetoConfigMap.__table__.columns.keys())
    assert {"map_veto_config_id", "map_id", "sort_order"} <= cols


def test_config_fk_targets_map_veto_config_cascade():
    col = MapVetoConfigMap.__table__.columns["map_veto_config_id"]
    fk = next(iter(col.foreign_keys))
    assert fk.column.table.name == "map_veto_config"
    assert fk.column.table.schema == "tournament"
    assert fk.ondelete == "CASCADE"


def test_map_fk_targets_overwatch_map_cascade():
    col = MapVetoConfigMap.__table__.columns["map_id"]
    fk = next(iter(col.foreign_keys))
    assert fk.column.table.name == "map"
    assert fk.column.table.schema == "overwatch"
    assert fk.ondelete == "CASCADE"


def test_unique_constraint_on_config_and_map():
    uniques = {
        c.name: [col.name for col in c.columns]
        for c in MapVetoConfigMap.__table__.constraints
        if c.name == "uq_map_veto_config_map_config_map"
    }
    assert uniques["uq_map_veto_config_map_config_map"] == [
        "map_veto_config_id",
        "map_id",
    ]


def test_map_pool_relationship_exists_and_is_list():
    rel = MapVetoConfig.__mapper__.relationships["map_pool"]
    assert rel.uselist is True
