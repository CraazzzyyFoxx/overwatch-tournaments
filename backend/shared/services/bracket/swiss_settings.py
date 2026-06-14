from __future__ import annotations

from collections import Counter
from typing import Any

SWISS_BYES_KEY = "swiss_byes"
SWISS_STOPPED_SCOPES_KEY = "swiss_stopped_scopes"


def swiss_scope_key(stage_item_id: int | None) -> str:
    return str(stage_item_id) if stage_item_id is not None else "stage"


def swiss_bye_team_ids(stage: Any, stage_item_id: int | None) -> list[int]:
    settings = _settings(stage)
    raw_byes = settings.get(SWISS_BYES_KEY)
    if not isinstance(raw_byes, dict):
        return []

    raw_team_ids = raw_byes.get(swiss_scope_key(stage_item_id))
    if not isinstance(raw_team_ids, list):
        return []

    team_ids: list[int] = []
    for team_id in raw_team_ids:
        try:
            team_ids.append(int(team_id))
        except (TypeError, ValueError):
            continue
    return team_ids


def swiss_bye_counts(stage: Any, stage_item_id: int | None) -> dict[int, int]:
    return dict(Counter(swiss_bye_team_ids(stage, stage_item_id)))


def record_swiss_bye(stage: Any, stage_item_id: int | None, team_id: int) -> None:
    settings = dict(_settings(stage))
    raw_byes = settings.get(SWISS_BYES_KEY)
    byes = dict(raw_byes) if isinstance(raw_byes, dict) else {}
    scope_key = swiss_scope_key(stage_item_id)
    scope_byes = list(byes.get(scope_key, []))
    scope_byes.append(int(team_id))
    byes[scope_key] = scope_byes
    settings[SWISS_BYES_KEY] = byes
    stage.settings_json = settings


def clear_swiss_byes(stage: Any, stage_item_id: int | None) -> None:
    settings = dict(_settings(stage))
    raw_byes = settings.get(SWISS_BYES_KEY)
    if not isinstance(raw_byes, dict):
        return

    byes = dict(raw_byes)
    byes.pop(swiss_scope_key(stage_item_id), None)
    if byes:
        settings[SWISS_BYES_KEY] = byes
    else:
        settings.pop(SWISS_BYES_KEY, None)
    stage.settings_json = settings


def swiss_scope_stopped(stage: Any, stage_item_id: int | None) -> bool:
    stopped_scopes = _settings(stage).get(SWISS_STOPPED_SCOPES_KEY)
    return isinstance(stopped_scopes, list) and swiss_scope_key(stage_item_id) in stopped_scopes


def mark_swiss_scope_stopped(stage: Any, stage_item_id: int | None) -> None:
    settings = dict(_settings(stage))
    raw_scopes = settings.get(SWISS_STOPPED_SCOPES_KEY)
    stopped_scopes = list(raw_scopes) if isinstance(raw_scopes, list) else []
    scope_key = swiss_scope_key(stage_item_id)
    if scope_key not in stopped_scopes:
        stopped_scopes.append(scope_key)
    settings[SWISS_STOPPED_SCOPES_KEY] = stopped_scopes
    stage.settings_json = settings


def clear_swiss_scope_stopped(stage: Any, stage_item_id: int | None) -> None:
    settings = dict(_settings(stage))
    raw_scopes = settings.get(SWISS_STOPPED_SCOPES_KEY)
    if not isinstance(raw_scopes, list):
        return

    scope_key = swiss_scope_key(stage_item_id)
    stopped_scopes = [value for value in raw_scopes if value != scope_key]
    if stopped_scopes:
        settings[SWISS_STOPPED_SCOPES_KEY] = stopped_scopes
    else:
        settings.pop(SWISS_STOPPED_SCOPES_KEY, None)
    stage.settings_json = settings


def _settings(stage: Any) -> dict[str, Any]:
    settings = getattr(stage, "settings_json", None)
    return settings if isinstance(settings, dict) else {}
