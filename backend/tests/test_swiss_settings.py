from types import SimpleNamespace

from shared.services.bracket.swiss_settings import (
    clear_swiss_byes,
    clear_swiss_scope_stopped,
    mark_swiss_scope_stopped,
    record_swiss_bye,
    swiss_bye_counts,
    swiss_bye_team_ids,
    swiss_scope_stopped,
)


def test_swiss_runtime_settings_are_scoped_by_stage_item() -> None:
    stage = SimpleNamespace(settings_json=None)

    record_swiss_bye(stage, 10, 101)
    record_swiss_bye(stage, 10, 102)
    record_swiss_bye(stage, 20, 201)
    mark_swiss_scope_stopped(stage, 10)

    assert swiss_bye_team_ids(stage, 10) == [101, 102]
    assert swiss_bye_counts(stage, 20) == {201: 1}
    assert swiss_scope_stopped(stage, 10)
    assert not swiss_scope_stopped(stage, 20)

    clear_swiss_byes(stage, 10)
    clear_swiss_scope_stopped(stage, 10)

    assert swiss_bye_team_ids(stage, 10) == []
    assert swiss_bye_team_ids(stage, 20) == [201]
    assert not swiss_scope_stopped(stage, 10)
