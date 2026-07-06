"""Registration rank autofill: stage chain, plan building and application.

Resolves the configured chain of rank sources (OW weekly composite, balancer
division history, tournament analytics history — see ``rank_sources``), builds
the per-registration preview plan and, on ``apply``, writes the chosen ranks
back and optionally adds ready registrations to the balancer. Everything here
is re-exported by the ``admin`` facade.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from shared.division_grid import DivisionGrid
from src import models
from src.services.registration._common import (
    _active_roles,
    _register_registration_changed,
    included_balancer_status,
    sync_included_balancer_status,
)
from src.services.registration.rank_sources import (
    OW_RANK_WEEK_WINDOW,
    RANK_ROLE_BY_REGISTRATION_ROLE,
    REGISTRATION_ROLE_LABELS,
    _build_autofill_rank_normalizer,
    _build_priority_rank_data,
    _load_latest_ranks_from_balancer_history,
    _load_latest_ranks_from_tournament_history,
    _load_main_battle_tags_by_key,
    _load_ow_rank_signals_by_social_account_id,
    _load_rank_autofill_registrations,
    _load_tournament_for_autofill,
    _OwRankSignals,
    _RankData,
)
from src.services.registration.utils import (
    DEFAULT_SORT_PRIORITY_SENTINEL,
    normalize_battle_tag_key,
)


@dataclass(frozen=True)
class _ResolvedAutofillStage:
    """One enabled source in the resolved autofill chain, with its lookback window.

    ``lookback_tournaments`` applies to the tournament-based sources (``division_history``,
    ``analytics``); ``lookback_days`` overrides the OW weekly window. The irrelevant field for a
    given ``source`` is simply ignored by the orchestrator.
    """

    source: str
    lookback_tournaments: int | None = None
    lookback_days: int | None = None


def _rank_snapshot_payload(snapshot: models.UserRankSnapshot | _RankData | Any | None) -> dict[str, Any]:
    if snapshot is None:
        return {
            "parsed_rank_value": None,
            "platform": None,
            "division": None,
            "tier": None,
            "season": None,
            "captured_at": None,
            "source": "analytics",
            "division_history_rank_value": None,
            "ow_rank_value": None,
            "ow_current_rank_value": None,
            "analytics_rank_value": None,
            "used_source": None,
        }
    return {
        "parsed_rank_value": getattr(snapshot, "rank_value", None),
        "platform": getattr(snapshot, "platform", None),
        "division": getattr(snapshot, "division", None),
        "tier": getattr(snapshot, "tier", None),
        "season": getattr(snapshot, "season", None),
        "captured_at": getattr(snapshot, "captured_at", None),
        "source": getattr(snapshot, "source", "analytics"),
        "division_history_rank_value": getattr(snapshot, "division_history_rank_value", None),
        "ow_rank_value": getattr(snapshot, "ow_rank_value", None),
        "ow_current_rank_value": getattr(snapshot, "ow_current_rank_value", None),
        "analytics_rank_value": getattr(snapshot, "analytics_rank_value", None),
        "used_source": getattr(snapshot, "used_source", None),
    }


def build_registration_rank_autofill_plan(
    registration: models.BalancerRegistration | Any,
    rank_snapshots_by_role: dict[str, models.UserRankSnapshot | Any],
    *,
    battle_tag_linked: bool,
    overwrite_existing: bool,
    allow_partial: bool = False,
    applied: bool = False,
) -> tuple[dict[str, Any], list[tuple[Any, Any]]]:
    """Build the rank autofill preview row and pending role updates.

    Only active registration roles are considered, and parsed ranks are expected to come from the
    registration's main battle tag only. With ``allow_partial`` the found role ranks are still
    applied when other active roles have no parsed rank (instead of skipping the whole registration);
    unfilled roles are left untouched — an existing rank is never cleared. A role that has a current
    rank no enabled source could corroborate is reported as ``unverified`` (informational only).
    """

    display_name = getattr(registration, "display_name", None)
    battle_tag = getattr(registration, "battle_tag", None)
    row = {
        "registration_id": registration.id,
        "display_name": display_name,
        "battle_tag": battle_tag,
        "status": "skipped",
        "reason": None,
        "partial": False,
        "roles": [],
    }

    if not battle_tag:
        row["reason"] = "Registration has no main BattleTag."
        return row, []

    active_roles = sorted(
        _active_roles(registration),
        key=lambda role: (getattr(role, "priority", DEFAULT_SORT_PRIORITY_SENTINEL), getattr(role, "role", "")),
    )
    if not active_roles:
        row["reason"] = "Registration has no active roles."
        return row, []

    if not battle_tag_linked:
        row["reason"] = "Main BattleTag is not linked to an analytics player account."
        return row, []

    updates: list[tuple[Any, Any]] = []
    missing_roles: list[str] = []
    kept_existing = False

    for role_entry in active_roles:
        role_code = getattr(role_entry, "role", None)
        rank_role = RANK_ROLE_BY_REGISTRATION_ROLE.get(role_code)
        snapshot = rank_snapshots_by_role.get(rank_role or "")
        current_rank = getattr(role_entry, "rank_value", None)
        snapshot_payload = _rank_snapshot_payload(snapshot)
        parsed_rank = snapshot_payload["parsed_rank_value"]
        role_row = {
            "role": role_code,
            "current_rank_value": current_rank,
            **snapshot_payload,
            "action": "missing_rank",
            "reason": "No parsed rank for this registered role on the main account.",
        }

        if current_rank is not None and not overwrite_existing:
            kept_existing = True
            if parsed_rank is None:
                role_row["action"] = "unverified"
                role_row["reason"] = "Current rank kept; no enabled source found a value to verify it."
            else:
                role_row["action"] = "keep_existing"
                role_row["reason"] = "Existing registration rank is kept. Enable overwrite to replace it."
        elif parsed_rank is None:
            missing_roles.append(REGISTRATION_ROLE_LABELS.get(role_code, str(role_code)))
        elif current_rank == parsed_rank:
            kept_existing = True
            role_row["action"] = "keep_existing"
            role_row["reason"] = "Parsed rank already matches the registration rank."
        else:
            role_row["action"] = "overwrite" if current_rank is not None else "set"
            role_row["reason"] = None
            updates.append((role_entry, snapshot))

        row["roles"].append(role_row)

    if missing_roles and not allow_partial:
        # All-or-nothing: one unparsed role skips the whole registration and blocks its updates.
        row["reason"] = f"No parsed rank for registered role(s): {', '.join(missing_roles)}."
        for role_row in row["roles"]:
            if role_row["action"] in {"set", "overwrite"}:
                role_row["action"] = "blocked"
                role_row["reason"] = "Player skipped because another registered role has no parsed rank."
        return row, []

    if updates:
        row["status"] = "applied" if applied else "will_update"
        if missing_roles:
            # allow_partial: apply what was found, leave the unparsed roles untouched.
            row["partial"] = True
            row["reason"] = f"Partial: applied found ranks; no parsed rank for {', '.join(missing_roles)}."
        return row, updates

    if missing_roles:
        # allow_partial but nothing to apply (the parsed roles already matched / were kept).
        row["reason"] = f"No parsed rank for registered role(s): {', '.join(missing_roles)}."
        return row, []

    row["status"] = "unchanged"
    row["reason"] = (
        "All active registration ranks are already set."
        if kept_existing and not overwrite_existing
        else "No rank changes needed."
    )
    return row, []


def _active_roles_ranked_after_updates(
    registration: models.BalancerRegistration | Any, updates: list[tuple[Any, Any]]
) -> bool:
    roles = _active_roles(registration)
    if not roles:
        return False
    updated_role_ids = {id(role_entry) for role_entry, _snapshot in updates}
    return all(getattr(role, "rank_value", None) is not None or id(role) in updated_role_ids for role in roles)


def _rank_autofill_balancer_addition(
    registration: models.BalancerRegistration | Any,
    updates: list[tuple[Any, Any]],
    *,
    add_to_balancer: bool,
) -> tuple[bool, str | None]:
    if not add_to_balancer:
        return False, None
    if getattr(registration, "status", None) != "approved":
        return False, "Registration must be approved before it can be added to balancer."
    if not (
        getattr(registration, "exclude_from_balancer", False)
        or getattr(registration, "balancer_status", None) == "not_in_balancer"
    ):
        return False, "Registration is already in balancer."
    if not _active_roles_ranked_after_updates(registration, updates):
        return False, "Registration will still be missing active role ranks."
    return True, None


# Legacy ``mode`` presets, expressed as a default stage order. Used only when no explicit stage
# chain is supplied on the request.
_DEFAULT_STAGE_ORDER_BY_MODE: dict[str, tuple[str, ...]] = {
    "ow_first": ("ow", "division_history", "analytics"),
    "balancer_first": ("division_history", "analytics", "ow"),
}


def resolve_autofill_stages(
    mode: str | None,
    stages: Sequence[Any] | None,
) -> list[_ResolvedAutofillStage]:
    """Resolve the effective, ordered list of enabled autofill stages.

    When ``stages`` is non-empty it wins: disabled entries are dropped and duplicate sources are
    de-duplicated (first occurrence kept), preserving order. Otherwise the legacy ``mode`` preset
    order is used, with no lookback windows. ``stages`` items are duck-typed (``source``,
    ``enabled``, ``lookback_tournaments``, ``lookback_days``) so unit tests can pass simple objects.
    """
    if stages:
        resolved: list[_ResolvedAutofillStage] = []
        seen: set[str] = set()
        for stage in stages:
            if not getattr(stage, "enabled", True):
                continue
            source = getattr(stage, "source", None)
            if source is None or source in seen:
                continue
            seen.add(source)
            resolved.append(
                _ResolvedAutofillStage(
                    source=source,
                    lookback_tournaments=getattr(stage, "lookback_tournaments", None),
                    lookback_days=getattr(stage, "lookback_days", None),
                )
            )
        return resolved

    order = _DEFAULT_STAGE_ORDER_BY_MODE.get(mode or "ow_first", _DEFAULT_STAGE_ORDER_BY_MODE["ow_first"])
    return [_ResolvedAutofillStage(source=source) for source in order]


def _autofill_lookback_cutoff(target_number: int | None, lookback_tournaments: int | None) -> int | None:
    """Min ``Tournament.number`` for a "last N tournaments" window, or None when not applicable.

    Returns ``target_number - lookback_tournaments`` so that tournaments numbered
    ``[target - N, target)`` (the N immediately preceding the current one, which is excluded
    elsewhere) qualify. ``None`` when no window is requested or the current tournament has no number.
    """
    if lookback_tournaments is None or target_number is None:
        return None
    return target_number - lookback_tournaments


async def autofill_registration_ranks_from_parsed(
    session: AsyncSession,
    tournament_id: int,
    *,
    registration_ids: list[int] | None = None,
    overwrite_existing: bool = False,
    add_to_balancer: bool = False,
    allow_partial: bool = False,
    mode: str = "ow_first",
    stages: Sequence[Any] | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    if registration_ids is not None:
        registration_ids = list(dict.fromkeys(int(registration_id) for registration_id in registration_ids))

    # Resolve the effective, ordered chain of enabled sources (explicit ``stages`` win over ``mode``).
    resolved_stages = resolve_autofill_stages(mode, stages)
    order = tuple(stage.source for stage in resolved_stages)
    enabled_sources = set(order)
    ow_lookback_days = next((s.lookback_days for s in resolved_stages if s.source == "ow"), None)
    division_lookback = next((s.lookback_tournaments for s in resolved_stages if s.source == "division_history"), None)
    analytics_lookback = next((s.lookback_tournaments for s in resolved_stages if s.source == "analytics"), None)

    now = datetime.now(UTC)
    tournament = await _load_tournament_for_autofill(session, tournament_id)
    grid = DivisionGrid.from_version(tournament.division_grid_version if tournament else None)
    target_number = getattr(tournament, "number", None) if tournament is not None else None

    registrations = await _load_rank_autofill_registrations(session, tournament_id, registration_ids)
    battle_tags_by_key = await _load_main_battle_tags_by_key(session, registrations)

    # Only load a source when its stage is enabled (skips its DB query otherwise). A disabled
    # source contributes no candidate, so it can never win the priority chain.
    ow_signals_by_tag_id: dict[int, dict[str, _OwRankSignals]] = {}
    if "ow" in enabled_sources:
        ow_week_window = timedelta(days=ow_lookback_days) if ow_lookback_days else OW_RANK_WEEK_WINDOW
        ow_signals_by_tag_id = await _load_ow_rank_signals_by_social_account_id(
            session,
            [account.id for account in battle_tags_by_key.values()],
            now,
            ow_week_window,
        )

    # Balancer history (division_history) and tournament-participation history (analytics) are
    # both candidates in the priority chain, keyed by user_id then registration role code.
    balancer_history_by_user_id: dict[int, dict[str, int]] = {}
    analytics_history_by_user_id: dict[int, dict[str, int]] = {}
    if tournament is not None and ({"division_history", "analytics"} & enabled_sources):
        user_ids = [battle_tag.user_id for battle_tag in battle_tags_by_key.values() if battle_tag.user_id is not None]
        # Normalize historical ranks from each source tournament's grid version into this
        # tournament's grid. Best-effort: skip when the target version is unknown or the
        # normalizer cannot be built (loaders then fall back to raw ranks).
        normalizer = await _build_autofill_rank_normalizer(session, tournament)
        if "division_history" in enabled_sources:
            balancer_history_by_user_id = await _load_latest_ranks_from_balancer_history(
                session,
                user_ids,
                tournament_id,
                tournament.workspace_id,
                normalizer,
                grid,
                _autofill_lookback_cutoff(target_number, division_lookback),
            )
        if "analytics" in enabled_sources:
            analytics_history_by_user_id = await _load_latest_ranks_from_tournament_history(
                session,
                user_ids,
                tournament_id,
                tournament.workspace_id,
                normalizer,
                grid,
                _autofill_lookback_cutoff(target_number, analytics_lookback),
            )

    players: list[dict[str, Any]] = []
    applied_registrations = 0
    role_updates = 0
    balancer_additions = 0

    for registration in registrations:
        tag_key = registration.battle_tag_normalized or normalize_battle_tag_key(registration.battle_tag)
        main_battle_tag = battle_tags_by_key.get(tag_key or "")
        ow_signals_by_role = ow_signals_by_tag_id.get(main_battle_tag.id, {}) if main_battle_tag else {}
        user_id = getattr(main_battle_tag, "user_id", None) if main_battle_tag else None
        balancer_by_role = balancer_history_by_user_id.get(user_id or -1, {})
        analytics_by_role = analytics_history_by_user_id.get(user_id or -1, {})

        # Build one suggestion per rank-role via the selected priority chain, keyed the way the
        # plan builder expects. Balancer/analytics history are stored under registration-role codes
        # (tank/dps/support); OW snapshots use rank-role codes (tank/damage/support) — bridge via
        # the mapping.
        rank_data_by_role: dict[str, _RankData | Any] = {}
        for registration_role, rank_role in RANK_ROLE_BY_REGISTRATION_ROLE.items():
            resolved = _build_priority_rank_data(
                order,
                ow_signals_by_role.get(rank_role),
                balancer_by_role.get(registration_role),
                analytics_by_role.get(registration_role),
                grid,
            )
            if resolved is not None:
                rank_data_by_role[rank_role] = resolved

        row, updates = build_registration_rank_autofill_plan(
            registration,
            rank_data_by_role,
            battle_tag_linked=main_battle_tag is not None,
            overwrite_existing=overwrite_existing,
            allow_partial=allow_partial,
            applied=apply,
        )
        will_add_to_balancer, balancer_reason = _rank_autofill_balancer_addition(
            registration,
            updates,
            add_to_balancer=add_to_balancer,
        )
        row["will_add_to_balancer"] = will_add_to_balancer
        row["balancer_reason"] = balancer_reason

        changed = False
        if apply and updates:
            for role_entry, rank_data in updates:
                role_entry.rank_value = getattr(rank_data, "rank_value", None)
                role_updates += 1
            registration.balancer_profile_overridden_at = now
            applied_registrations += 1
            changed = True
        elif not apply:
            role_updates += len(updates)

        if apply and will_add_to_balancer:
            registration.exclude_from_balancer = False
            registration.exclude_reason = None
            registration.balancer_status = included_balancer_status(registration)
            balancer_additions += 1
            changed = True
        elif not apply and will_add_to_balancer:
            balancer_additions += 1

        if apply and changed:
            if not will_add_to_balancer:
                sync_included_balancer_status(registration)
            _register_registration_changed(session, registration)

        players.append(row)

    if apply and (applied_registrations > 0 or balancer_additions > 0):
        await session.commit()

    updatable_registrations = sum(1 for row in players if row["status"] in {"will_update", "applied"})
    skipped_registrations = sum(1 for row in players if row["status"] == "skipped")
    unchanged_registrations = sum(1 for row in players if row["status"] == "unchanged")
    unverified_registrations = sum(
        1 for row in players if any(role.get("action") == "unverified" for role in row["roles"])
    )

    return {
        "total_registrations": len(players),
        "updatable_registrations": updatable_registrations,
        "applied_registrations": applied_registrations,
        "skipped_registrations": skipped_registrations,
        "unchanged_registrations": unchanged_registrations,
        "unverified_registrations": unverified_registrations,
        "role_updates": role_updates,
        "overwrite_existing": overwrite_existing,
        "add_to_balancer": add_to_balancer,
        "balancer_additions": balancer_additions,
        "players": players,
    }
