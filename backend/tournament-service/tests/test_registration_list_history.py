"""Unit tests for the participants-list tournament-history builder.

Covers the Tier A/B optimization of ``_build_tournament_history``:
- history is capped at ``HISTORY_LIMIT`` while ``count`` reports the true total
- duplicate Player rows per tournament (substitutions) are deduplicated
- ``division_grids`` only contains versions referenced by the (post-cap) entries
- each entry carries a ``division_grid_version_id`` reference, not an embedded version
"""

from __future__ import annotations

import importlib
import os
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"

registration = importlib.import_module("src.schemas.registration_build")


def _registration(reg_id: int, user_id: int) -> SimpleNamespace:
    """A registration with a resolved player identity: since dbarch02 the ONLY
    anchor is the (eager-loaded) workspace_member, whose player_id is the
    analytics user id."""
    return SimpleNamespace(id=reg_id, workspace_member=SimpleNamespace(player_id=user_id))


def _row(
    tournament_id: int,
    user_id: int,
    *,
    rank: int | None,
    role: str | None = "tank",
    name: str | None = None,
) -> tuple:
    """A history query row: (tournament_id, user_id, role, rank, tournament_name)."""
    role_obj = SimpleNamespace(value=role) if role is not None else None
    return (tournament_id, user_id, role_obj, rank, name or f"Tournament {tournament_id}")


def _fake_version_payload(version_id: int) -> dict:
    """A ``DivisionGridVersionRead``-shaped payload, as the cached batch loader returns."""
    return {
        "id": version_id,
        "grid_id": 1,
        "version": 1,
        "label": f"v{version_id}",
        "status": "published",
        "created_from_version_id": None,
        "published_at": datetime(2026, 1, 1),
        "tiers": [],
    }


def _fake_session(rows: list[tuple]) -> SimpleNamespace:
    """Session whose history ``execute`` returns ``rows``.

    Nothing else is reachable: every grid lookup ``_build_tournament_history``
    performs is a batch helper, and all three are patched out in ``_patches``.
    """
    history_result = SimpleNamespace(all=lambda: rows)
    return SimpleNamespace(execute=AsyncMock(return_value=history_result))


def _patches(*, version_map: dict[int, int | None], division: int = 4):
    """Patch the Redis-cached grid helpers used by ``_build_tournament_history``.

    These are the BATCH helpers -- the builder resolves every historical
    tournament in a constant number of round trips rather than one await per
    tournament. Patching the singular ``get_effective_division_grid_version_id``
    / ``load_division_grid_snapshot`` here silently stopped matching the module
    and the tests died on ``patch.object``'s missing-attribute check.
    """

    async def fake_version_ids(_session, _workspace_id, tournament_ids):
        return {tid: version_map.get(tid) for tid in tournament_ids}

    grid = SimpleNamespace(resolve_division_number=lambda _rank: division)
    snapshot = SimpleNamespace(to_runtime_grid=lambda: grid)

    async def fake_snapshots(_session, version_ids):
        return dict.fromkeys(version_ids, snapshot)

    async def fake_version_payloads(_session, version_ids):
        return {vid: _fake_version_payload(vid) for vid in version_ids}

    return (
        patch.object(
            registration,
            "get_effective_division_grid_version_ids",
            AsyncMock(side_effect=fake_version_ids),
        ),
        patch.object(
            registration,
            "load_division_grid_snapshots",
            AsyncMock(side_effect=fake_snapshots),
        ),
        patch.object(
            registration,
            "load_division_grid_version_read_payloads",
            AsyncMock(side_effect=fake_version_payloads),
        ),
    )


