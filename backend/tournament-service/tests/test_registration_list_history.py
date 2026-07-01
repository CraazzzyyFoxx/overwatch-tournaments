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
os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

registration = importlib.import_module("src.schemas.registration_build")


def _registration(reg_id: int, user_id: int) -> SimpleNamespace:
    """A registration with a resolved analytics user_id (skips workspace_member fallback)."""
    return SimpleNamespace(id=reg_id, user_id=user_id, workspace_member=None)


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


def _fake_version(version_id: int) -> SimpleNamespace:
    """A DivisionGridVersion-shaped object for ``model_validate(..., from_attributes=True)``."""
    return SimpleNamespace(
        id=version_id,
        grid_id=1,
        version=1,
        label=f"v{version_id}",
        status="published",
        created_from_version_id=None,
        published_at=datetime(2026, 1, 1),
        tiers=[],
    )


def _fake_session(rows: list[tuple], versions: list[SimpleNamespace]) -> SimpleNamespace:
    """Session whose history ``execute`` returns ``rows`` and ``scalars`` returns ``versions``."""
    history_result = SimpleNamespace(all=lambda: rows)
    return SimpleNamespace(
        execute=AsyncMock(return_value=history_result),
        scalars=AsyncMock(return_value=versions),
    )


def _patches(*, version_map: dict[int, int | None], division: int = 4):
    """Patch the Redis-cached grid helpers used by ``_build_tournament_history``."""

    async def fake_version_id(_session, _workspace_id, tournament_id):
        return version_map.get(tournament_id)

    grid = SimpleNamespace(resolve_division_number=lambda _rank: division)
    snapshot = SimpleNamespace(to_runtime_grid=lambda: grid)

    async def fake_snapshot(_session, _version_id):
        return snapshot

    return (
        patch.object(
            registration,
            "get_effective_division_grid_version_id",
            AsyncMock(side_effect=fake_version_id),
        ),
        patch.object(
            registration,
            "load_division_grid_snapshot",
            AsyncMock(side_effect=fake_snapshot),
        ),
    )


class BuildTournamentHistoryTests(IsolatedAsyncioTestCase):
    async def test_caps_history_and_reports_true_count(self) -> None:
        reg = _registration(1, user_id=100)
        # 12 tournaments, already ordered most-recent-first (ids 12 -> 1).
        rows = [_row(tid, 100, rank=2000) for tid in range(12, 0, -1)]
        version_map = dict.fromkeys(range(1, 13), 5)

        ver_patch, snap_patch = _patches(version_map=version_map, division=4)
        with ver_patch, snap_patch:
            history_map, count_map, division_grids = await registration._build_tournament_history(
                _fake_session(rows, [_fake_version(5)]),
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
            _row(50, 100, rank=None, role="dps"),
            _row(40, 100, rank=None),
        ]

        ver_patch, snap_patch = _patches(version_map={})
        with ver_patch, snap_patch:
            history_map, count_map, division_grids = await registration._build_tournament_history(
                _fake_session(rows, []),
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

        ver_patch, snap_patch = _patches(version_map=version_map, division=3)
        with ver_patch, snap_patch:
            history_map, count_map, division_grids = await registration._build_tournament_history(
                _fake_session(rows, [_fake_version(5), _fake_version(7)]),
                [reg],
                current_tournament_id=999,
                workspace_id=1,
            )

        self.assertEqual(registration.HISTORY_LIMIT, len(history_map[1]))
        self.assertEqual(12, count_map[1])
        # Version 7 was resolved but its only tournament fell outside the cap.
        self.assertEqual({"5"}, set(division_grids))

    async def test_no_resolvable_players_returns_empty(self) -> None:
        # Registration without user_id or a workspace_member -> nothing to resolve.
        reg = SimpleNamespace(id=1, user_id=None, workspace_member=None)
        session = SimpleNamespace(execute=AsyncMock(), scalars=AsyncMock())

        history_map, count_map, division_grids = await registration._build_tournament_history(
            session, [reg], current_tournament_id=999, workspace_id=1
        )

        self.assertEqual({}, history_map)
        self.assertEqual({}, count_map)
        self.assertEqual({}, division_grids)
        session.execute.assert_not_awaited()

    async def test_falls_back_to_workspace_member_player_id(self) -> None:
        """A registration with no ``user_id`` but a loaded ``workspace_member``
        resolves via ``workspace_member.player_id`` (self-service registrations)."""
        reg = SimpleNamespace(id=1, user_id=None, workspace_member=SimpleNamespace(player_id=100))
        rows = [_row(50, 100, rank=None)]

        ver_patch, snap_patch = _patches(version_map={})
        with ver_patch, snap_patch:
            history_map, count_map, division_grids = await registration._build_tournament_history(
                _fake_session(rows, []),
                [reg],
                current_tournament_id=999,
                workspace_id=1,
            )

        self.assertEqual([50], [e.tournament_id for e in history_map[1]])
        self.assertEqual(1, count_map[1])
