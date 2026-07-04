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
from src.services.draft import ranks
from src.services.draft import suggestions as sug


@dataclass(frozen=True)
class DraftResult:
    pick: DraftPick
    next_pick: DraftPick | None
    completed: bool


def _err(code: str, msg: str, status_code: int = 409) -> ApiHTTPException:
    return ApiHTTPException(status_code=status_code, detail=[ApiExc(code=code, msg=msg)])


async def _finalize(
    session: AsyncSession,
    pick_id: int,
    *,
    status: DraftPickStatus,
    player_id: int | None,
    picked_by_user_id: int | None,
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
            picked_by_user_id=picked_by_user_id,
            is_autopick=is_autopick,
            is_admin_override=is_admin_override,
            version=DraftPick.version + 1,
        )
    )
    return result.rowcount == 1


async def _team_picked_count(session: AsyncSession, team_id: int) -> int:
    return (
        await session.scalar(
            sa.select(sa.func.count())
            .select_from(DraftPlayer)
            .where(
                DraftPlayer.drafted_by_team_id == team_id,
                DraftPlayer.status == DraftPlayerStatus.PICKED.value,
            )
        )
        or 0
    )


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
                    await session.scalars(
                        sa.select(DraftTeam)
                        .where(DraftTeam.session_id == draft_session.id)
                    )
                ).all()

                reverse_sort = rule == "team_avg_desc"
                sorted_teams = sorted(
                    teams,
                    key=lambda t: (avg_by_team.get(t.id, 0.0), t.draft_position),
                    reverse=reverse_sort
                )
                sorted_team_ids = [t.id for t in sorted_teams]

                # Get all picks in this round
                round_picks = (
                    await session.scalars(
                        sa.select(DraftPick)
                        .where(
                            DraftPick.session_id == draft_session.id,
                            DraftPick.round_no == next_pick.round_no
                        )
                        .order_by(DraftPick.overall_no.asc())
                    )
                ).all()

                # Re-assign teams to the picks of this round
                for index, pick_to_update in enumerate(round_picks):
                    if index < len(sorted_team_ids):
                        pick_to_update.draft_team_id = sorted_team_ids[index]

                await session.flush()
                # Refresh next_pick's data as its draft_team_id might have changed
                await session.refresh(next_pick)

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
    await session.refresh(pick)
    await session.refresh(draft_session)
    return DraftResult(pick=pick, next_pick=next_pick, completed=next_pick is None)


def role_targets(team_size: int) -> dict[DraftRole, int]:
    if team_size >= 5:
        return {
            DraftRole.TANK: 1,
            DraftRole.DPS: 2,
            DraftRole.SUPPORT: max(2, team_size - 3),
        }
    if team_size <= 0:
        return {DraftRole.TANK: 0, DraftRole.DPS: 0, DraftRole.SUPPORT: 0}
    tank = min(1, team_size)
    dps = min(2, max(team_size - tank, 0))
    support = max(team_size - tank - dps, 0)
    return {DraftRole.TANK: tank, DraftRole.DPS: dps, DraftRole.SUPPORT: support}


