from __future__ import annotations

import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest import TestCase

import pytest

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("CHALLONGE_USERNAME", "test")
os.environ.setdefault("CHALLONGE_API_KEY", "test")
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost")
os.environ.setdefault("S3_BUCKET_NAME", "test")

from src.services.admin.balancer_utils import (  # noqa: E402
    build_csv_export_url,
    build_header_keys,
    extract_battle_tags,
    extract_sheet_source,
    fetch_csv_rows,
    normalize_battle_tag,
    normalize_battle_tag_key,
    normalize_header,
    parse_boolean_value,
    parse_datetime,
    parse_integer,
    row_to_json,
    unique_strings,
)


class NormalizeBattleTagTests(TestCase):
    def test_none_returns_none(self) -> None:
        assert normalize_battle_tag(None) is None

    def test_empty_returns_none(self) -> None:
        assert normalize_battle_tag("") is None
        assert normalize_battle_tag("   ") is None

    def test_normal_tag(self) -> None:
        assert normalize_battle_tag("Player#1234") == "Player#1234"

    def test_spaces_around_hash(self) -> None:
        assert normalize_battle_tag("Player  #  1234") == "Player#1234"

    def test_strips_whitespace(self) -> None:
        assert normalize_battle_tag("  Player#1234  ") == "Player#1234"


class NormalizeBattleTagKeyTests(TestCase):
    def test_none_returns_none(self) -> None:
        assert normalize_battle_tag_key(None) is None

    def test_lowercases_and_removes_spaces(self) -> None:
        assert normalize_battle_tag_key("Player Name#1234") == "playername#1234"

    def test_empty_returns_none(self) -> None:
        assert normalize_battle_tag_key("") is None


class NormalizeHeaderTests(TestCase):
    def test_collapses_whitespace(self) -> None:
        assert normalize_header("  Battle   Tag  ") == "battle tag"

    def test_none_returns_empty(self) -> None:
        assert normalize_header(None) == ""

    def test_lowercases(self) -> None:
        assert normalize_header("ROLE") == "role"


class UniqueStringsTests(TestCase):
    def test_deduplicates(self) -> None:
        assert unique_strings(["a", "b", "a", "c"]) == ["a", "b", "c"]

    def test_skips_empty(self) -> None:
        assert unique_strings(["a", "", "b", ""]) == ["a", "b"]

    def test_preserves_order(self) -> None:
        assert unique_strings(["c", "a", "b"]) == ["c", "a", "b"]

    def test_empty_input(self) -> None:
        assert unique_strings([]) == []


class ExtractSheetSourceTests(TestCase):
    def test_valid_url(self) -> None:
        url = "https://docs.google.com/spreadsheets/d/abc123/edit"
        sheet_id, gid = extract_sheet_source(url)
        assert sheet_id == "abc123"
        assert gid is None

    def test_url_with_gid_query(self) -> None:
        url = "https://docs.google.com/spreadsheets/d/abc123/edit?gid=456"
        sheet_id, gid = extract_sheet_source(url)
        assert sheet_id == "abc123"
        assert gid == "456"

    def test_url_with_gid_fragment(self) -> None:
        url = "https://docs.google.com/spreadsheets/d/abc123/edit#gid=789"
        sheet_id, gid = extract_sheet_source(url)
        assert sheet_id == "abc123"
        assert gid == "789"

    def test_invalid_url_raises(self) -> None:
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            extract_sheet_source("https://example.com/not-a-sheet")
        assert exc_info.value.status_code == 400


class BuildCsvExportUrlTests(TestCase):
    def test_without_gid(self) -> None:
        url = build_csv_export_url("abc123", None)
        assert url == "https://docs.google.com/spreadsheets/d/abc123/export?format=csv"

    def test_with_gid(self) -> None:
        url = build_csv_export_url("abc123", "456")
        assert url == "https://docs.google.com/spreadsheets/d/abc123/export?format=csv&gid=456"


