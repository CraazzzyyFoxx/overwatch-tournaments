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

from shared.division_grid import DivisionGrid, DivisionTier  # noqa: E402
from shared.services.division_grid_normalization import DivisionGridNormalizer  # noqa: E402


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


# ── Priority-chain suggestion (OW weekly composite / balancer / analytics) ───────────────────


class _FakeGrid:
    """Identity grid for ranks in [1000, 4900]; everything else is unmapped (None)."""

    def resolve_division_from_ow_rank(self, ow_rank: int | None):
        if ow_rank is None or ow_rank < 1000 or ow_rank > 4900:
            return None
        return SimpleNamespace(rank_min=ow_rank)


def _ow_signals(composite: int | None, *, latest_rank: int | None = None) -> SimpleNamespace:
    """OW signal whose weekly composite is already resolved to ``composite`` (pre-grid rank_value)."""
    latest_value = latest_rank if latest_rank is not None else composite
    latest = _snapshot(latest_value) if latest_value is not None else None
    return reg_admin._OwRankSignals(composite_rank_value=composite, latest_snapshot=latest)


# Ordered source chains (what ``resolve_autofill_stages`` produces for the legacy presets).
_OW_FIRST = ("ow", "division_history", "analytics")
_BALANCER_FIRST = ("division_history", "analytics", "ow")


def test_priority_ow_first_prefers_ow() -> None:
    # User-confirmed example: OW=3000, balancer=3200, analytics=2800 -> ow_first picks OW.
    data = reg_admin._build_priority_rank_data(_OW_FIRST, _ow_signals(3000), 3200, 2800, _FakeGrid())

    assert data is not None
    assert data.rank_value == 3000
    assert data.used_source == "ow"
    assert data.source == "analytics"
    assert data.ow_rank_value == 3000
    assert data.division_history_rank_value == 3200
    assert data.analytics_rank_value == 2800


def test_priority_balancer_first_prefers_balancer() -> None:
    data = reg_admin._build_priority_rank_data(_BALANCER_FIRST, _ow_signals(3000), 3200, 2800, _FakeGrid())

    assert data is not None
    assert data.rank_value == 3200
    assert data.used_source == "division_history"
    assert data.source == "balancer"


def test_priority_ow_first_falls_back_to_balancer() -> None:
    data = reg_admin._build_priority_rank_data(_OW_FIRST, None, 3200, 2800, _FakeGrid())

    assert data is not None
    assert data.rank_value == 3200
    assert data.used_source == "division_history"


def test_priority_ow_first_falls_back_to_analytics() -> None:
    data = reg_admin._build_priority_rank_data(_OW_FIRST, None, None, 2800, _FakeGrid())

    assert data is not None
    assert data.rank_value == 2800
    assert data.used_source == "analytics"


def test_priority_balancer_first_prefers_analytics_over_ow() -> None:
    data = reg_admin._build_priority_rank_data(_BALANCER_FIRST, _ow_signals(3000), None, 2800, _FakeGrid())

    assert data is not None
    assert data.rank_value == 2800
    assert data.used_source == "analytics"


def test_priority_balancer_first_falls_back_to_ow_last() -> None:
    data = reg_admin._build_priority_rank_data(_BALANCER_FIRST, _ow_signals(3000), None, None, _FakeGrid())

    assert data is not None
    assert data.rank_value == 3000
    assert data.used_source == "ow"


def test_priority_unmapped_ow_is_skipped() -> None:
    data = reg_admin._build_priority_rank_data(_OW_FIRST, _ow_signals(5000), 3400, None, _FakeGrid())

    assert data is not None
    assert data.rank_value == 3400
    assert data.used_source == "division_history"
    assert data.ow_rank_value is None


def test_priority_returns_none_when_all_sources_empty() -> None:
    assert reg_admin._build_priority_rank_data(_OW_FIRST, None, None, None, _FakeGrid()) is None
    # OW present but unmapped, no balancer/analytics → still nothing usable.
    assert reg_admin._build_priority_rank_data(_BALANCER_FIRST, _ow_signals(5000), None, None, _FakeGrid()) is None


