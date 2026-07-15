"""Pure role-feasibility rules for live draft sessions.

A draft is feasible when every still-open ``(team, role)`` roster slot can be
matched to a distinct available player who declared that role.  Evaluating a
hypothetical pick removes both the chosen slot and player before matching, which
prevents a locally legal pick from starving another team's future role slot.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import DraftPickStatus, DraftPlayerStatus, DraftRole
from shared.models.balancer.draft import DraftPick, DraftPlayer, DraftSession, DraftTeam
from src.services.draft import loaders
from src.services.role_matching import maximum_bipartite_matching


@dataclass(frozen=True)
class EligiblePlayer:
    player_id: int
    playable_roles: frozenset[DraftRole]


@dataclass(frozen=True)
class DraftAssignment:
    player_id: int
    team_id: int
    role: DraftRole


@dataclass(frozen=True)
class DraftSlot:
    team_id: int
    role: DraftRole
    ordinal: int


@dataclass(frozen=True)
class RoleDeficit:
    role: DraftRole
    unmatched_slots: int
    eligible_players: int


@dataclass(frozen=True)
class DraftFeasibilityReport:
    is_feasible: bool
    total_open_slots: int
    matched_slots: int
    unmatched_slots: tuple[DraftSlot, ...]
    role_deficits: tuple[RoleDeficit, ...]
    blocking_player_ids: tuple[int, ...]
    reason_code: str | None = None


@dataclass(frozen=True)
class DraftPickOption:
    player_id: int
    role: DraftRole
    is_safe: bool
    reason_code: str | None
    unmatched_slots: tuple[DraftSlot, ...] = ()
    blocking_player_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class DraftFeasibilityState:
    team_ids: tuple[int, ...]
    role_targets: dict[DraftRole, int]
    players: tuple[EligiblePlayer, ...]
    assignments: tuple[DraftAssignment, ...]


def role_targets_for_team_size(team_size: int) -> dict[DraftRole, int]:
    if team_size >= 5:
        return {
            DraftRole.TANK: 1,
            DraftRole.DPS: 2,
            DraftRole.SUPPORT: max(2, team_size - 3),
        }
    if team_size <= 0:
        return dict.fromkeys(DraftRole, 0)
    tank = min(1, team_size)
    dps = min(2, max(team_size - tank, 0))
    return {
        DraftRole.TANK: tank,
        DraftRole.DPS: dps,
        DraftRole.SUPPORT: max(team_size - tank - dps, 0),
    }


def _as_role(value: Any) -> DraftRole | None:
    try:
        return DraftRole(str(value))
    except ValueError:
        return None


def build_feasibility_state(
    *,
    team_size: int,
    teams: Collection[DraftTeam],
    players: Collection[DraftPlayer],
    picks: Collection[DraftPick],
) -> DraftFeasibilityState:
    """Translate eager-loaded ORM snapshot rows into the pure matching input."""

    team_ids = tuple(team.id for team in sorted(teams, key=lambda team: (team.draft_position, team.id)))
    picked_role_by_player = {
        pick.picked_player_id: role
        for pick in picks
        if pick.picked_player_id is not None
        and pick.status
        in {
            DraftPickStatus.COMPLETED.value,
            DraftPickStatus.AUTOPICKED.value,
        }
        and (role := _as_role(pick.target_role)) is not None
    }
    eligible_players: list[EligiblePlayer] = []
    assignments: list[DraftAssignment] = []
    for player in players:
        primary_role = _as_role(player.primary_role)
        if player.status == DraftPlayerStatus.AVAILABLE.value:
            playable_roles = frozenset(DraftRole) if player.is_flex else frozenset(
                role
                for entry in player.roles
                if (role := _as_role(entry.role)) is not None
            )
            if primary_role is not None:
                playable_roles = playable_roles | {primary_role}
            eligible_players.append(EligiblePlayer(player_id=player.id, playable_roles=playable_roles))
            continue
        if player.status != DraftPlayerStatus.PICKED.value or player.drafted_by_team_id is None:
            continue
        assigned_role = picked_role_by_player.get(player.id) or primary_role
        if assigned_role is not None:
            assignments.append(
                DraftAssignment(
                    player_id=player.id,
                    team_id=player.drafted_by_team_id,
                    role=assigned_role,
                )
            )
    return DraftFeasibilityState(
        team_ids=team_ids,
        role_targets=role_targets_for_team_size(team_size),
        players=tuple(eligible_players),
        assignments=tuple(assignments),
    )


async def load_feasibility_state(
    session: AsyncSession,
    draft_session: DraftSession,
) -> DraftFeasibilityState:
    teams = (
        await session.scalars(
            sa.select(DraftTeam)
            .where(DraftTeam.session_id == draft_session.id)
            .order_by(DraftTeam.draft_position.asc())
        )
    ).all()
    players = (
        await session.scalars(
            sa.select(DraftPlayer)
            .where(DraftPlayer.session_id == draft_session.id)
            .options(*loaders.player_options())
        )
    ).all()
    picks = (
        await session.scalars(sa.select(DraftPick).where(DraftPick.session_id == draft_session.id))
    ).all()
    return build_feasibility_state(
        team_size=draft_session.team_size,
        teams=teams,
        players=players,
        picks=picks,
    )


async def analyze_session(
    session: AsyncSession,
    draft_session: DraftSession,
    *,
    hypothetical: DraftAssignment | None = None,
) -> DraftFeasibilityReport:
    state = await load_feasibility_state(session, draft_session)
    return analyze_draft_feasibility(
        team_ids=state.team_ids,
        role_targets=state.role_targets,
        players=state.players,
        assignments=state.assignments,
        hypothetical=hypothetical,
    )


async def evaluate_session_pick_options(
    session: AsyncSession,
    draft_session: DraftSession,
    *,
    team_id: int,
) -> tuple[DraftPickOption, ...]:
    state = await load_feasibility_state(session, draft_session)
    return evaluate_pick_options(
        team_id=team_id,
        team_ids=state.team_ids,
        role_targets=state.role_targets,
        players=state.players,
        assignments=state.assignments,
    )


def _ordered_roles(role_targets: Mapping[DraftRole, int]) -> tuple[DraftRole, ...]:
    return tuple(role for role in DraftRole if role_targets.get(role, 0) > 0)


def describe_role_deficits(report: DraftFeasibilityReport) -> str:
    """Return a safe, compact explanation suitable for API errors."""

    return ", ".join(
        f"{deficit.role.value}: {deficit.unmatched_slots} open, {deficit.eligible_players} eligible"
        for deficit in report.role_deficits
    )


def _remaining_capacity(
    *,
    team_ids: Collection[int],
    role_targets: Mapping[DraftRole, int],
    assignments: Collection[DraftAssignment],
) -> tuple[dict[tuple[int, DraftRole], int], bool]:
    remaining = {
        (team_id, role): int(role_targets.get(role, 0))
        for team_id in dict.fromkeys(team_ids)
        for role in _ordered_roles(role_targets)
    }
    overfilled = False
    for assignment in assignments:
        key = (assignment.team_id, assignment.role)
        if key not in remaining or remaining[key] <= 0:
            overfilled = True
            continue
        remaining[key] -= 1
    return remaining, overfilled


def _open_slots(remaining: Mapping[tuple[int, DraftRole], int]) -> tuple[DraftSlot, ...]:
    return tuple(
        DraftSlot(team_id=team_id, role=role, ordinal=ordinal)
        for (team_id, role), count in remaining.items()
        for ordinal in range(count)
    )


def analyze_draft_feasibility(
    *,
    team_ids: Collection[int],
    role_targets: Mapping[DraftRole, int],
    players: Collection[EligiblePlayer],
    assignments: Collection[DraftAssignment] = (),
    hypothetical: DraftAssignment | None = None,
) -> DraftFeasibilityReport:
    """Analyze the remaining draft, optionally after one hypothetical pick."""

    all_assignments = (*assignments, *((hypothetical,) if hypothetical is not None else ()))
    remaining, overfilled = _remaining_capacity(
        team_ids=team_ids,
        role_targets=role_targets,
        assignments=all_assignments,
    )
    slots = _open_slots(remaining)
    assigned_player_ids = {assignment.player_id for assignment in all_assignments}
    available_players = tuple(player for player in players if player.player_id not in assigned_player_ids)
    slots_by_role = {
        role: tuple(slot for slot in slots if slot.role == role)
        for role in _ordered_roles(role_targets)
    }
    eligible_slots = {
        player.player_id: tuple(
            slot
            for role in _ordered_roles(role_targets)
            if role in player.playable_roles
            for slot in slots_by_role[role]
        )
        for player in available_players
    }
    matching = maximum_bipartite_matching(
        candidates=tuple(player.player_id for player in available_players),
        slots=slots,
        eligible_slots=eligible_slots,
    )
    unmatched_roles = {slot.role for slot in matching.unmatched_slots}
    blocking_players = tuple(
        player.player_id
        for player in available_players
        if player.playable_roles & unmatched_roles
    )
    unmatched_counts = Counter(slot.role for slot in matching.unmatched_slots)
    role_deficits = tuple(
        RoleDeficit(
            role=role,
            unmatched_slots=unmatched_counts[role],
            eligible_players=sum(role in player.playable_roles for player in available_players),
        )
        for role in _ordered_roles(role_targets)
        if unmatched_counts[role]
    )
    reason_code = "role_overfilled" if overfilled else ("role_shortage" if matching.unmatched_slots else None)
    return DraftFeasibilityReport(
        is_feasible=not overfilled and not matching.unmatched_slots,
        total_open_slots=len(slots),
        matched_slots=matching.matched_count,
        unmatched_slots=matching.unmatched_slots,
        role_deficits=role_deficits,
        blocking_player_ids=blocking_players,
        reason_code=reason_code,
    )


def evaluate_pick_options(
    *,
    team_id: int,
    team_ids: Collection[int],
    role_targets: Mapping[DraftRole, int],
    players: Collection[EligiblePlayer],
    assignments: Collection[DraftAssignment] = (),
) -> tuple[DraftPickOption, ...]:
    """Return safe/blocked role choices for every available player."""

    remaining, _ = _remaining_capacity(
        team_ids=team_ids,
        role_targets=role_targets,
        assignments=assignments,
    )
    options: list[DraftPickOption] = []
    # Players with the same declared role set are interchangeable for the
    # feasibility question. Cache one forced-pick matching per role-set/role
    # pair; at the supported scale this reduces hundreds of equivalent graph
    # runs to at most 21 (seven non-empty subsets of three canonical roles).
    report_cache: dict[tuple[frozenset[DraftRole], DraftRole], tuple[int, DraftFeasibilityReport]] = {}
    for player in players:
        for role in DraftRole:
            if role not in player.playable_roles:
                continue
            if remaining.get((team_id, role), 0) <= 0:
                options.append(
                    DraftPickOption(
                        player_id=player.player_id,
                        role=role,
                        is_safe=False,
                        reason_code="role_filled",
                    )
                )
                continue
            cache_key = (player.playable_roles, role)
            cached = report_cache.get(cache_key)
            if cached is None:
                report = analyze_draft_feasibility(
                    team_ids=team_ids,
                    role_targets=role_targets,
                    players=players,
                    assignments=assignments,
                    hypothetical=DraftAssignment(player_id=player.player_id, team_id=team_id, role=role),
                )
                representative_id = player.player_id
                report_cache[cache_key] = (representative_id, report)
            else:
                representative_id, report = cached
            blocking_player_ids = report.blocking_player_ids
            if representative_id != player.player_id:
                blocking_player_ids = tuple(
                    representative_id if player_id == player.player_id else player_id
                    for player_id in blocking_player_ids
                )
            options.append(
                DraftPickOption(
                    player_id=player.player_id,
                    role=role,
                    is_safe=report.is_feasible,
                    reason_code=None if report.is_feasible else report.reason_code,
                    unmatched_slots=report.unmatched_slots,
                    blocking_player_ids=blocking_player_ids,
                )
            )
    return tuple(options)


__all__ = (
    "DraftAssignment",
    "DraftFeasibilityReport",
    "DraftFeasibilityState",
    "DraftPickOption",
    "DraftSlot",
    "EligiblePlayer",
    "RoleDeficit",
    "analyze_draft_feasibility",
    "analyze_session",
    "build_feasibility_state",
    "describe_role_deficits",
    "evaluate_pick_options",
    "evaluate_session_pick_options",
    "load_feasibility_state",
    "role_targets_for_team_size",
)