class BuildTournamentHistoryTests(IsolatedAsyncioTestCase):
    async def test_caps_history_and_reports_true_count(self) -> None:
        reg = _registration(1, user_id=100)
        # 12 tournaments, already ordered most-recent-first (ids 12 -> 1).
        rows = [_row(tid, 100, rank=2000) for tid in range(12, 0, -1)]
        version_map = dict.fromkeys(range(1, 13), 5)

        ver_patch, snap_patch, read_patch = _patches(version_map=version_map, division=4)
        with ver_patch, snap_patch, read_patch:
            history_map, count_map, division_grids = await registration._build_tournament_history(
                _fake_session(rows),
                [reg],
                current_tournament_id=999,
                workspace_id=1,
            )

        self.assertEqual(registration.HISTORY_LIMIT, len(history_map[1]))
        self.assertEqual(12, count_map[1])
        # Cap keeps the most-recent entries in order (ids 12..3).
        self.assertEqual(list(range(12, 2, -1)), [e.tournament_id for e in history_map[1]])
        for entry in history_map[1]:
            self.assertEqual(5, entry.division_grid_version_id)
            self.assertEqual(4, entry.division)
        # division_grids is keyed by stringified version id (JSON wire format).
        self.assertEqual({"5"}, set(division_grids))

    async def test_dedup_substitution_rows(self) -> None:
        reg = _registration(1, user_id=100)
        # Tournament 50 appears twice (e.g. main + substitution); 40 once. No rank.
        rows = [
            _row(50, 100, rank=None),
            _row(50, 100, rank=None, role="damage"),
            _row(40, 100, rank=None),
        ]

        ver_patch, snap_patch, read_patch = _patches(version_map={})
        with ver_patch, snap_patch, read_patch:
            history_map, count_map, division_grids = await registration._build_tournament_history(
                _fake_session(rows),
                [reg],
                current_tournament_id=999,
                workspace_id=1,
            )

        self.assertEqual([50, 40], [e.tournament_id for e in history_map[1]])
        self.assertEqual(2, count_map[1])
        self.assertEqual({}, division_grids)
        # No rank -> no division/version reference.
        self.assertTrue(all(e.division_grid_version_id is None for e in history_map[1]))

    async def test_division_grids_only_keeps_referenced_versions(self) -> None:
        reg = _registration(1, user_id=100)
        # 11 newest tournaments on version 5, oldest (id 1) on version 7.
        rows = [_row(tid, 100, rank=2000) for tid in range(12, 1, -1)]  # ids 12..2 -> v5
        rows.append(_row(1, 100, rank=2000))  # oldest -> v7, dropped by the cap
        version_map = dict.fromkeys(range(2, 13), 5)
        version_map[1] = 7

        ver_patch, snap_patch, read_patch = _patches(version_map=version_map, division=3)
        with ver_patch, snap_patch, read_patch:
            history_map, count_map, division_grids = await registration._build_tournament_history(
                _fake_session(rows),
                [reg],
                current_tournament_id=999,
                workspace_id=1,
            )

        self.assertEqual(registration.HISTORY_LIMIT, len(history_map[1]))
        self.assertEqual(12, count_map[1])
        # Version 7 was resolved but its only tournament fell outside the cap.
        self.assertEqual({"5"}, set(division_grids))

    async def test_no_resolvable_players_returns_empty(self) -> None:
        # Registration without a workspace_member -> no player identity at all.
        reg = SimpleNamespace(id=1, workspace_member=None)
        session = SimpleNamespace(execute=AsyncMock())

        history_map, count_map, division_grids = await registration._build_tournament_history(
            session, [reg], current_tournament_id=999, workspace_id=1
        )

        self.assertEqual({}, history_map)
        self.assertEqual({}, count_map)
        self.assertEqual({}, division_grids)
        session.execute.assert_not_awaited()

    async def test_falls_back_to_workspace_member_player_id(self) -> None:
        """A registration with a loaded ``workspace_member`` resolves via
        ``workspace_member.player_id`` — the sole identity path since dbarch02."""
        reg = SimpleNamespace(id=1, workspace_member=SimpleNamespace(player_id=100))
        rows = [_row(50, 100, rank=None)]

        ver_patch, snap_patch, read_patch = _patches(version_map={})
        with ver_patch, snap_patch, read_patch:
            history_map, count_map, division_grids = await registration._build_tournament_history(
                _fake_session(rows),
                [reg],
                current_tournament_id=999,
                workspace_id=1,
            )

        self.assertEqual([50], [e.tournament_id for e in history_map[1]])
        self.assertEqual(1, count_map[1])

    async def test_uses_sql_history_count_when_present(self) -> None:
        reg = _registration(1, user_id=100)
        # SQL already capped to HISTORY_LIMIT rows but reported the true total.
        rows = [_row(tid, 100, rank=None) + (12,) for tid in range(12, 2, -1)]

        ver_patch, snap_patch, read_patch = _patches(version_map={})
        with ver_patch, snap_patch, read_patch:
            history_map, count_map, _division_grids = await registration._build_tournament_history(
                _fake_session(rows),
                [reg],
                current_tournament_id=999,
                workspace_id=1,
            )

        self.assertEqual(registration.HISTORY_LIMIT, len(history_map[1]))
        self.assertEqual(12, count_map[1])
        self.assertEqual(list(range(12, 2, -1)), [e.tournament_id for e in history_map[1]])
