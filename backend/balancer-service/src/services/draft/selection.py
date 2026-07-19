"""Draft pick selection, autopick, override, and board advance.

The select-vs-autopick race is resolved by a single conditional UPDATE guarded
by both ``status='on_clock'`` and the optimistic ``version`` token: exactly one
writer's ``rowcount`` is 1, the loser gets a 409. Events are published by the
caller within the same transaction so WorkspaceEvent ids preserve pick order.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import (
    DraftAutopickStrategy,
    DraftFormat,
    DraftPickStatus,
    DraftPlayerStatus,
    DraftRole,
    DraftStatus,
)
from shared.core.errors import ApiExc, ApiHTTPException
from shared.models.balancer.draft import DraftPick, DraftPlayer, DraftSession, DraftTeam
from shared.repository.workspace import get_or_create_workspace_member
from src.services.draft import feasibility, loaders, ranks
from src.services.draft import suggestions as sug


@dataclass(frozen=True)
class DraftResult:
    pick: DraftPick
    next_pick: DraftPick | None
    completed: bool
    blocked_reason: str | None = None


def _err(code: str, msg: str, status_code: int = 409) -> ApiHTTPException:
    return ApiHTTPException(status_code=status_code, detail=[ApiExc(code=code, msg=msg)])


async def _actor_member_id(session: AsyncSession, draft_session: DraftSession, actor_user_id: int | None) -> int | None:
    """Resolve an acting captain's domain player id to a workspace_member id.

    dbarch03 anchors ``draft_pick.picked_by`` on ``workspace_member``; the actor
    is identified by their public player id, so map it (idempotently create) to a
    member in this draft's workspace.
    """
    if actor_user_id is None:
        return None
    member = await get_or_create_workspace_member(
        session, workspace_id=draft_session.workspace_id, player_id=actor_user_id
    )
    return member.id


async def _finalize(
    session: AsyncSession,
    pick_id: int,
    *,
    status: DraftPickStatus,
    player_id: int | None,
    picked_by_member_id: int | None,
    is_autopick: bool,
    is_admin_override: bool,
    expected_version: int,
) -> bool:
    """Atomic conditional finalize. Returns True iff this writer won the race."""
    result = await session.execute(
        sa.update(DraftPick)
        .where(
            DraftPick.id == pick_id,
            DraftPick.version == expected_version,
            DraftPick.status == DraftPickStatus.ON_CLOCK.value,
        )
        .values(
            status=status.value,
            picked_player_id=player_id,
            picked_by_workspace_member_id=picked_by_member_id,
            is_autopick=is_autopick,
            is_admin_override=is_admin_override,
            version=DraftPick.version + 1,
        )
        # Explicitly sync the identity-mapped pick in Python so callers can
        # read the finalized fields without a refresh round-trip afterwards.
        .execution_options(synchronize_session="evaluate")
    )
    return result.rowcount == 1


async def _advance(session: AsyncSession, draft_session: DraftSession) -> DraftPick | None:
    """Move the next UPCOMING pick to ON_CLOCK, or complete the draft."""
    next_pick = await session.scalar(
        sa.select(DraftPick)
        .where(
            DraftPick.session_id == draft_session.id,
            DraftPick.status == DraftPickStatus.UPCOMING.value,
        )
        .order_by(DraftPick.overall_no.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if next_pick is None:
        draft_session.status = DraftStatus.COMPLETED.value
        draft_session.current_pick_id = None
        await session.flush()
        return None

    # Handle custom round dynamic ordering when a new round starts (first pick of the round)
    if next_pick.pick_in_round == 1 and draft_session.format == DraftFormat.CUSTOM.value:
        round_rules = draft_session.settings_json.get("round_rules") or []
        round_idx = next_pick.round_no - 1
        if round_idx < len(round_rules):
            rule = round_rules[round_idx]
            if rule in ("team_avg_asc", "team_avg_desc"):
                # Average the drafted-role rank (off-role aware), not the
                # primary-role rank_value.
                avg_by_team = await _team_avg_drafted_rank(session, draft_session.id)

                # Load all teams in this draft session
                teams = (
                    await session.scalars(sa.select(DraftTeam).where(DraftTeam.session_id == draft_session.id))
                ).all()

                reverse_sort = rule == "team_avg_desc"
                sorted_teams = sorted(
                    teams, key=lambda t: (avg_by_team.get(t.id, 0.0), t.draft_position), reverse=reverse_sort
                )
                sorted_team_ids = [t.id for t in sorted_teams]

                # Get all picks in this round
                round_picks = (
                    await session.scalars(
                        sa.select(DraftPick)
                        .where(DraftPick.session_id == draft_session.id, DraftPick.round_no == next_pick.round_no)
                        .order_by(DraftPick.overall_no.asc())
                    )
                ).all()

                # Re-assign teams to the picks of this round
                for index, pick_to_update in enumerate(round_picks):
                    if index < len(sorted_team_ids):
                        pick_to_update.draft_team_id = sorted_team_ids[index]

                await session.flush()
                # round_picks returned the identity-mapped objects, so next_pick's
                # draft_team_id reassignment above is already visible in memory.

    now = datetime.now(UTC)
    next_pick.status = DraftPickStatus.ON_CLOCK.value
    next_pick.clock_started_at = now
    next_pick.clock_expires_at = now + timedelta(seconds=draft_session.pick_time_seconds)
    next_pick.clock_remaining_ms = None
    draft_session.current_pick_id = next_pick.id
    await session.flush()
    return next_pick


async def _apply_won(
    session: AsyncSession,
    draft_session: DraftSession,
    pick: DraftPick,
    player: DraftPlayer,
) -> DraftResult:
    player.status = DraftPlayerStatus.PICKED.value
    player.drafted_by_team_id = pick.draft_team_id
    await session.flush()
    next_pick = await _advance(session, draft_session)
    # No refresh needed: _finalize syncs the pick via synchronize_session and
    # draft_session was only mutated in Python (expire_on_commit=False).
    return DraftResult(pick=pick, next_pick=next_pick, completed=next_pick is None)


def role_targets(team_size: int) -> dict[DraftRole, int]:
    return feasibility.role_targets_for_team_size(team_size)


def _team_role_counts(
    players: Collection[DraftPlayer],
    picks: Collection[DraftPick],
    team_id: int,
) -> dict[DraftRole, int]:
    """Filled-role counts for one team, computed from the request snapshot.

    A resolved pick's frozen ``target_role`` wins over the player's
    ``primary_role`` (off-role picks count against the drafted role).
    """
    pick_by_player_id = {
        pk.picked_player_id: pk
        for pk in picks
        if pk.picked_player_id is not None
        and pk.draft_team_id == team_id
        and pk.status in (DraftPickStatus.COMPLETED.value, DraftPickStatus.AUTOPICKED.value)
    }
    counts = dict.fromkeys(DraftRole, 0)
    for p in players:
        if p.drafted_by_team_id != team_id or p.status != DraftPlayerStatus.PICKED.value:
            continue
        pk = pick_by_player_id.get(p.id)
        role_str = pk.target_role if (pk and pk.target_role) else p.primary_role
        if role_str:
            try:
                counts[DraftRole(role_str)] += 1
            except ValueError:
                pass
    return counts


async def _team_avg_drafted_rank(session: AsyncSession, draft_session_id: int) -> dict[int, float]:
    """Average drafted-role rank per team (picked players + captains).

    Uses each pick's frozen ``target_rank_value``; falls back to the
    role-specific rank for the drafted/primary role (captains have no pick).
    """
    players = (
        await session.scalars(
            sa.select(DraftPlayer)
            .where(
                DraftPlayer.session_id == draft_session_id,
                DraftPlayer.drafted_by_team_id.isnot(None),
                DraftPlayer.status == DraftPlayerStatus.PICKED.value,
            )
            .options(*loaders.player_options())  # role_rank reads role_ranks
        )
    ).all()
    picks = (
        await session.scalars(
            sa.select(DraftPick).where(
                DraftPick.session_id == draft_session_id,
                DraftPick.status.in_([DraftPickStatus.COMPLETED.value, DraftPickStatus.AUTOPICKED.value]),
            )
        )
    ).all()
    pick_by_player_id = {pk.picked_player_id: pk for pk in picks if pk.picked_player_id is not None}

    sums: dict[int, float] = {}
    counts: dict[int, int] = {}
    for p in players:
        pk = pick_by_player_id.get(p.id)
        if pk is not None and pk.target_rank_value is not None:
            rank = pk.target_rank_value
        else:
            role = (pk.target_role if pk else None) or p.primary_role
            rank = ranks.role_rank(p, role) or 0
        tid = p.drafted_by_team_id
        sums[tid] = sums.get(tid, 0.0) + rank
        counts[tid] = counts.get(tid, 0) + 1
    return {tid: sums[tid] / counts[tid] for tid in sums}


def _role_capacity(team_size: int, counts: dict[DraftRole, int]) -> dict[DraftRole, int]:
    targets = role_targets(team_size)
    return {role: max(0, targets.get(role, 0) - counts.get(role, 0)) for role in DraftRole}


async def _validate_current_pick(draft_session: DraftSession, pick: DraftPick) -> None:
    if draft_session.status != DraftStatus.LIVE.value:
        raise _err("draft_not_live", "Draft is not live")
    if pick.id != draft_session.current_pick_id or pick.status != DraftPickStatus.ON_CLOCK.value:
        raise _err("pick_not_on_clock", "This is not the current on-clock pick")


def _available_player_from(snapshot: feasibility.DraftSnapshot, player_id: int) -> DraftPlayer:
    # Snapshot players were loaded with loaders.player_options(), so the compat
    # read properties (secondary_roles_json/role_ranks via _role_is_legal +
    # ranks.role_rank) never trigger an async lazy load.
    player = next((p for p in snapshot.players if p.id == player_id), None)
    if player is None:
        raise _err("player_not_found", "Player not in this draft", status_code=404)
    if player.status != DraftPlayerStatus.AVAILABLE.value:
        raise _err("player_unavailable", "Player is not available")
    return player


def _role_is_legal(player: DraftPlayer, target_role: DraftRole | None) -> bool:
    if target_role is None:
        return True
    if player.is_flex:
        return True
    playable = {player.primary_role, *(player.secondary_roles_json or [])}
    return target_role.value in playable


def _playable_roles(player: DraftPlayer) -> frozenset[DraftRole]:
    if player.is_flex:
        return frozenset(DraftRole)
    return frozenset(DraftRole(role) for role in {player.primary_role, *(player.secondary_roles_json or [])})


def _unsafe_pick_error(report: feasibility.DraftFeasibilityReport) -> ApiHTTPException:
    details = feasibility.describe_role_deficits(report) or "unknown role deficit"
    return _err(
        "pick_makes_draft_infeasible",
        f"This pick would leave unfillable role slots: {details}",
        status_code=422,
    )


def mark_role_shortage_paused(draft_session: DraftSession, pick: DraftPick) -> DraftResult:
    """Pause on the unresolved current pick when no globally safe option exists."""

    draft_session.status = DraftStatus.PAUSED.value
    draft_session.blocked_reason = "role_shortage"
    pick.clock_expires_at = None
    pick.clock_remaining_ms = 0
    return DraftResult(
        pick=pick,
        next_pick=None,
        completed=False,
        blocked_reason="role_shortage",
    )


def _is_on_clock_captain(
    team: DraftTeam | None,
    *,
    actor_auth_user_id: int | None,
    actor_player_ids: Collection[int],
) -> bool:
    if team is None:
        return False
    if actor_auth_user_id is not None and team.captain_auth_user_id == actor_auth_user_id:
        return True
    return team.captain_user_id is not None and team.captain_user_id in actor_player_ids


async def select(
    session: AsyncSession,
    draft_session: DraftSession,
    pick: DraftPick,
    *,
    player_id: int,
    expected_version: int,
    target_role: DraftRole | None,
    actor_user_id: int | None,
    actor_auth_user_id: int | None = None,
    actor_player_ids: Collection[int] = (),
    is_admin: bool,
) -> DraftResult:
    await _validate_current_pick(draft_session, pick)
    # captain_user_id (read in _is_on_clock_captain) resolves via captain_member;
    # eager-load it so the property read never triggers an async lazy load.
    team = await session.get(DraftTeam, pick.draft_team_id, options=loaders.team_options(), populate_existing=True)
    player_ids = set(actor_player_ids)
    if actor_user_id is not None:
        player_ids.add(actor_user_id)
    if not is_admin and not _is_on_clock_captain(
        team,
        actor_auth_user_id=actor_auth_user_id,
        actor_player_ids=player_ids,
    ):
        raise _err("not_your_pick", "Only the on-clock captain may pick", status_code=403)
    snapshot = await feasibility.load_snapshot(session, draft_session)
    player = _available_player_from(snapshot, player_id)
    if not _role_is_legal(player, target_role):
        raise _err("illegal_role", "Player cannot play the requested role", status_code=422)

    chosen_role = target_role or DraftRole(player.primary_role)
    counts = _team_role_counts(snapshot.players, snapshot.picks, pick.draft_team_id)
    targets = role_targets(draft_session.team_size)
    if counts.get(chosen_role, 0) >= targets.get(chosen_role, 0):
        raise _err("role_filled", f"Role {chosen_role.value} is already filled for this team", status_code=422)

    feasibility_report = await feasibility.analyze_session(
        session,
        draft_session,
        state=feasibility.state_from_snapshot(draft_session, snapshot),
        hypothetical=feasibility.DraftAssignment(
            player_id=player.id,
            team_id=pick.draft_team_id,
            role=chosen_role,
        ),
    )
    if not feasibility_report.is_feasible:
        raise _unsafe_pick_error(feasibility_report)

    won = await _finalize(
        session,
        pick.id,
        status=DraftPickStatus.COMPLETED,
        player_id=player.id,
        picked_by_member_id=await _actor_member_id(session, draft_session, actor_user_id),
        is_autopick=False,
        is_admin_override=False,
        expected_version=expected_version,
    )
    if not won:
        raise _err("pick_already_resolved", "Pick was already resolved")
    # Always record the resolved decision (role + its rank) on the pick, so the
    # pick is a complete (player, role, rank) record regardless of off-role.
    pick.target_role = chosen_role.value
    pick.target_rank_value = ranks.role_rank(player, chosen_role)
    return await _apply_won(session, draft_session, pick, player)


async def autopick(
    session: AsyncSession,
    draft_session: DraftSession,
    pick: DraftPick,
    *,
    expected_version: int,
    actor_user_id: int | None = None,
) -> DraftResult:
    await _validate_current_pick(draft_session, pick)
    snapshot = await feasibility.load_snapshot(session, draft_session)
    # Fit construction reads secondary_roles_json/user_id/role_ranks; snapshot
    # players carry loaders.player_options() so those never lazy-load.
    available = [p for p in snapshot.players if p.status == DraftPlayerStatus.AVAILABLE.value]
    counts = _team_role_counts(snapshot.players, snapshot.picks, pick.draft_team_id)
    capacity = _role_capacity(draft_session.team_size, counts)

    fit_players = [
        sug.FitPlayer(
            player_id=p.id,
            rank_value=p.rank_value or 0,
            playable_roles=_playable_roles(p),
            preference_order=(DraftRole(p.primary_role),),
            is_flex=p.is_flex,
            user_id=p.user_id,
            rank_by_role={DraftRole(k): v for k, v in (p.role_ranks or {}).items()},
        )
        for p in available
    ]
    options = await feasibility.evaluate_session_pick_options(
        session,
        draft_session,
        team_id=pick.draft_team_id,
        state=feasibility.state_from_snapshot(draft_session, snapshot),
    )
    safe_options = {(option.player_id, option.role) for option in options if option.is_safe}
    choice = sug.best_fit(
        fit_players,
        capacity,
        DraftAutopickStrategy(draft_session.autopick_strategy),
        sug.FitConfig(),
        allowed_options=safe_options,
    )
    chosen_id = choice.player_id if choice is not None else None
    chosen_role = choice.role if choice is not None else None

    if chosen_id is None:
        result = mark_role_shortage_paused(draft_session, pick)
        await session.flush()
        return result

    won = await _finalize(
        session,
        pick.id,
        status=DraftPickStatus.AUTOPICKED,
        player_id=chosen_id,
        picked_by_member_id=None,
        is_autopick=True,
        is_admin_override=False,
        expected_version=expected_version,
    )
    if not won:
        raise _err("pick_already_resolved", "Pick was already resolved")
    # ranks.role_rank(player, ...) reads role_ranks -> roles; the chosen row came
    # from the snapshot's eager-loaded players, so no re-fetch is needed.
    player = next(p for p in available if p.id == chosen_id)
    resolved_role = chosen_role or DraftRole(player.primary_role)
    pick.target_role = resolved_role.value
    pick.target_rank_value = ranks.role_rank(player, resolved_role)
    return await _apply_won(session, draft_session, pick, player)


async def override(
    session: AsyncSession,
    draft_session: DraftSession,
    pick: DraftPick,
    *,
    player_id: int | None,
    expected_version: int,
    actor_user_id: int | None,
    target_role: DraftRole | None = None,
) -> DraftResult:
    if not draft_session.allow_admin_override:
        raise _err("override_disabled", "Admin override is disabled for this draft")
    await _validate_current_pick(draft_session, pick)
    if player_id is None:
        raise _err("override_needs_player", "Override requires a player_id", status_code=422)
    snapshot = await feasibility.load_snapshot(session, draft_session)
    player = _available_player_from(snapshot, player_id)
    if not _role_is_legal(player, target_role):
        raise _err("illegal_role", "Player cannot play the requested role", status_code=422)
    resolved_role = target_role or DraftRole(player.primary_role)
    counts = _team_role_counts(snapshot.players, snapshot.picks, pick.draft_team_id)
    targets = role_targets(draft_session.team_size)
    if counts.get(resolved_role, 0) >= targets.get(resolved_role, 0):
        raise _err("role_filled", f"Role {resolved_role.value} is already filled for this team", status_code=422)
    feasibility_report = await feasibility.analyze_session(
        session,
        draft_session,
        state=feasibility.state_from_snapshot(draft_session, snapshot),
        hypothetical=feasibility.DraftAssignment(
            player_id=player.id,
            team_id=pick.draft_team_id,
            role=resolved_role,
        ),
    )
    if not feasibility_report.is_feasible:
        raise _unsafe_pick_error(feasibility_report)

    won = await _finalize(
        session,
        pick.id,
        status=DraftPickStatus.COMPLETED,
        player_id=player.id,
        picked_by_member_id=await _actor_member_id(session, draft_session, actor_user_id),
        is_autopick=False,
        is_admin_override=True,
        expected_version=expected_version,
    )
    if not won:
        raise _err("pick_already_resolved", "Pick was already resolved")
    pick.target_role = resolved_role.value
    pick.target_rank_value = ranks.role_rank(player, resolved_role)
    return await _apply_won(session, draft_session, pick, player)
