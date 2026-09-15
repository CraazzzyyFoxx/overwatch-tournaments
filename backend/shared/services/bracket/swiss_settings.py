from __future__ import annotations

from collections import Counter
from typing import Any

SWISS_BYES_KEY = "swiss_byes"
SWISS_STOPPED_SCOPES_KEY = "swiss_stopped_scopes"


def swiss_scope_key(stage_item_id: int | None) -> str:
    return str(stage_item_id) if stage_item_id is not None else "stage"


def swiss_bye_team_ids(stage: Any, stage_item_id: int | None) -> list[int]:
    team_ids: list[int] = []
    for entry in _scope_byes(stage, stage_item_id):
        team_id = _entry_team_id(entry)
        if team_id is not None:
            team_ids.append(team_id)
    return team_ids


def swiss_bye_counts(stage: Any, stage_item_id: int | None) -> dict[int, int]:
    return dict(Counter(swiss_bye_team_ids(stage, stage_item_id)))


def record_swiss_bye(stage: Any, stage_item_id: int | None, team_id: int, *, round_number: int) -> None:
    settings = dict(_settings(stage))
    raw_byes = settings.get(SWISS_BYES_KEY)
    byes = dict(raw_byes) if isinstance(raw_byes, dict) else {}
    scope_key = swiss_scope_key(stage_item_id)
    scope_byes = list(byes.get(scope_key, []))
    scope_byes.append({"round": int(round_number), "team_id": int(team_id)})
    byes[scope_key] = scope_byes
    settings[SWISS_BYES_KEY] = byes
    stage.settings_json = settings


def remove_swiss_bye_round(stage: Any, stage_item_id: int | None, round_number: int) -> None:
    """Revoke the byes recorded for one round, e.g. when that round is deleted.

    Legacy entries stored as a bare team id carry no round, so they are kept:
    there is no way to tell which round they belonged to.
    """
    settings = dict(_settings(stage))
    raw_byes = settings.get(SWISS_BYES_KEY)
    if not isinstance(raw_byes, dict):
        return

    scope_key = swiss_scope_key(stage_item_id)
    scope_byes = raw_byes.get(scope_key)
    if not isinstance(scope_byes, list):
        return

    kept = [entry for entry in scope_byes if _entry_round(entry) != int(round_number)]
    if len(kept) == len(scope_byes):
        return

    byes = dict(raw_byes)
    byes[scope_key] = kept
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


def _scope_byes(stage: Any, stage_item_id: int | None) -> list[Any]:
    raw_byes = _settings(stage).get(SWISS_BYES_KEY)
    if not isinstance(raw_byes, dict):
        return []

    scope_byes = raw_byes.get(swiss_scope_key(stage_item_id))
    return scope_byes if isinstance(scope_byes, list) else []


def _entry_team_id(entry: Any) -> int | None:
    """Team id of one stored bye; a bare int is the legacy round-less form."""
    try:
        return int(entry["team_id"] if isinstance(entry, dict) else entry)
    except (KeyError, TypeError, ValueError):
        return None


def _entry_round(entry: Any) -> int | None:
    if not isinstance(entry, dict):
        return None
    try:
        return int(entry["round"])
    except (KeyError, TypeError, ValueError):
        return None


def _settings(stage: Any) -> dict[str, Any]:
    settings = getattr(stage, "settings_json", None)
    return settings if isinstance(settings, dict) else {}
