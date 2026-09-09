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

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.balancer_registration_statuses import is_balancer_status_excluded
from shared.division_grid import DivisionGrid
from shared.domain.roster import PlayerRoster
from shared.services.roster import roster_engine
from src import models
from src.domain.registration.utils import normalize_battle_tag_key
from src.services.registration._common import (
    RegistrationCommonService,
    _common_service,
    included_balancer_status,
    resolve_roster,
    sync_included_balancer_status,
)
from src.services.registration.rank_sources import (
    OW_RANK_WEEK_WINDOW,
    RANK_ROLE_BY_REGISTRATION_ROLE,
    REGISTRATION_ROLE_LABELS,
    RankSourcesService,
    _build_priority_rank_data,
    _OwRankSignals,
    _RankData,
    rank_sources_service,
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
    roster: PlayerRoster | None,
    battle_tag_linked: bool,
    overwrite_existing: bool,
    allow_partial: bool = False,
    applied: bool = False,
) -> tuple[dict[str, Any], list[tuple[Any, Any]]]:
    """Build the rank autofill preview row and pending role updates.

    The role set is the registration's resolved ``roster`` -- every role the
    tournament has it declaring, in priority order, playable or not. Reading the
    raw ``is_active`` column instead is what used to make autofill skip exactly
    the rows it exists to fill: under a non-optional flex mode all three roles are
    the player's, and a sheet row whose rank did not parse landed inactive.

    Parsed ranks are expected to come from the registration's main battle tag
    only. With ``allow_partial`` the found role ranks are still applied when other
    roles have no parsed rank (instead of skipping the whole registration);
    unfilled roles are left untouched -- an existing rank is never cleared. A role
    that has a current rank no enabled source could corroborate is reported as
    ``unverified`` (informational only).
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

    # The plan WRITES ``registration_role.rank_value``, so a declared role with no
    # row of its own has nothing to write to and is skipped.
    rows_by_role = {getattr(entry, "role", None): entry for entry in getattr(registration, "roles", [])}
    declared_roles = [
        rows_by_role[entry.role.slot_code]
        for entry in (roster.roles if roster is not None else ())
        if entry.role.slot_code in rows_by_role
    ]
    if not declared_roles:
        row["reason"] = "Registration has no active roles."
        return row, []

    if not battle_tag_linked:
        row["reason"] = "Main BattleTag is not linked to an analytics player account."
        return row, []

    updates: list[tuple[Any, Any]] = []
    missing_roles: list[str] = []
    kept_existing = False

    for role_entry in declared_roles:
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


def _roles_ranked_after_updates(
    roster: PlayerRoster | None,
    updates: list[tuple[Any, Any]],
) -> bool:
    """Would every declared role carry a rank once ``updates`` land?

    ``is_playable`` already folds in the inherited layers, so a role whose number
    only exists as the workspace canon counts as ranked here -- which is the point:
    those registrations used to be told they were "missing active role ranks" and
    kept out of the pool.
    """
    if roster is None or not roster.roles:
        return False
    updated_roles = {getattr(role_entry, "role", None) for role_entry, _snapshot in updates}
    return all(entry.is_playable or entry.role.slot_code in updated_roles for entry in roster.roles)


def _rank_autofill_balancer_addition(
    registration: models.BalancerRegistration | Any,
    updates: list[tuple[Any, Any]],
    *,
    add_to_balancer: bool,
    roster: PlayerRoster | None = None,
) -> tuple[bool, str | None]:
    if not add_to_balancer:
        return False, None
    if getattr(registration, "status", None) != "approved":
        return False, "Registration must be approved before it can be added to balancer."
    if not is_balancer_status_excluded(getattr(registration, "balancer_status", None)):
        return False, "Registration is already in balancer."
    if not _roles_ranked_after_updates(roster, updates):
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


class RankAutofillService:
    def __init__(
        self,
        *,
        rank_sources: RankSourcesService = rank_sources_service,
        common: RegistrationCommonService = _common_service,
    ) -> None:
        self.rank_sources = rank_sources
        self.common = common

    async def _autofill_lookback_tournament_ids(
        self, session: AsyncSession, target: models.Tournament, lookback_tournaments: int | None
    ) -> set[int] | None:
        """Ids of the N workspace tournaments immediately preceding ``target``, or None when unrestricted.

        "Preceding" is chronological by ``(start_date, id)`` with NULL start dates sorting last; the N
        most recent of those (``start_date DESC NULLS LAST, id DESC``) form the lookback window.
        """
        if lookback_tournaments is None:
            return None
        if target.start_date is not None:
            before = sa.or_(
                models.Tournament.start_date < target.start_date,
                sa.and_(models.Tournament.start_date == target.start_date, models.Tournament.id < target.id),
            )
        else:
            before = sa.or_(models.Tournament.start_date.is_not(None), models.Tournament.id < target.id)
        stmt = (
            sa.select(models.Tournament.id)
            .where(models.Tournament.workspace_id == target.workspace_id, before)
            .order_by(models.Tournament.start_date.desc().nulls_last(), models.Tournament.id.desc())
            .limit(lookback_tournaments)
        )
        return set((await session.execute(stmt)).scalars().all())

    async def autofill_registration_ranks_from_parsed(
        self,
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
        division_lookback = next(
            (s.lookback_tournaments for s in resolved_stages if s.source == "division_history"), None
        )
        analytics_lookback = next((s.lookback_tournaments for s in resolved_stages if s.source == "analytics"), None)

        now = datetime.now(UTC)
        tournament = await self.rank_sources._load_tournament_for_autofill(session, tournament_id)
        grid = DivisionGrid.from_version(tournament.division_grid_version if tournament else None)
        # Loop-invariant: one autofill run is scoped to one tournament, and every
        # inherited rank layer below is read through its workspace.
        workspace_id = getattr(tournament, "workspace_id", None)

        registrations = await self.rank_sources._load_rank_autofill_registrations(
            session, tournament_id, registration_ids
        )
        battle_tags_by_key = await self.rank_sources._load_main_battle_tags_by_key(session, registrations)
        # One resolve for the whole run: the role SET the plan fills, and the
        # "would this be complete" verdict, both come from these rosters.
        rosters = await roster_engine.resolve(
            session, registrations, workspace_id=workspace_id, tournament_id=tournament_id, grid=grid
        )

        # Only load a source when its stage is enabled (skips its DB query otherwise). A disabled
        # source contributes no candidate, so it can never win the priority chain.
        ow_signals_by_tag_id: dict[int, dict[str, _OwRankSignals]] = {}
        if "ow" in enabled_sources:
            ow_week_window = timedelta(days=ow_lookback_days) if ow_lookback_days else OW_RANK_WEEK_WINDOW
            ow_signals_by_tag_id = await self.rank_sources._load_ow_rank_signals_by_social_account_id(
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
            user_ids = [
                battle_tag.user_id for battle_tag in battle_tags_by_key.values() if battle_tag.user_id is not None
            ]
            # Normalize historical ranks from each source tournament's grid version into this
            # tournament's grid. Best-effort: skip when the target version is unknown or the
            # normalizer cannot be built (loaders then fall back to raw ranks).
            normalizer = await self.rank_sources._build_autofill_rank_normalizer(session, tournament)
            if "division_history" in enabled_sources:
                balancer_history_by_user_id = await self.rank_sources._load_latest_ranks_from_balancer_history(
                    session,
                    user_ids,
                    tournament_id,
                    tournament.workspace_id,
                    normalizer,
                    grid,
                    await self._autofill_lookback_tournament_ids(session, tournament, division_lookback),
                )
            if "analytics" in enabled_sources:
                analytics_history_by_user_id = await self.rank_sources._load_latest_ranks_from_tournament_history(
                    session,
                    user_ids,
                    tournament_id,
                    tournament.workspace_id,
                    normalizer,
                    grid,
                    await self._autofill_lookback_tournament_ids(session, tournament, analytics_lookback),
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

            roster = rosters.get(registration.id)
            row, updates = build_registration_rank_autofill_plan(
                registration,
                rank_data_by_role,
                roster=roster,
                battle_tag_linked=main_battle_tag is not None,
                overwrite_existing=overwrite_existing,
                allow_partial=allow_partial,
                applied=apply,
            )
            will_add_to_balancer, balancer_reason = _rank_autofill_balancer_addition(
                registration,
                updates,
                add_to_balancer=add_to_balancer,
                roster=roster,
            )
            row["will_add_to_balancer"] = will_add_to_balancer
            row["balancer_reason"] = balancer_reason

            changed = False
            if apply and updates:
                # No identity is provisioned here on purpose: autofill writes the
                # registration's own layer, and minting players as a side effect of
                # a rank fill would make a preview-then-apply mutate identity.
                for role_entry, rank_data in updates:
                    value = getattr(rank_data, "rank_value", None)
                    if value is None:
                        continue
                    if overwrite_existing or getattr(role_entry, "rank_value", None) is None:
                        role_entry.rank_value = value
                        # A number nobody can see is not a fill: an inactive row
                        # keeps the role out of every roster, so the write that
                        # gives it a rank is also the write that declares it.
                        role_entry.is_active = True
                role_updates += len(updates)
                applied_registrations += 1
                changed = True
            elif not apply:
                role_updates += len(updates)

            if apply and will_add_to_balancer:
                registration.exclude_reason = None
                # Re-resolved AFTER the writes above: autoflush publishes them, so
                # the verdict is the one the pool will actually see.
                registration.balancer_status = included_balancer_status(await resolve_roster(session, registration))
                balancer_additions += 1
                changed = True
            elif not apply and will_add_to_balancer:
                balancer_additions += 1

            if apply and changed:
                if not will_add_to_balancer:
                    sync_included_balancer_status(registration, await resolve_roster(session, registration))
                await self.common._register_registration_changed(session, registration)

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


rank_autofill_service = RankAutofillService()