async def _team_role_counts(session: AsyncSession, team_id: int) -> dict[DraftRole, int]:
    players = (
        await session.scalars(
            sa.select(DraftPlayer).where(
                DraftPlayer.drafted_by_team_id == team_id,
                DraftPlayer.status == DraftPlayerStatus.PICKED.value,
            )
        )
    ).all()
    picks = (
        await session.scalars(
            sa.select(DraftPick).where(
                DraftPick.draft_team_id == team_id,
                DraftPick.status.in_(
                    [DraftPickStatus.COMPLETED.value, DraftPickStatus.AUTOPICKED.value]
                ),
            )
        )
    ).all()

    pick_by_player_id = {pk.picked_player_id: pk for pk in picks if pk.picked_player_id is not None}
    counts = {r: 0 for r in DraftRole}
    for p in players:
        pk = pick_by_player_id.get(p.id)
        role_str = pk.target_role if (pk and pk.target_role) else p.primary_role
        if role_str:
            try:
                role = DraftRole(role_str)
                counts[role] += 1
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
            sa.select(DraftPlayer).where(
                DraftPlayer.session_id == draft_session_id,
                DraftPlayer.drafted_by_team_id.isnot(None),
                DraftPlayer.status == DraftPlayerStatus.PICKED.value,
            )
        )
    ).all()
    picks = (
        await session.scalars(
            sa.select(DraftPick).where(
                DraftPick.session_id == draft_session_id,
                DraftPick.status.in_(
                    [DraftPickStatus.COMPLETED.value, DraftPickStatus.AUTOPICKED.value]
                ),
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
    return {
        role: max(0, targets.get(role, 0) - counts.get(role, 0))
        for role in DraftRole
    }



async def _validate_current_pick(draft_session: DraftSession, pick: DraftPick) -> None:
    if draft_session.status != DraftStatus.LIVE.value:
        raise _err("draft_not_live", "Draft is not live")
    if pick.id != draft_session.current_pick_id or pick.status != DraftPickStatus.ON_CLOCK.value:
        raise _err("pick_not_on_clock", "This is not the current on-clock pick")


async def _load_available_player(session: AsyncSession, draft_session_id: int, player_id: int) -> DraftPlayer:
    player = await session.get(DraftPlayer, player_id)
    if player is None or player.session_id != draft_session_id:
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
    team = await session.get(DraftTeam, pick.draft_team_id)
    player_ids = set(actor_player_ids)
    if actor_user_id is not None:
        player_ids.add(actor_user_id)
    if not is_admin and not _is_on_clock_captain(
        team,
        actor_auth_user_id=actor_auth_user_id,
        actor_player_ids=player_ids,
    ):
        raise _err("not_your_pick", "Only the on-clock captain may pick", status_code=403)
    player = await _load_available_player(session, draft_session.id, player_id)
    if not _role_is_legal(player, target_role):
        raise _err("illegal_role", "Player cannot play the requested role", status_code=422)

    chosen_role = target_role or DraftRole(player.primary_role)
    counts = await _team_role_counts(session, pick.draft_team_id)
    targets = role_targets(draft_session.team_size)
    if counts.get(chosen_role, 0) >= targets.get(chosen_role, 0):
        raise _err("role_filled", f"Role {chosen_role.value} is already filled for this team", status_code=422)

    won = await _finalize(
        session,
        pick.id,
        status=DraftPickStatus.COMPLETED,
        player_id=player.id,
        picked_by_user_id=actor_user_id,
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
    available = (
        await session.scalars(
            sa.select(DraftPlayer).where(
                DraftPlayer.session_id == draft_session.id,
                DraftPlayer.status == DraftPlayerStatus.AVAILABLE.value,
            )
        )
    ).all()
    counts = await _team_role_counts(session, pick.draft_team_id)
    capacity = _role_capacity(draft_session.team_size, counts)

    fit_players = [
        sug.FitPlayer(
            player_id=p.id,
            rank_value=p.rank_value or 0,
            playable_roles=frozenset(DraftRole(r) for r in ({p.primary_role, *(p.secondary_roles_json or [])})),
            preference_order=(DraftRole(p.primary_role),),
            is_flex=p.is_flex,
            user_id=p.user_id,
            rank_by_role={DraftRole(k): v for k, v in (p.role_ranks or {}).items()},
        )
        for p in available
    ]
    choice = sug.best_fit(
        fit_players,
        capacity,
        DraftAutopickStrategy(draft_session.autopick_strategy),
        sug.FitConfig(),
    )
    # Fallback: any available player if fit produced nothing (e.g. no capacity map).
    chosen_id = choice.player_id if choice is not None else (available[0].id if available else None)
    chosen_role = choice.role if choice is not None else None

    won = await _finalize(
        session,
        pick.id,
        status=DraftPickStatus.AUTOPICKED if chosen_id is not None else DraftPickStatus.SKIPPED,
        player_id=chosen_id,
        picked_by_user_id=None,
        is_autopick=True,
        is_admin_override=False,
        expected_version=expected_version,
    )
    if not won:
        raise _err("pick_already_resolved", "Pick was already resolved")
    if chosen_id is None:
        await session.refresh(pick)
        next_pick = await _advance(session, draft_session)
        await session.refresh(draft_session)
        return DraftResult(pick=pick, next_pick=next_pick, completed=next_pick is None)
    player = await session.get(DraftPlayer, chosen_id)
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
    player = await _load_available_player(session, draft_session.id, player_id)
    if not _role_is_legal(player, target_role):
        raise _err("illegal_role", "Player cannot play the requested role", status_code=422)
    won = await _finalize(
        session,
        pick.id,
        status=DraftPickStatus.COMPLETED,
        player_id=player.id,
        picked_by_user_id=actor_user_id,
        is_autopick=False,
        is_admin_override=True,
        expected_version=expected_version,
    )
    if not won:
        raise _err("pick_already_resolved", "Pick was already resolved")
    resolved_role = target_role or DraftRole(player.primary_role)
    pick.target_role = resolved_role.value
    pick.target_rank_value = ranks.role_rank(player, resolved_role)
    return await _apply_won(session, draft_session, pick, player)
