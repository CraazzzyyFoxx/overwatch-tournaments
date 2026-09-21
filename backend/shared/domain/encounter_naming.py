from __future__ import annotations

from collections.abc import Mapping

__all__ = (
    "build_encounter_name",
    "build_encounter_name_from_ids",
)


def _normalize_team_name(name: str | None) -> str:
    if name is None:
        return "TBD"
    normalized = name.strip()
    return normalized or "TBD"


def build_encounter_name(home_team_name: str | None, away_team_name: str | None) -> str:
    return f"{_normalize_team_name(home_team_name)} vs {_normalize_team_name(away_team_name)}"


def build_encounter_name_from_ids(
    home_team_id: int | None,
    away_team_id: int | None,
    team_names_by_id: Mapping[int, str],
) -> str:
    home_team_name = team_names_by_id.get(home_team_id) if home_team_id is not None else None
    away_team_name = team_names_by_id.get(away_team_id) if away_team_id is not None else None
    return build_encounter_name(home_team_name, away_team_name)