class ParseDatetimeTests(TestCase):
    def test_none_returns_none(self) -> None:
        assert parse_datetime(None) is None

    def test_empty_returns_none(self) -> None:
        assert parse_datetime("") is None
        assert parse_datetime("   ") is None

    def test_us_format(self) -> None:
        result = parse_datetime("01/15/2024 14:30:00")
        assert result == datetime(2024, 1, 15, 14, 30, 0, tzinfo=UTC)

    def test_eu_format(self) -> None:
        result = parse_datetime("15.01.2024 14:30:00")
        assert result == datetime(2024, 1, 15, 14, 30, 0, tzinfo=UTC)

    def test_iso_format(self) -> None:
        result = parse_datetime("2024-01-15T14:30:00")
        assert result == datetime(2024, 1, 15, 14, 30, 0, tzinfo=UTC)

    def test_iso_with_microseconds(self) -> None:
        result = parse_datetime("2024-01-15T14:30:00.123456")
        assert result is not None
        assert result.year == 2024

    def test_invalid_returns_none(self) -> None:
        assert parse_datetime("not a date") is None


class ParseBooleanValueTests(TestCase):
    def test_none_returns_false(self) -> None:
        assert parse_boolean_value(None) is False

    def test_true_values(self) -> None:
        for val in ("1", "true", "yes", "y", "да", "ага", "буду", "конечно"):
            assert parse_boolean_value(val) is True, f"Expected True for {val!r}"

    def test_da_prefix(self) -> None:
        assert parse_boolean_value("дааа") is True

    def test_false_values(self) -> None:
        assert parse_boolean_value("no") is False
        assert parse_boolean_value("0") is False
        assert parse_boolean_value("false") is False

    def test_custom_true_values(self) -> None:
        custom = {"ok", "sure"}
        assert parse_boolean_value("ok", custom) is True
        assert parse_boolean_value("yes", custom) is False  # not in custom set


class ParseIntegerTests(TestCase):
    def test_none_returns_none(self) -> None:
        assert parse_integer(None) is None

    def test_normal_integer(self) -> None:
        assert parse_integer("42") == 42

    def test_with_non_digits(self) -> None:
        assert parse_integer("~1500 SR") == 1500

    def test_empty_returns_none(self) -> None:
        assert parse_integer("") is None

    def test_no_digits_returns_none(self) -> None:
        assert parse_integer("abc") is None


class ExtractBattleTagsTests(TestCase):
    BATTLE_TAG_RE = re.compile(r"[\w][\w ]{0,30}#[0-9]{3,}", re.UNICODE)

    def test_empty_returns_empty(self) -> None:
        assert extract_battle_tags(None, self.BATTLE_TAG_RE) == []
        assert extract_battle_tags("", self.BATTLE_TAG_RE) == []

    def test_single_tag(self) -> None:
        result = extract_battle_tags("Player#1234", self.BATTLE_TAG_RE)
        assert result == ["Player#1234"]

    def test_multiple_tags(self) -> None:
        result = extract_battle_tags("Player#1234, Other#5678", self.BATTLE_TAG_RE)
        assert "Player#1234" in result
        assert "Other#5678" in result

    def test_deduplicates(self) -> None:
        result = extract_battle_tags("Player#1234 Player#1234", self.BATTLE_TAG_RE)
        assert result == ["Player#1234"]


class BuildHeaderKeysTests(TestCase):
    def test_unique_headers(self) -> None:
        assert build_header_keys(["Name", "Age"]) == ["Name", "Age"]

    def test_duplicate_headers(self) -> None:
        assert build_header_keys(["Role", "Role"]) == ["Role", "Role__1"]

    def test_empty_header(self) -> None:
        keys = build_header_keys(["Name", "", "Age"])
        assert keys[1] == "column_1"


class RowToJsonTests(TestCase):
    def test_basic(self) -> None:
        result = row_to_json(["Name", "Age"], ["Alice", "30"])
        assert result == {"Name": "Alice", "Age": "30"}

    def test_strips_values(self) -> None:
        result = row_to_json(["Name"], ["  Alice  "])
        assert result == {"Name": "Alice"}

    def test_short_row(self) -> None:
        result = row_to_json(["Name", "Age"], ["Alice"])
        assert result == {"Name": "Alice", "Age": ""}


class FetchCsvRowsTests(TestCase):
    def test_valid_csv(self) -> None:
        rows = fetch_csv_rows("Name,Age\nAlice,30\n")
        assert len(rows) == 2
        assert rows[0] == ["Name", "Age"]
        assert rows[1] == ["Alice", "30"]

    def test_bom_stripped(self) -> None:
        rows = fetch_csv_rows("\ufeffName,Age\nAlice,30\n")
        assert rows[0] == ["Name", "Age"]

    def test_empty_raises(self) -> None:
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            fetch_csv_rows("")
        assert exc_info.value.status_code == 400
