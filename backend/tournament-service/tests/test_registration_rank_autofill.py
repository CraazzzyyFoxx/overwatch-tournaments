"""Unit tests for registration rank autofill planning."""

from __future__ import annotations

import importlib
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

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

reg_admin = importlib.import_module("src.services.registration.admin")


def test_rank_snapshot_model_is_available_from_service_models() -> None:
    assert hasattr(reg_admin.models, "UserRankSnapshot")


def _role(role: str, rank_value: int | None = None, priority: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        role=role,
        rank_value=rank_value,
        is_active=True,
        priority=priority,
    )


def _registration(*roles: SimpleNamespace, battle_tag: str | None = "Main#123") -> SimpleNamespace:
    return SimpleNamespace(
        id=42,
        display_name="Main",
        battle_tag=battle_tag,
        status="approved",
        balancer_status="not_in_balancer",
        exclude_from_balancer=True,
        roles=list(roles),
    )


def _snapshot(rank_value: int, *, role: str = "damage") -> SimpleNamespace:
    return SimpleNamespace(
        rank_value=rank_value,
        role=role,
        platform="pc",
        division="master",
        tier=3,
        season=15,
        captured_at=datetime(2026, 6, 1, tzinfo=UTC),
    )


def test_autofill_keeps_existing_rank_without_overwrite() -> None:
    row, updates = reg_admin.build_registration_rank_autofill_plan(
        _registration(_role("dps", 2500)),
        {"damage": _snapshot(2700)},
        battle_tag_linked=True,
        overwrite_existing=False,
    )

    assert updates == []
    assert row["status"] == "unchanged"
    assert row["roles"][0]["action"] == "keep_existing"
    assert row["roles"][0]["current_rank_value"] == 2500
    assert row["roles"][0]["parsed_rank_value"] == 2700


def test_autofill_overwrites_existing_rank_when_allowed() -> None:
    support = _role("support", 2100)

    row, updates = reg_admin.build_registration_rank_autofill_plan(
        _registration(support),
        {"support": _snapshot(2500, role="support")},
        battle_tag_linked=True,
        overwrite_existing=True,
    )

    assert row["status"] == "will_update"
    assert row["roles"][0]["action"] == "overwrite"
    assert len(updates) == 1
    assert updates[0][0] is support
    assert updates[0][1].rank_value == 2500


def test_autofill_sets_missing_ranks_from_active_registered_roles() -> None:
    tank = _role("tank", priority=0)
    dps = _role("dps", priority=1)

    row, updates = reg_admin.build_registration_rank_autofill_plan(
        _registration(tank, dps),
        {"tank": _snapshot(3100, role="tank"), "damage": _snapshot(3300)},
        battle_tag_linked=True,
        overwrite_existing=False,
    )

    assert row["status"] == "will_update"
    assert [role_row["action"] for role_row in row["roles"]] == ["set", "set"]
    assert [snapshot.rank_value for _, snapshot in updates] == [3100, 3300]


def test_autofill_skips_player_when_registered_role_has_no_parsed_rank() -> None:
    row, updates = reg_admin.build_registration_rank_autofill_plan(
        _registration(_role("dps", priority=0), _role("support", priority=1)),
        {"damage": _snapshot(3300)},
        battle_tag_linked=True,
        overwrite_existing=False,
    )

    assert updates == []
    assert row["status"] == "skipped"
    assert row["reason"] == "No parsed rank for registered role(s): Support."
    assert [role_row["action"] for role_row in row["roles"]] == ["blocked", "missing_rank"]


def test_autofill_skips_unlinked_main_battle_tag() -> None:
    row, updates = reg_admin.build_registration_rank_autofill_plan(
        _registration(_role("dps")),
        {"damage": _snapshot(3300)},
        battle_tag_linked=False,
        overwrite_existing=False,
    )

    assert updates == []
    assert row["status"] == "skipped"
    assert row["reason"] == "Main BattleTag is not linked to an analytics player account."


def test_autofill_can_add_player_to_balancer_after_rank_update() -> None:
    dps = _role("dps")
    registration = _registration(dps)
    row, updates = reg_admin.build_registration_rank_autofill_plan(
        registration,
        {"damage": _snapshot(3300)},
        battle_tag_linked=True,
        overwrite_existing=False,
    )

    will_add, reason = reg_admin._rank_autofill_balancer_addition(
        registration,
        updates,
        add_to_balancer=True,
    )

    assert row["status"] == "will_update"
    assert will_add is True
    assert reason is None


def test_autofill_can_add_unchanged_ranked_player_to_balancer() -> None:
    registration = _registration(_role("support", rank_value=3600))
    _row, updates = reg_admin.build_registration_rank_autofill_plan(
        registration,
        {"support": _snapshot(3600, role="support")},
        battle_tag_linked=True,
        overwrite_existing=False,
    )

    will_add, reason = reg_admin._rank_autofill_balancer_addition(
        registration,
        updates,
        add_to_balancer=True,
    )

    assert will_add is True
    assert reason is None


