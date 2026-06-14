"""Shared utility functions and constants for the balancer subsystem.

This module contains pure functions and constants used by both the legacy
sheet-based balancer (balancer.py) and the registration-based balancer
(balancer_registration.py). Consolidating them here eliminates duplication
and ensures consistent behavior across both systems.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

from fastapi import HTTPException, status

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GOOGLE_SHEET_FETCH_TIMEOUT = 20.0
"""Timeout (in seconds) for fetching data from Google Sheets."""

UNKNOWN_PRIORITY_SENTINEL = 99
"""Sentinel value used when a role's priority is unknown or unset."""

DEFAULT_SORT_PRIORITY_SENTINEL = 999
"""Sentinel value for sorting roles with unset priority to the end."""

MIN_SYNC_INTERVAL_SECONDS = 30
"""Minimum interval (seconds) between automatic Google Sheet feed syncs."""

DEFAULT_SYNC_INTERVAL_SECONDS = 300
"""Default interval (seconds) between automatic Google Sheet feed syncs."""

VALID_ROLES = {"tank", "dps", "support"}
LEGACY_ROLE_SUBTYPES: dict[str, set[str]] = {
    "tank": set(),
    "dps": {"hitscan", "projectile"},
    "support": {"main_heal", "light_heal"},
}
VALID_ROLE_SUBTYPES = LEGACY_ROLE_SUBTYPES

ROLE_ORDER = ("tank", "dps", "support")

# Legacy verbose Russian role mapping (used by legacy sheet sync in balancer.py)
DEFAULT_ROLE_MAPPING: dict[str, str | None] = {
    "Лайт хил (Мерси, Кирико)": "support",
    "Лайт хил (Мерси, Зен, Люсио, Брига, Мойра)": "support",
    "Лайт хил (Мерси, Зен, Люсио, Брига)": "support",
    "Лайт хил (Мерси, Иллари, Зен, Люсио, Брига, Мойра)": "support",
    "Оба Подкласса Хила": "support",
    "Мейн хил (Ана, Батист, Мойра)": "support",
    "Мейн хил (Юнона, Ана, Батист, Мойра)": "support",
    "Танк": "tank",
    "Танк.": "tank",
    "Оба Подкласса Танка.": "tank",
    "ОффТанк (Заря, Дива, Хог, Сигма)": "tank",
    "МейнТанк (Рейнхард, Винстон, Ориса, Хэммонд)": "tank",
    "Оба Подкласса ДД": "dps",
    "Dps": "dps",
    "Проджектайл ДД (Генджи, Фара, Ханзо, Торбьерн, Джанкрет, Эхо, Мей, Рипер, Сомбра, Симметра, Трейсер)": "dps",
    "Хитскан ДД (Маккри, Вдова, Солдат76, Эш)": "dps",
    "Хитскан ДД (Кэс, Вдова, Солдат76, Эш)": "dps",
    "Я флекс, могу играть абсолютно на всем": None,
}

# Short-token role mapping (used by registration sheet sync in balancer_registration.py)
DEFAULT_ROLE_VALUE_MAP: dict[str, str | None] = {
    "support": "support",
    "поддержка": "support",
    "танк": "tank",
    "tank": "tank",
    "dps": "dps",
    "damage": "dps",
    "дд": "dps",
}

# Subrole token mapping (used by registration sheet sync)
DEFAULT_SUBROLE_VALUE_MAP: dict[str, str | None] = {
    "hitscan": "hitscan",
    "хитскан": "hitscan",
    "projectile": "projectile",
    "проджектайл": "projectile",
    "main_heal": "main_heal",
    "main heal": "main_heal",
    "мейн хил": "main_heal",
    "light_heal": "light_heal",
    "light heal": "light_heal",
    "лайт хил": "light_heal",
}

# Boolean true values for parsing sheet data
DEFAULT_BOOLEAN_TRUE_VALUES = {
    "1",
    "true",
    "yes",
    "y",
    "да",
    "ага",
    "буду",
    "конечно",
}

# Legacy alias (same values, used in balancer.py)
STREAM_TRUE_VALUES = DEFAULT_BOOLEAN_TRUE_VALUES


# ---------------------------------------------------------------------------
# Pure utility functions
# ---------------------------------------------------------------------------