def test_priority_custom_order_analytics_only_ignores_disabled_sources() -> None:
    # Only analytics in the chain: OW and balancer candidates are present but never considered.
    data = reg_admin._build_priority_rank_data(("analytics",), _ow_signals(3000), 3200, 2800, _FakeGrid())

    assert data is not None
    assert data.rank_value == 2800
    assert data.used_source == "analytics"


def test_priority_custom_order_reordered_prefers_first_in_order() -> None:
    # analytics before division_history → analytics wins even though balancer has a value.
    data = reg_admin._build_priority_rank_data(("analytics", "division_history"), None, 3200, 2800, _FakeGrid())

    assert data is not None
    assert data.rank_value == 2800
    assert data.used_source == "analytics"


def test_priority_empty_order_returns_none() -> None:
    assert reg_admin._build_priority_rank_data((), _ow_signals(3000), 3200, 2800, _FakeGrid()) is None


# ── resolve_autofill_stages: legacy mode presets vs explicit stage chain ─────────────────────


def _stage(source: str, *, enabled: bool = True, lookback_tournaments=None, lookback_days=None):
    return SimpleNamespace(
        source=source,
        enabled=enabled,
        lookback_tournaments=lookback_tournaments,
        lookback_days=lookback_days,
    )


def test_resolve_stages_uses_mode_order_when_no_stages() -> None:
    assert [s.source for s in reg_admin.resolve_autofill_stages("ow_first", None)] == list(_OW_FIRST)
    assert [s.source for s in reg_admin.resolve_autofill_stages("balancer_first", None)] == list(_BALANCER_FIRST)
    # Unknown / None mode → ow_first default.
    assert [s.source for s in reg_admin.resolve_autofill_stages(None, None)] == list(_OW_FIRST)


def test_resolve_stages_explicit_chain_overrides_mode_and_preserves_order() -> None:
    stages = [_stage("analytics", lookback_tournaments=5), _stage("ow", lookback_days=14)]
    resolved = reg_admin.resolve_autofill_stages("ow_first", stages)

    assert [s.source for s in resolved] == ["analytics", "ow"]
    assert resolved[0].lookback_tournaments == 5
    assert resolved[1].lookback_days == 14


def test_resolve_stages_drops_disabled_and_dedupes() -> None:
    stages = [
        _stage("ow"),
        _stage("division_history", enabled=False),
        _stage("ow"),  # duplicate, dropped
        _stage("analytics"),
    ]
    resolved = reg_admin.resolve_autofill_stages("ow_first", stages)

    assert [s.source for s in resolved] == ["ow", "analytics"]


def test_resolve_stages_all_disabled_is_empty() -> None:
    stages = [_stage("ow", enabled=False), _stage("analytics", enabled=False)]
    assert reg_admin.resolve_autofill_stages("ow_first", stages) == []


def test_lookback_cutoff() -> None:
    assert reg_admin._autofill_lookback_cutoff(42, 5) == 37
    assert reg_admin._autofill_lookback_cutoff(None, 5) is None
    assert reg_admin._autofill_lookback_cutoff(42, None) is None


# ── allow_partial + unverified action in the plan builder ────────────────────────────────────


def test_partial_applies_found_role_and_leaves_unparsed_role_untouched() -> None:
    tank = _role("tank", priority=0)  # no current rank, no parsed rank → would otherwise block
    dps = _role("dps", priority=1)  # parsed rank found

    row, updates = reg_admin.build_registration_rank_autofill_plan(
        _registration(tank, dps),
        {"damage": _snapshot(3300)},
        battle_tag_linked=True,
        overwrite_existing=False,
        allow_partial=True,
    )

    assert row["status"] == "will_update"
    assert row["partial"] is True
    assert len(updates) == 1
    assert updates[0][0] is dps
    assert tank.rank_value is None  # unfilled role left untouched
    actions = {role_row["role"]: role_row["action"] for role_row in row["roles"]}
    assert actions == {"tank": "missing_rank", "dps": "set"}


