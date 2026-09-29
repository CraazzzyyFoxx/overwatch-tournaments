"""Unit tests for registration rank autofill planning."""

from __future__ import annotations

import asyncio
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

models = importlib.import_module("src.models")
rank_autofill = importlib.import_module("src.services.registration.rank_autofill")
rank_sources = importlib.import_module("src.services.registration.rank_sources")

from shared.core.enums import HeroClass  # noqa: E402
from shared.division_grid import DivisionGrid, DivisionTier  # noqa: E402
from shared.domain.roster import PlayerRoster, RosterRole  # noqa: E402
from shared.services.division_grid.normalization import DivisionGridNormalizer  # noqa: E402
from shared.testing.factories import division_tier  # noqa: E402


def test_rank_snapshot_model_is_available_from_service_models() -> None:
    assert hasattr(models, "UserRankSnapshot")


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


def _roster_for(registration: SimpleNamespace) -> PlayerRoster:
    """The engine's roster for these rows: registration layer only, in priority
    order, over every role the registration declares."""
    return PlayerRoster(
        registration_id=registration.id,
        battle_tag=registration.battle_tag,
        display_name=registration.display_name,
        player_id=None,
        auth_user_id=None,
        workspace_member_id=None,
        roles=tuple(
            RosterRole(
                role=HeroClass.from_slot_code(role.role),
                rank=role.rank_value,
                source="registration" if role.rank_value is not None else "none",
                is_primary=priority == 0,
                priority=priority,
                subrole=None,
            )
            for priority, role in enumerate(sorted(registration.roles, key=lambda role: role.priority))
            if role.is_active
        ),
        is_full_flex=False,
    )


def _plan(registration: SimpleNamespace, snapshots: dict, **kwargs):
    return rank_autofill.build_registration_rank_autofill_plan(
        registration, snapshots, roster=_roster_for(registration), **kwargs
    )


def _balancer_addition(registration: SimpleNamespace, updates: list, **kwargs):
    return rank_autofill._rank_autofill_balancer_addition(
        registration, updates, roster=_roster_for(registration), **kwargs
    )