def normalize_battle_tag(value: str | None) -> str | None:
    """Normalize a battle tag by collapsing spaces around '#'.

    Returns None for empty/whitespace-only input.
    """
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    return re.sub(r"\s*#\s*", "#", text)


def normalize_battle_tag_key(value: str | None) -> str | None:
    """Create a case-insensitive, space-free lookup key from a battle tag.

    Returns None for empty/whitespace-only input.
    """
    normalized = normalize_battle_tag(value)
    if not normalized:
        return None
    return normalized.replace(" ", "").strip().lower()


def normalize_header(value: str | None) -> str:
    """Normalize a sheet header: collapse whitespace, lowercase."""
    return re.sub(r"\s+", " ", (value or "").strip()).lower()


def unique_strings(values: list[str]) -> list[str]:
    """Deduplicate a list of strings while preserving order. Skips empty strings."""
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def extract_sheet_source(source_url: str) -> tuple[str, str | None]:
    """Extract (sheet_id, gid) from a Google Sheets URL.

    Raises HTTPException(400) if the URL is not a valid Sheets URL.
    """
    match = re.search(r"/spreadsheets/d/([^/]+)", source_url)
    if not match:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Google Sheets URL")

    sheet_id = match.group(1)
    parsed = urlparse(source_url)
    query = parse_qs(parsed.query)
    gid = query.get("gid", [None])[0]
    if gid is None and parsed.fragment.startswith("gid="):
        gid = parsed.fragment.split("=", 1)[1]
    return sheet_id, gid


def build_csv_export_url(sheet_id: str, gid: str | None) -> str:
    """Build a CSV export URL for a Google Sheets spreadsheet."""
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    return f"{url}&gid={gid}" if gid else url


def parse_datetime(value: str | None) -> datetime | None:
    """Parse a datetime string in multiple common formats.

    Tries several formats in order, falling back to fromisoformat().
    Returns None if parsing fails.
    """
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    formats = (
        "%m/%d/%Y %H:%M:%S",
        "%d.%m.%Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
    )
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


# Alias for backward compatibility in balancer.py callers
parse_submitted_at = parse_datetime


def parse_boolean_value(value: str | None, true_values: set[str] | None = None) -> bool:
    """Parse a boolean value from sheet data.

    Uses DEFAULT_BOOLEAN_TRUE_VALUES when true_values is not provided.
    Also returns True for values starting with 'да'.
    """
    if value is None:
        return False
    normalized = normalize_header(value)
    effective_values = true_values if true_values is not None else DEFAULT_BOOLEAN_TRUE_VALUES
    return normalized in effective_values or normalized.startswith("да")


def parse_integer(value: str | None) -> int | None:
    """Parse an integer from a string, stripping non-digit characters."""
    if value is None:
        return None
    digits = re.sub(r"[^\d-]", "", value.strip())
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def extract_battle_tags(value: str | None, battle_tag_re: re.Pattern[str]) -> list[str]:
    """Extract and deduplicate battle tags from a raw string value."""
    if not value:
        return []
    return unique_strings(
        [normalize_battle_tag(match) for match in battle_tag_re.findall(value) if normalize_battle_tag(match)]
    )


def build_header_keys(headers: list[str]) -> list[str]:
    """Build unique column keys from headers, appending __N suffix for duplicates."""
    seen: dict[str, int] = {}
    keys: list[str] = []
    for index, header in enumerate(headers):
        key_base = header.strip() or f"column_{index}"
        occurrence = seen.get(key_base, 0)
        seen[key_base] = occurrence + 1
        keys.append(key_base if occurrence == 0 else f"{key_base}__{occurrence}")
    return keys


def row_to_json(headers: list[str], row: list[str]) -> dict[str, str]:
    """Convert a CSV row to a dict using header-based keys with duplicate handling."""
    keys = build_header_keys(headers)
    return {
        key: row[index].strip() if index < len(row) else ""
        for index, key in enumerate(keys)
    }


def fetch_csv_rows(text: str) -> list[list[str]]:
    """Parse CSV text (after BOM stripping) into rows. Raises HTTPException if empty."""
    cleaned = text.lstrip("\ufeff")
    rows = list(csv.reader(io.StringIO(cleaned)))
    if not rows:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Google Sheet is empty")
    return rows