def test_partial_preserves_existing_rank_on_unparsed_role() -> None:
    # Unfound role already has a rank → reported as unverified (kept), never cleared.
    tank = _role("tank", rank_value=3100, priority=0)
    dps = _role("dps", priority=1)  # parsed rank found

    row, updates = reg_admin.build_registration_rank_autofill_plan(
        _registration(tank, dps),
        {"damage": _snapshot(3300)},
        battle_tag_linked=True,
        overwrite_existing=False,
        allow_partial=True,
    )

    assert row["status"] == "will_update"
    assert len(updates) == 1
    assert updates[0][0] is dps
    assert tank.rank_value == 3100  # existing rank untouched, never cleared
    actions = {role_row["role"]: role_row["action"] for role_row in row["roles"]}
    assert actions["tank"] == "unverified"


def test_partial_disabled_skips_whole_registration() -> None:
    tank = _role("tank", priority=0)  # no current rank, no parsed rank
    dps = _role("dps", priority=1)

    row, updates = reg_admin.build_registration_rank_autofill_plan(
        _registration(tank, dps),
        {"damage": _snapshot(3300)},
        battle_tag_linked=True,
        overwrite_existing=False,
        allow_partial=False,
    )

    assert updates == []
    assert row["status"] == "skipped"
    assert row["partial"] is False
    assert [role_row["action"] for role_row in row["roles"]] == ["missing_rank", "blocked"]


def test_unverified_action_when_existing_rank_has_no_source_value() -> None:
    # Current rank set, overwrite off, and no source produced a value for the role → unverified.
    row, updates = reg_admin.build_registration_rank_autofill_plan(
        _registration(_role("support", rank_value=2100)),
        {},
        battle_tag_linked=True,
        overwrite_existing=False,
    )

    assert updates == []
    assert row["status"] == "unchanged"
    assert row["roles"][0]["action"] == "unverified"


def test_keep_existing_action_when_source_value_present() -> None:
    # Same setup but a source value exists → kept (not unverified) because overwrite is off.
    row, _updates = reg_admin.build_registration_rank_autofill_plan(
        _registration(_role("support", rank_value=2100)),
        {"support": _snapshot(2500, role="support")},
        battle_tag_linked=True,
        overwrite_existing=False,
    )

    assert row["roles"][0]["action"] == "keep_existing"


# ── OW weekly composite: round((max + mean) / 2) over a 7-day window ─────────────────────────

_NOW = datetime(2026, 6, 12, tzinfo=UTC)


def _snap(
    rank_value: int | None,
    captured_at: datetime,
    *,
    role: str = "damage",
    tag_id: int = 7,
) -> SimpleNamespace:
    return SimpleNamespace(
        rank_value=rank_value,
        role=role,
        social_account_id=tag_id,
        platform="pc",
        division="master",
        tier=3,
        season=15,
        captured_at=captured_at,
    )


def test_week_composite_is_max_plus_mean_over_two() -> None:
    snaps = [
        _snap(3400, datetime(2026, 6, 11, tzinfo=UTC)),
        _snap(3200, datetime(2026, 6, 9, tzinfo=UTC)),
        _snap(3000, datetime(2026, 6, 7, tzinfo=UTC)),
    ]
    # max=3400, mean=3200 -> (3400 + 3200) / 2 = 3300
    assert reg_admin._compute_ow_week_rank_value(snaps, _NOW) == 3300


def test_week_recent_window_takes_precedence_over_old_peak() -> None:
    snaps = [
        _snap(3000, datetime(2026, 6, 10, tzinfo=UTC)),
        _snap(3400, datetime(2026, 6, 8, tzinfo=UTC)),
        _snap(4000, datetime(2026, 5, 1, tzinfo=UTC)),  # older than a week -> ignored
    ]
    # window [now-7d]: [3000, 3400] -> max 3400, mean 3200 -> 3300
    assert reg_admin._compute_ow_week_rank_value(snaps, _NOW) == 3300