def test_autofill_does_not_add_unapproved_player_to_balancer() -> None:
    registration = _registration(_role("support", rank_value=3600))
    registration.status = "pending"

    will_add, reason = reg_admin._rank_autofill_balancer_addition(
        registration,
        [],
        add_to_balancer=True,
    )

    assert will_add is False
    assert reason == "Registration must be approved before it can be added to balancer."


# ── Blended suggestion (division history + OW peak/current) ──────────────────────────────────


class _FakeGrid:
    """Identity grid for SR in [1000, 4900]; everything else is unmapped (None)."""

    def resolve_division_from_ow_rank(self, ow_rank: int | None):
        if ow_rank is None or ow_rank < 1000 or ow_rank > 4900:
            return None
        return SimpleNamespace(rank_min=ow_rank)


def _signals(*, peak: int | None, current: int | None, season: int | None = 15) -> SimpleNamespace:
    peak_snapshot = _snapshot(peak) if peak is not None else None
    current_snapshot = _snapshot(current) if current is not None else None
    if peak_snapshot is not None:
        peak_snapshot.season = season
    if current_snapshot is not None:
        current_snapshot.season = season
    return reg_admin._OwRankSignals(
        current_snapshot=current_snapshot,
        peak_snapshot=peak_snapshot,
        current_season=season,
    )


def test_blend_division_history_only() -> None:
    data = reg_admin._build_blended_rank_data(None, 3400, _FakeGrid())

    assert data is not None
    assert data.rank_value == 3400
    assert data.used_source == "division_history"
    assert data.source == "balancer"
    assert data.division_history_rank_value == 3400
    assert data.ow_peak_rank_value is None
    assert data.ow_current_rank_value is None


def test_blend_ow_only_uses_peak() -> None:
    data = reg_admin._build_blended_rank_data(
        _signals(peak=3450, current=3200), None, _FakeGrid()
    )

    assert data is not None
    assert data.rank_value == 3450
    assert data.used_source == "ow_peak"
    assert data.source == "analytics"
    assert data.ow_peak_rank_value == 3450
    assert data.ow_current_rank_value == 3200  # reported but not chosen


def test_blend_peak_beats_lower_division_history() -> None:
    data = reg_admin._build_blended_rank_data(
        _signals(peak=3450, current=3200), 3400, _FakeGrid()
    )

    assert data is not None
    assert data.rank_value == 3450
    assert data.used_source == "ow_peak"


def test_blend_division_history_beats_lower_peak() -> None:
    data = reg_admin._build_blended_rank_data(
        _signals(peak=3450, current=3200), 3500, _FakeGrid()
    )

    assert data is not None
    assert data.rank_value == 3500
    assert data.used_source == "division_history"


def test_blend_tie_prefers_division_history() -> None:
    data = reg_admin._build_blended_rank_data(
        _signals(peak=3400, current=3400), 3400, _FakeGrid()
    )

    assert data is not None
    assert data.rank_value == 3400
    assert data.used_source == "division_history"


def test_blend_unmapped_ow_falls_back_to_division_history() -> None:
    data = reg_admin._build_blended_rank_data(
        _signals(peak=5000, current=5000), 3400, _FakeGrid()
    )

    assert data is not None
    assert data.rank_value == 3400
    assert data.used_source == "division_history"
    assert data.ow_peak_rank_value is None


def test_blend_returns_none_when_no_signal() -> None:
    assert reg_admin._build_blended_rank_data(None, None, _FakeGrid()) is None
    # OW present but unmapped, no division history → still nothing usable.
    assert (
        reg_admin._build_blended_rank_data(_signals(peak=5000, current=5000), None, _FakeGrid())
        is None
    )


# ── OW signal grouping (current + current-season peak) ───────────────────────────────────────


def _tagged(rank_value: int, *, season: int, role: str = "damage", tag_id: int = 7) -> SimpleNamespace:
    snapshot = _snapshot(rank_value, role=role)
    snapshot.season = season
    snapshot.battle_tag_id = tag_id
    return snapshot


def test_group_peak_is_current_season_only() -> None:
    # Newest-first: current is season 15 @ 3200; a higher 3900 sits in the older season 14.
    snapshots = [
        _tagged(3200, season=15),
        _tagged(3100, season=15),
        _tagged(3900, season=14),  # higher, but old season → ignored for peak
    ]

    grouped = reg_admin._group_ow_rank_signals(snapshots)
    signals = grouped[7]["damage"]

    assert signals.current_season == 15
    assert signals.current_snapshot.rank_value == 3200
    assert signals.peak_snapshot.rank_value == 3200  # 3100 lower, 3900 wrong season


def test_group_peak_picks_highest_within_current_season() -> None:
    snapshots = [
        _tagged(3200, season=15),
        _tagged(3600, season=15),  # in-season peak
        _tagged(3400, season=15),
    ]

    grouped = reg_admin._group_ow_rank_signals(snapshots)
    signals = grouped[7]["damage"]

    assert signals.current_snapshot.rank_value == 3200
    assert signals.peak_snapshot.rank_value == 3600
