"""Registration rank autofill: stage chain, plan building and application.

Resolves the configured chain of rank sources (OW weekly composite, balancer
division history, tournament analytics history — see ``rank_sources``), builds
the per-registration preview plan and, on ``apply``, writes the chosen ranks
back and optionally adds ready registrations to the balancer.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.social import SocialProvider
from shared.disciplines import discipline
from shared.domain.roster import PlayerRoster
from shared.registration_statuses import is_balancer_status_excluded
from shared.schemas.identity import PlayerIdentityRead
from shared.services.roster import roster_engine
from src.services.registration._common import (
    RegistrationCommonService,
    _common_service,
    included_balancer_status,
    sync_included_balancer_status,
)
from src.services.registration.rank_sources import (
    OW_RANK_WEEK_WINDOW,
    RankSourcesService,
    _build_priority_rank_data,
    _OwRankSignals,
    _RankData,
    primary_identity_key,
    rank_sources_service,
)


@dataclass(frozen=True)
class _ResolvedAutofillStage:
    """One enabled source in the resolved autofill chain, with its lookback window.

    ``lookback_tournaments`` applies to the tournament-based sources (``division_history``,
    ``analytics``); ``lookback_days`` overrides the OW weekly window and ``ow_value`` picks the
    OW number. The irrelevant fields for a given ``source`` are simply ignored by the orchestrator.
    """

    source: str
    lookback_tournaments: int | None = None
    lookback_days: int | None = None
    ow_value: str = "composite"


def autofill_sources(enabled: set[str], discipline_code: str | None) -> set[str]:
    """The enabled stages a tournament of ``discipline_code`` can draw on: the ``ow`` stage is the game's native layer
    — OverFast for a Battle.net game, the module's ``native_ranks`` otherwise — so a game whose module declares none
    never gets it."""
    if discipline_code is None or discipline(discipline_code).native_ranks is None:
        return enabled - {"ow"}
    return enabled


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
            "ow_peak_rank_value": None,
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
        "ow_peak_rank_value": getattr(snapshot, "ow_peak_rank_value", None),
        "analytics_rank_value": getattr(snapshot, "analytics_rank_value", None),
        "used_source": getattr(snapshot, "used_source", None),
    }


def build_registration_rank_autofill_plan(
    registration: models.Registration | Any,
    rank_snapshots_by_role: dict[str, models.UserRankSnapshot | Any],
    *,
    roster: PlayerRoster | None,
    provider: str | None,
    identity_linked: bool,
    overwrite_existing: bool,
    allow_partial: bool = False,
    applied: bool = False,
) -> tuple[dict[str, Any], list[tuple[Any, Any]]]:
    """Build the rank autofill preview row and pending role updates.

    The role set is the registration's resolved ``roster`` -- every role the
    tournament has it declaring, in priority order, playable or not -- not the raw
    ``is_active`` column: under a non-optional flex mode all three roles are the
    player's, and a sheet row whose rank did not parse lands inactive, so
    ``is_active`` would skip exactly the rows autofill exists to fill.

    Parsed ranks are expected to come from the registration's main owner-provider handle
    only. With ``allow_partial`` the found role ranks are still applied when other
    roles have no parsed rank (instead of skipping the whole registration);
    unfilled roles are left untouched -- an existing rank is never cleared. A role
    that has a current rank no enabled source could corroborate is reported as
    ``unverified`` (informational only).
    """

    display_name = getattr(registration, "display_name", None)
    handle = registration.primary_handle(provider) if provider is not None else None
    identity = PlayerIdentityRead.of(provider, handle)
    row = {
        "registration_id": registration.id,
        "display_name": display_name,
        "identity": identity.model_dump() if identity is not None else None,
        "status": "skipped",
        "reason": None,
        "partial": False,
        "roles": [],
    }

    if identity is None:
        row["reason"] = "Registration has no primary game identity."
        return row, []

    # The plan WRITES ``registration_role.rank_value``, so a declared role with no
    # row of its own has nothing to write to and is skipped.
    rows_by_role = {getattr(entry, "role", None): entry for entry in getattr(registration, "roles", [])}
    declared_roles = [
        rows_by_role[entry.role] for entry in (roster.roles if roster is not None else ()) if entry.role in rows_by_role
    ]
    if not declared_roles:
        row["reason"] = "Registration has no active roles."
        return row, []

    if not identity_linked:
        row["reason"] = "Primary game identity is not linked to a player account."
        return row, []

    updates: list[tuple[Any, Any]] = []
    missing_roles: list[str] = []
    kept_existing = False

    for role_entry in declared_roles:
        role_code = getattr(role_entry, "role", None)
        snapshot = rank_snapshots_by_role.get(role_code)
        current_rank = getattr(role_entry, "rank_value", None)
        snapshot_payload = _rank_snapshot_payload(snapshot)
        parsed_rank = snapshot_payload["parsed_rank_value"]
        role_row = {
            "role": role_entry.role_ref.model_dump(),
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
            missing_roles.append(role_entry.catalog_role.name)
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
    only exists as the workspace canon counts as ranked here: such a registration
    must not be reported as missing role ranks and kept out of the pool.
    """
    if roster is None or not roster.roles:
        return False
    updated_roles = {getattr(role_entry, "role", None) for role_entry, _snapshot in updates}
    return all(entry.is_playable or entry.role in updated_roles for entry in roster.roles)