def test_week_falls_back_to_window_around_latest_when_recent_empty() -> None:
    snaps = [
        _snap(3000, datetime(2026, 6, 1, tzinfo=UTC)),  # latest, but >7d before now
        _snap(3200, datetime(2026, 5, 30, tzinfo=UTC)),
        _snap(3100, datetime(2026, 5, 28, tzinfo=UTC)),
    ]
    # No snapshot within 7d of now -> window of 7d around the latest (2026-06-01): all three.
    # max=3200, mean=3100 -> (3200 + 3100) / 2 = 3150
    assert reg_admin._compute_ow_week_rank_value(snaps, _NOW) == 3150


def test_week_single_snapshot_returns_its_value() -> None:
    snaps = [_snap(3333, datetime(2026, 1, 1, tzinfo=UTC))]
    assert reg_admin._compute_ow_week_rank_value(snaps, _NOW) == 3333


def test_week_no_snapshots_returns_none() -> None:
    assert reg_admin._compute_ow_week_rank_value([], _NOW) is None
    assert reg_admin._compute_ow_week_rank_value([_snap(None, _NOW)], _NOW) is None


def test_group_ow_signals_computes_composite_and_latest() -> None:
    snaps = [
        _snap(3400, datetime(2026, 6, 11, tzinfo=UTC)),
        _snap(3200, datetime(2026, 6, 9, tzinfo=UTC)),
    ]
    grouped = reg_admin._group_ow_rank_signals(snaps, _NOW)
    signals = grouped[7]["damage"]

    # max=3400, mean=3300 -> (3400 + 3300) / 2 = 3350
    assert signals.composite_rank_value == 3350
    assert signals.latest_snapshot.rank_value == 3400


# ── Cross-grid rank normalization for history sources ────────────────────────────────────────


def _tier(tier_id: int, number: int, rank_min: int, rank_max: int | None) -> DivisionTier:
    return DivisionTier(
        id=tier_id,
        slug=None,
        number=number,
        name=str(number),
        rank_min=rank_min,
        rank_max=rank_max,
        icon_url="",
    )


def _make_normalizer() -> tuple[DivisionGridNormalizer, DivisionGrid]:
    target_t1 = _tier(10, 1, 1000, 1999)
    target_t2 = _tier(11, 2, 2000, None)
    target_grid = DivisionGrid(version_id=1, tiers=(target_t2, target_t1))
    source_t1 = _tier(20, 1, 100, 199)
    source_t2 = _tier(21, 2, 200, None)
    source_grid = DivisionGrid(version_id=2, tiers=(source_t2, source_t1))
    normalizer = DivisionGridNormalizer(
        target_version_id=1,
        target_grid=target_grid,
        source_grids_by_version_id={2: source_grid},
        primary_target_by_source_tier_id={20: target_t1, 21: target_t2},
        weighted_targets_by_source_tier_id={},
    )
    return normalizer, target_grid


def test_normalize_history_rank_passthrough_without_mapping_inputs() -> None:
    normalizer, target_grid = _make_normalizer()
    # No normalizer / no source version → rank is returned unchanged; None stays None.
    assert reg_admin._normalize_history_rank(None, 2, 150, target_grid) == 150
    assert reg_admin._normalize_history_rank(normalizer, None, 150, target_grid) == 150
    assert reg_admin._normalize_history_rank(normalizer, 2, None, target_grid) is None


def test_normalize_history_rank_maps_via_primary_mapping() -> None:
    normalizer, target_grid = _make_normalizer()
    # source v2 rank 150 → source tier 20 → target tier 10 (rank_min 1000).
    assert reg_admin._normalize_history_rank(normalizer, 2, 150, target_grid) == 1000


def test_normalize_history_rank_falls_back_to_division_number() -> None:
    normalizer, target_grid = _make_normalizer()
    # Drop the primary mapping for source tier 21 → normalize raises → fallback by division
    # number: source tier number 2 → target rank for division 2 = 2000 (open tier rank_min).
    normalizer.primary_target_by_source_tier_id.pop(21)
    assert reg_admin._normalize_history_rank(normalizer, 2, 250, target_grid) == 2000
