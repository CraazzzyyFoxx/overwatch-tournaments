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


def test_a_failed_league_keeps_the_snapshot_and_still_queues_what_merged(tmp_path, monkeypatch) -> None:
    from src.services.flow.league_merge import GrantSnapshot, MergeLog  # noqa: PLC0415

    mapping = tmp_path / "league_merge.json"
    aggregate = {"unit": "players", "score": {"preset": "stage_points"}, "mode": "sum_all"}
    mapping.write_text(
        json.dumps(
            [
                {
                    "league": "Weekly",
                    "season": n,
                    "name": f"Weekly {n}",
                    "target_tournament_id": n,
                    "aggregate": aggregate,
                    "days": [{"tournament_id": n, "day": 1}],
                }
                for n in (1, 2)
            ]
        ),
        encoding="utf-8",
    )
    snapshot_file = mapping.with_suffix(".snapshot.json")
    snapshot_file.write_text(GrantSnapshot([(9, 9, 9, None, None)], ["old-run"]).to_json(), encoding="utf-8")
    calls: list[str] = []

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def commit(self):
            calls.append("commit")

    async def affected_scope(session, tournament_ids):
        return {7}, {8}

    async def snapshot_results(session, **kwargs):
        return [(1, 8, 1, None, None)]

    async def apply_mapping(maker, entries, *, dry_run, logs):
        logs.append(MergeLog(entries[0].target_tournament_id, []))
        raise RuntimeError("league 2 failed")

    async def queue_evaluations(session, workspaces):
        calls.append("evaluations")
        return ["new-run"]

    async def queue_analytics(session, targets):
        calls.append(f"analytics {sorted(targets)}")
        return {7: "job 1"}

    async def bump(*generations):
        calls.append("bump")

    monkeypatch.setattr(league_merge, "_session_maker", lambda: Session)
    for fn in (affected_scope, snapshot_results, apply_mapping, queue_evaluations, queue_analytics, bump):
        monkeypatch.setattr(league_merge, fn.__name__, fn)
    monkeypatch.setattr(league_merge, "configure_generations", lambda url: None)

    result = CliRunner().invoke(league_merge.cli, ["apply", "--file", str(mapping)])

    assert isinstance(result.exception, RuntimeError)
    saved = GrantSnapshot.from_json(snapshot_file.read_text(encoding="utf-8"))
    assert saved.keys == [(1, 8, 1, None, None), (9, 9, 9, None, None)]
    assert saved.run_ids == ["old-run", "new-run"]
    assert calls == ["evaluations", "commit", "bump", "analytics [1]", "commit"]
