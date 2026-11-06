"""The CLI refuses a mapping without an aggregate before it opens a database session (spec §15.2)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # backend/, where ``scripts`` lives

from scripts import league_merge  # noqa: E402


def test_apply_refuses_a_league_without_aggregate(tmp_path, monkeypatch) -> None:
    mapping = tmp_path / "league_merge.json"
    mapping.write_text(
        json.dumps(
            [
                {
                    "league": "Weekly",
                    "season": 1,
                    "name": "Weekly",
                    "target_tournament_id": 1,
                    "aggregate": None,
                    "days": [{"tournament_id": 1, "day": 1}],
                }
            ]
        ),
        encoding="utf-8",
    )

    def no_database():
        raise AssertionError("apply opened a session before validating the file")

    monkeypatch.setattr(league_merge, "_session_maker", no_database)

    result = CliRunner().invoke(league_merge.cli, ["apply", "--file", str(mapping), "--dry-run"])

    assert result.exit_code == 1
    assert "league 'Weekly' season 1: aggregate is required" in result.output
    assert not mapping.with_suffix(".snapshot.json").exists()


def test_plan_refuses_to_overwrite_an_edited_file(tmp_path) -> None:
    out = tmp_path / "league_merge.json"
    out.write_text("[]", encoding="utf-8")
    result = CliRunner().invoke(league_merge.cli, ["plan", "--output", str(out)])
    assert result.exit_code == 1 and "already exists" in result.output
