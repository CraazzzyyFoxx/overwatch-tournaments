"""The encounter_game table shape the migration and the services rely on."""

from shared.core import enums
from shared.models.tournament.encounter_game import EncounterGame
from shared.models.tournament.encounter_report import EncounterMapReport


def test_live_position_is_unique_only_among_non_cancelled_games() -> None:
    index = next(i for i in EncounterGame.__table__.indexes if i.name == "uq_encounter_game_encounter_position")
    assert index.unique
    assert [c.name for c in index.columns] == ["encounter_id", "position"]
    assert "cancelled" in str(index.dialect_options["postgresql"]["where"])


def test_map_report_is_keyed_by_game_and_side() -> None:
    unique = next(c for c in EncounterMapReport.__table__.constraints if c.name == "uq_encounter_map_report_game_side")
    assert [c.name for c in unique.columns] == ["game_id", "side"]
    assert "team_id" not in EncounterMapReport.__table__.c
    assert "map_index" not in EncounterMapReport.__table__.c


def test_played_is_no_longer_an_entry_status() -> None:
    assert "played" not in {member.value for member in enums.MapPoolEntryStatus}