def test_autofill_keeps_existing_rank_without_overwrite() -> None:
    row, updates = _plan(
        _registration(_role("damage", 2500)),
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

    row, updates = _plan(
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
    damage = _role("damage", priority=1)

    row, updates = _plan(
        _registration(tank, damage),
        {"tank": _snapshot(3100, role="tank"), "damage": _snapshot(3300)},
        battle_tag_linked=True,
        overwrite_existing=False,
    )

    assert row["status"] == "will_update"
    assert [role_row["action"] for role_row in row["roles"]] == ["set", "set"]
    assert [snapshot.rank_value for _, snapshot in updates] == [3100, 3300]


def test_autofill_skips_player_when_registered_role_has_no_parsed_rank() -> None:
    row, updates = _plan(
        _registration(_role("damage", priority=0), _role("support", priority=1)),
        {"damage": _snapshot(3300)},
        battle_tag_linked=True,
        overwrite_existing=False,
    )

    assert updates == []
    assert row["status"] == "skipped"
    assert row["reason"] == "No parsed rank for registered role(s): Support."
    assert [role_row["action"] for role_row in row["roles"]] == ["blocked", "missing_rank"]


def test_autofill_skips_unlinked_main_battle_tag() -> None:
    row, updates = _plan(
        _registration(_role("damage")),
        {"damage": _snapshot(3300)},
        battle_tag_linked=False,
        overwrite_existing=False,
    )

    assert updates == []
    assert row["status"] == "skipped"
    assert row["reason"] == "Main BattleTag is not linked to an analytics player account."


def test_autofill_can_add_player_to_balancer_after_rank_update() -> None:
    damage = _role("damage")
    registration = _registration(damage)
    row, updates = _plan(
        registration,
        {"damage": _snapshot(3300)},
        battle_tag_linked=True,
        overwrite_existing=False,
    )

    will_add, reason = _balancer_addition(
        registration,
        updates,
        add_to_balancer=True,
    )

    assert row["status"] == "will_update"
    assert will_add is True
    assert reason is None


def test_autofill_can_add_unchanged_ranked_player_to_balancer() -> None:
    registration = _registration(_role("support", rank_value=3600))
    _row, updates = _plan(
        registration,
        {"support": _snapshot(3600, role="support")},
        battle_tag_linked=True,
        overwrite_existing=False,
    )

    will_add, reason = _balancer_addition(
        registration,
        updates,
        add_to_balancer=True,
    )

    assert will_add is True
    assert reason is None


def test_autofill_does_not_add_unapproved_player_to_balancer() -> None:
    registration = _registration(_role("support", rank_value=3600))
    registration.status = "pending"

    will_add, reason = _balancer_addition(
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


def _ow_signals(composite: int | None, *, latest_rank: int | None = None, peak: int | None = None) -> SimpleNamespace:
    """OW signal whose weekly composite is already resolved to ``composite`` (pre-grid rank_value)."""
    latest_value = latest_rank if latest_rank is not None else composite
    latest = _snapshot(latest_value) if latest_value is not None else None
    return rank_sources._OwRankSignals(composite_rank_value=composite, peak_rank_value=peak, latest_snapshot=latest)


# Ordered source chains (what ``resolve_autofill_stages`` produces for the legacy presets).
_OW_FIRST = ("ow", "division_history", "analytics")
_BALANCER_FIRST = ("division_history", "analytics", "ow")


def test_priority_ow_first_prefers_ow() -> None:
    # User-confirmed example: OW=3000, balancer=3200, analytics=2800 -> ow_first picks OW.
    data = rank_sources._build_priority_rank_data(_OW_FIRST, _ow_signals(3000), 3200, 2800, _FakeGrid())

    assert data is not None
    assert data.rank_value == 3000
    assert data.used_source == "ow"
    assert data.source == "analytics"
    assert data.ow_rank_value == 3000
    assert data.division_history_rank_value == 3200
    assert data.analytics_rank_value == 2800


def test_priority_balancer_first_prefers_balancer() -> None:
    data = rank_sources._build_priority_rank_data(_BALANCER_FIRST, _ow_signals(3000), 3200, 2800, _FakeGrid())

    assert data is not None
    assert data.rank_value == 3200
    assert data.used_source == "division_history"
    assert data.source == "balancer"


def test_priority_ow_first_falls_back_to_balancer() -> None:
    data = rank_sources._build_priority_rank_data(_OW_FIRST, None, 3200, 2800, _FakeGrid())

    assert data is not None
    assert data.rank_value == 3200
    assert data.used_source == "division_history"


def test_priority_ow_first_falls_back_to_analytics() -> None:
    data = rank_sources._build_priority_rank_data(_OW_FIRST, None, None, 2800, _FakeGrid())

    assert data is not None
    assert data.rank_value == 2800
    assert data.used_source == "analytics"


def test_priority_balancer_first_prefers_analytics_over_ow() -> None:
    data = rank_sources._build_priority_rank_data(_BALANCER_FIRST, _ow_signals(3000), None, 2800, _FakeGrid())

    assert data is not None
    assert data.rank_value == 2800
    assert data.used_source == "analytics"


def test_priority_balancer_first_falls_back_to_ow_last() -> None:
    data = rank_sources._build_priority_rank_data(_BALANCER_FIRST, _ow_signals(3000), None, None, _FakeGrid())

    assert data is not None
    assert data.rank_value == 3000
    assert data.used_source == "ow"


def test_priority_unmapped_ow_is_skipped() -> None:
    data = rank_sources._build_priority_rank_data(_OW_FIRST, _ow_signals(5000), 3400, None, _FakeGrid())

    assert data is not None
    assert data.rank_value == 3400
    assert data.used_source == "division_history"
    assert data.ow_rank_value is None


def test_priority_returns_none_when_all_sources_empty() -> None:
    assert rank_sources._build_priority_rank_data(_OW_FIRST, None, None, None, _FakeGrid()) is None
    # OW present but unmapped, no balancer/analytics → still nothing usable.
    assert rank_sources._build_priority_rank_data(_BALANCER_FIRST, _ow_signals(5000), None, None, _FakeGrid()) is None


def test_priority_custom_order_analytics_only_ignores_disabled_sources() -> None:
    # Only analytics in the chain: OW and balancer candidates are present but never considered.
    data = rank_sources._build_priority_rank_data(("analytics",), _ow_signals(3000), 3200, 2800, _FakeGrid())

    assert data is not None
    assert data.rank_value == 2800
    assert data.used_source == "analytics"


def test_priority_custom_order_reordered_prefers_first_in_order() -> None:
    # analytics before division_history → analytics wins even though balancer has a value.
    data = rank_sources._build_priority_rank_data(("analytics", "division_history"), None, 3200, 2800, _FakeGrid())

    assert data is not None
    assert data.rank_value == 2800
    assert data.used_source == "analytics"


def test_priority_empty_order_returns_none() -> None:
    assert rank_sources._build_priority_rank_data((), _ow_signals(3000), 3200, 2800, _FakeGrid()) is None


def test_priority_ow_value_picks_the_number_that_stands_for_ow() -> None:
    signals = _ow_signals(3000, latest_rank=3200, peak=3400)
    picked = {
        ow_value: rank_sources._build_priority_rank_data(_OW_FIRST, signals, 2000, None, _FakeGrid(), ow_value)
        for ow_value in ("composite", "current", "peak")
    }

    assert {ow_value: data.rank_value for ow_value, data in picked.items()} == {
        "composite": 3000,
        "current": 3200,
        "peak": 3400,
    }
    # Whichever one is offered, the breakdown still shows all three.
    peak = picked["peak"]
    assert (peak.ow_rank_value, peak.ow_current_rank_value, peak.ow_peak_rank_value) == (3000, 3200, 3400)


# ── resolve_autofill_stages: legacy mode presets vs explicit stage chain ─────────────────────


def _stage(source: str, *, enabled: bool = True, lookback_tournaments=None, lookback_days=None, ow_value="composite"):
    return SimpleNamespace(
        source=source,
        enabled=enabled,
        lookback_tournaments=lookback_tournaments,
        lookback_days=lookback_days,
        ow_value=ow_value,
    )


def test_resolve_stages_uses_mode_order_when_no_stages() -> None:
    assert [s.source for s in rank_autofill.resolve_autofill_stages("ow_first", None)] == list(_OW_FIRST)
    assert [s.source for s in rank_autofill.resolve_autofill_stages("balancer_first", None)] == list(_BALANCER_FIRST)
    # Unknown / None mode → ow_first default.
    assert [s.source for s in rank_autofill.resolve_autofill_stages(None, None)] == list(_OW_FIRST)


def test_resolve_stages_explicit_chain_overrides_mode_and_preserves_order() -> None:
    stages = [_stage("analytics", lookback_tournaments=5), _stage("ow", lookback_days=14, ow_value="peak")]
    resolved = rank_autofill.resolve_autofill_stages("ow_first", stages)

    assert [s.source for s in resolved] == ["analytics", "ow"]
    assert resolved[0].lookback_tournaments == 5
    assert resolved[1].lookback_days == 14
    assert resolved[1].ow_value == "peak"


def test_resolve_stages_drops_disabled_and_dedupes() -> None:
    stages = [
        _stage("ow"),
        _stage("division_history", enabled=False),
        _stage("ow"),  # duplicate, dropped
        _stage("analytics"),
    ]
    resolved = rank_autofill.resolve_autofill_stages("ow_first", stages)

    assert [s.source for s in resolved] == ["ow", "analytics"]


def test_resolve_stages_all_disabled_is_empty() -> None:
    stages = [_stage("ow", enabled=False), _stage("analytics", enabled=False)]
    assert rank_autofill.resolve_autofill_stages("ow_first", stages) == []


def test_lookback_ids_none_when_unrestricted() -> None:
    target = SimpleNamespace(id=5, start_date=None, workspace_id=1)
    assert (
        asyncio.run(rank_autofill.rank_autofill_service._autofill_lookback_tournament_ids(None, target, None)) is None
    )


def test_lookback_ids_returns_queried_id_set() -> None:
    class _Session:
        async def execute(self, stmt):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [3, 2]))

    target = SimpleNamespace(id=5, start_date=datetime(2024, 1, 1, tzinfo=UTC).date(), workspace_id=1)
    assert asyncio.run(
        rank_autofill.rank_autofill_service._autofill_lookback_tournament_ids(_Session(), target, 2)
    ) == {3, 2}


# ── allow_partial + unverified action in the plan builder ────────────────────────────────────


def test_partial_applies_found_role_and_leaves_unparsed_role_untouched() -> None:
    tank = _role("tank", priority=0)  # no current rank, no parsed rank → would otherwise block
    damage = _role("damage", priority=1)  # parsed rank found

    row, updates = _plan(
        _registration(tank, damage),
        {"damage": _snapshot(3300)},
        battle_tag_linked=True,
        overwrite_existing=False,
        allow_partial=True,
    )

    assert row["status"] == "will_update"
    assert row["partial"] is True
    assert len(updates) == 1
    assert updates[0][0] is damage
    assert tank.rank_value is None  # unfilled role left untouched
    actions = {role_row["role"]: role_row["action"] for role_row in row["roles"]}
    assert actions == {"tank": "missing_rank", "damage": "set"}


def test_partial_preserves_existing_rank_on_unparsed_role() -> None:
    # Unfound role already has a rank → reported as unverified (kept), never cleared.
    tank = _role("tank", rank_value=3100, priority=0)
    damage = _role("damage", priority=1)  # parsed rank found

    row, updates = _plan(
        _registration(tank, damage),
        {"damage": _snapshot(3300)},
        battle_tag_linked=True,
        overwrite_existing=False,
        allow_partial=True,
    )

    assert row["status"] == "will_update"
    assert len(updates) == 1
    assert updates[0][0] is damage
    assert tank.rank_value == 3100  # existing rank untouched, never cleared
    actions = {role_row["role"]: role_row["action"] for role_row in row["roles"]}
    assert actions["tank"] == "unverified"


def test_partial_disabled_skips_whole_registration() -> None:
    tank = _role("tank", priority=0)  # no current rank, no parsed rank
    damage = _role("damage", priority=1)

    row, updates = _plan(
        _registration(tank, damage),
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
    row, updates = _plan(
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
    row, _updates = _plan(
        _registration(_role("support", rank_value=2100)),
        {"support": _snapshot(2500, role="support")},
        battle_tag_linked=True,
        overwrite_existing=False,
    )

    assert row["roles"][0]["action"] == "keep_existing"


# ── OW weekly composite: round((max + mean) / 2), mean weighted by how long each rank held ──

_NOW = datetime(2026, 6, 12, tzinfo=UTC)


def _snap(
    rank_value: int | None,
    captured_at: datetime,
    *,
    role: str = "damage",
    tag_id: int = 7,
    platform: str = "pc",
) -> SimpleNamespace:
    return SimpleNamespace(
        rank_value=rank_value,
        is_ranked=rank_value is not None,
        role=role,
        social_account_id=tag_id,
        platform=platform,
        division="master",
        tier=3,
        season=15,
        captured_at=captured_at,
    )


def _day(day: int, month: int = 6) -> datetime:
    return datetime(2026, month, day, tzinfo=UTC)


def test_week_rank_that_held_all_week_is_that_rank() -> None:
    # Climbed a month ago and stayed: the week says 3600, not the climb that led there.
    snaps = [_snap(3000, _day(1, 5)), _snap(3200, _day(3, 5)), _snap(3600, _day(5, 5))]
    assert rank_sources._compute_ow_week_ranks(snaps, _NOW, _NOW) == (3600, 3600)


def test_week_mean_is_weighted_by_how_long_each_rank_held() -> None:
    # 3000 from before the window to 6/11 (6 of its 7 days), then 3400 for the last day.
    snaps = [_snap(3000, _day(1)), _snap(3400, _day(11))]
    # mean = (3000*6 + 3400*1) / 7 = 3057.14, max 3400 -> 3228.57
    assert rank_sources._compute_ow_week_ranks(snaps, _NOW, _NOW) == (3229, 3400)


def test_week_peak_is_the_highest_rank_seen_inside_the_window() -> None:
    # 4000 was a month ago; this week 3000 (4 days), 3400 (1 day), 3200 (2 days).
    snaps = [_snap(4000, _day(1, 5)), _snap(3000, _day(1)), _snap(3400, _day(9)), _snap(3200, _day(10))]
    # mean = (3000*4 + 3400 + 3200*2) / 7 = 3114.29, max 3400 -> 3257.14
    assert rank_sources._compute_ow_week_ranks(snaps, _NOW, _NOW) == (3257, 3400)


def test_week_unranked_row_ends_the_ranked_stretch() -> None:
    snaps = [_snap(3200, _day(1, 5)), _snap(None, _day(9))]
    assert rank_sources._compute_ow_week_ranks(snaps, _NOW, _NOW) == (3200, 3200)


def test_week_ends_at_the_last_poll_when_the_account_went_stale() -> None:
    # Last polled 5/28, before this week: the window is the week up to that poll.
    snaps = [_snap(3000, _day(20, 5)), _snap(3400, _day(25, 5))]
    # window [5/21, 5/28]: 3000 for 4 days, 3400 for 3 -> mean 3171.43, max 3400 -> 3285.71
    assert rank_sources._compute_ow_week_ranks(snaps, _NOW, _day(28, 5)) == (3286, 3400)


def test_week_platforms_hold_their_ranks_side_by_side() -> None:
    snaps = [_snap(3000, _day(1, 5)), _snap(3600, _day(2, 5), platform="console")]
    # Both hold the whole week: mean 3300, max 3600 -> 3450.
    assert rank_sources._compute_ow_week_ranks(snaps, _NOW, _NOW) == (3450, 3600)


def test_week_rank_observed_on_this_poll_counts() -> None:
    assert rank_sources._compute_ow_week_ranks([_snap(3333, _NOW)], _NOW, _NOW) == (3333, 3333)


def test_week_no_ranked_snapshots_returns_none() -> None:
    assert rank_sources._compute_ow_week_ranks([], _NOW) == (None, None)
    assert rank_sources._compute_ow_week_ranks([_snap(None, _NOW)], _NOW, _NOW) == (None, None)


def test_group_ow_signals_computes_composite_peak_and_latest_ranked() -> None:
    snaps = [_snap(None, _day(11)), _snap(3400, _day(9)), _snap(3200, _day(1))]
    grouped = rank_sources._group_ow_rank_signals(snaps, _NOW, {7: _NOW})
    signals = grouped[7]["damage"]

    # 3200 for 4 days (6/5-6/9), 3400 for 2 (6/9-6/11) -> mean 3266.67, max 3400 -> 3333.33
    assert signals.composite_rank_value == 3333
    assert signals.peak_rank_value == 3400
    assert signals.latest_snapshot.rank_value == 3400


# ── Cross-grid rank normalization for history sources ────────────────────────────────────────


def _tier(tier_id: int, number: int, rank_min: int, rank_max: int | None) -> DivisionTier:
    return division_tier(tier_id, number, rank_min, rank_max, slug=None, name=str(number))


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
    assert rank_sources._normalize_history_rank(None, 2, 150, target_grid) == 150
    assert rank_sources._normalize_history_rank(normalizer, None, 150, target_grid) == 150
    assert rank_sources._normalize_history_rank(normalizer, 2, None, target_grid) is None


def test_normalize_history_rank_maps_via_primary_mapping() -> None:
    normalizer, target_grid = _make_normalizer()
    # source v2 rank 150 → source tier 20 → target tier 10 (rank_min 1000).
    assert rank_sources._normalize_history_rank(normalizer, 2, 150, target_grid) == 1000


def test_normalize_history_rank_falls_back_to_division_number() -> None:
    normalizer, target_grid = _make_normalizer()
    # Drop the primary mapping for source tier 21 → normalize raises → fallback by division
    # number: source tier number 2 → target rank for division 2 = 2000 (open tier rank_min).
    normalizer.primary_target_by_source_tier_id.pop(21)
    assert rank_sources._normalize_history_rank(normalizer, 2, 250, target_grid) == 2000