def _rank_autofill_balancer_addition(
    registration: models.Registration | Any,
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


# ``mode`` presets, expressed as a default stage order. Used only when no explicit stage
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
    de-duplicated (first occurrence kept), preserving order. Otherwise the ``mode`` preset
    order is used, with no lookback windows. ``stages`` items are duck-typed (``source``,
    ``enabled``, ``lookback_tournaments``, ``lookback_days``, ``ow_value``) so unit tests can pass
    simple objects.
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
                    ow_value=getattr(stage, "ow_value", "composite"),
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

        resolved_stages = resolve_autofill_stages(mode, stages)
        order = tuple(stage.source for stage in resolved_stages)
        enabled_sources = set(order)
        ow_stage = next((s for s in resolved_stages if s.source == "ow"), None)
        ow_lookback_days = ow_stage.lookback_days if ow_stage else None
        ow_value = ow_stage.ow_value if ow_stage else None
        division_lookback = next(
            (s.lookback_tournaments for s in resolved_stages if s.source == "division_history"), None
        )
        analytics_lookback = next((s.lookback_tournaments for s in resolved_stages if s.source == "analytics"), None)

        now = datetime.now(UTC)
        tournament = await self.rank_sources._load_tournament_for_autofill(session, tournament_id)
        enabled_sources = autofill_sources(enabled_sources, getattr(tournament, "discipline", None))
        provider = discipline(tournament.discipline).identity_provider if tournament is not None else None
        grid = await self.common.get_tournament_grid(session, tournament_id)
        # Loop-invariant: one autofill run is scoped to one tournament, and every
        # inherited rank layer below is read through its workspace.
        workspace_id = getattr(tournament, "workspace_id", None)

        registrations = await self.rank_sources._load_rank_autofill_registrations(
            session, tournament_id, registration_ids
        )
        accounts_by_key = await self.rank_sources._load_primary_accounts_by_key(
            session, registrations, provider=provider
        )
        # A Battle.net game reads OverFast through the registration's primary account. Any other game's player is the
        # registration's member, its stable identity: the handle the registration was submitted with may no longer
        # name the account (the LoL collector follows a Riot ID rename onto it).
        member_player_ids: dict[int, int] = (
            {}
            if provider == SocialProvider.BATTLENET
            else {r.id: r.workspace_member.player_id for r in registrations if r.workspace_member is not None}
        )
        user_ids = [battle_tag.user_id for battle_tag in accounts_by_key.values() if battle_tag.user_id is not None]
        user_ids += member_player_ids.values()
        # One resolve for the whole run: the role SET the plan fills, and the
        # "would this be complete" verdict, both come from these rosters.
        rosters = await roster_engine.resolve(
            session, registrations, workspace_id=workspace_id, tournament_id=tournament_id, grid=grid
        )

        # Only load a source when its stage is enabled (skips its DB query otherwise). A disabled
        # source contributes no candidate, so it can never win the priority chain.
        ow_signals_by_tag_id: dict[int, dict[str, _OwRankSignals]] = {}
        native_signals_by_user_id: dict[int, dict[str, _OwRankSignals]] = {}
        if "ow" in enabled_sources:
            if provider == SocialProvider.BATTLENET:
                ow_week_window = timedelta(days=ow_lookback_days) if ow_lookback_days else OW_RANK_WEEK_WINDOW
                ow_signals_by_tag_id = await self.rank_sources._load_ow_rank_signals_by_social_account_id(
                    session,
                    [account.id for account in accounts_by_key.values()],
                    now,
                    ow_week_window,
                )
            else:
                native_signals_by_user_id = await self.rank_sources._load_native_rank_signals_by_user_id(
                    session, tournament.discipline, user_ids
                )

        # Balancer history (division_history) and tournament-participation history (analytics) are
        # both candidates in the priority chain, keyed by user_id then registration role code.
        balancer_history_by_user_id: dict[int, dict[str, int]] = {}
        analytics_history_by_user_id: dict[int, dict[str, int]] = {}
        if tournament is not None and ({"division_history", "analytics"} & enabled_sources):
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
        # Applied rows whose verdict is recomputed once, after the loop: ``True`` when the row joins the pool
        # (status set outright), ``False`` when only a ready/incomplete row is re-derived.
        resync: dict[int, tuple[models.Registration, bool]] = {}

        for registration in registrations:
            tag_key = primary_identity_key(registration, provider=provider)
            primary_account = accounts_by_key.get(tag_key or "")
            user_id = getattr(primary_account, "user_id", None) if primary_account else None
            if provider == SocialProvider.BATTLENET:
                ow_signals_by_role = ow_signals_by_tag_id.get(primary_account.id, {}) if primary_account else {}
            else:
                user_id = member_player_ids.get(registration.id, user_id)
                ow_signals_by_role = native_signals_by_user_id.get(user_id or -1, {})
            balancer_by_role = balancer_history_by_user_id.get(user_id or -1, {})
            analytics_by_role = analytics_history_by_user_id.get(user_id or -1, {})

            # Build one suggestion per rank-role via the selected priority chain, keyed the way the
            # plan builder expects. Registration rows, balancer/analytics history and OW snapshots
            # all speak the same role vocabulary (tank/damage/support), so the keys line up.
            rank_data_by_role: dict[str, _RankData | Any] = {}
            for registration_role in registration.roles:
                rank_role = registration_role.role
                resolved = _build_priority_rank_data(
                    order,
                    ow_signals_by_role.get(rank_role),
                    balancer_by_role.get(rank_role),
                    analytics_by_role.get(rank_role),
                    grid,
                    ow_value or "composite",
                )
                if resolved is not None:
                    rank_data_by_role[rank_role] = resolved

            roster = rosters.get(registration.id)
            row, updates = build_registration_rank_autofill_plan(
                registration,
                rank_data_by_role,
                roster=roster,
                provider=provider,
                identity_linked=primary_account is not None or user_id is not None,
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
                balancer_additions += 1
                changed = True
            elif not apply and will_add_to_balancer:
                balancer_additions += 1

            if apply and changed:
                resync[registration.id] = (registration, will_add_to_balancer)
                await self.common._register_registration_changed(session, registration)

            players.append(row)

        if resync:
            # One resolve for every applied row, AFTER the writes above: autoflush
            # publishes them, so each verdict is the one the pool will actually see.
            resolved = await roster_engine.for_tournament(
                session, tournament_id, registration_ids=list(resync), include_deleted=True
            )
            for registration_id, (registration, joins_pool) in resync.items():
                if joins_pool:
                    registration.balancer_status = included_balancer_status(resolved.get(registration_id))
                else:
                    sync_included_balancer_status(registration, resolved.get(registration_id))

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
            "ow_value": ow_value,
        }


rank_autofill_service = RankAutofillService()
