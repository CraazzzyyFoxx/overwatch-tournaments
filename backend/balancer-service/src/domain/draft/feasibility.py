"""Pure slot-feasibility rules for live draft sessions.

A draft is feasible when every still-open ``(team, slot)`` roster slot can be
matched to a distinct available player who fits it. A role slot fits a player
who declared that role; a ``flex`` slot fits anybody. Evaluating a hypothetical
pick removes both the chosen slot and player before matching, which prevents a
locally legal pick from starving another team's future roster slot.

No database access, no event loop — every function here is synchronous and
deterministic over ``entities``. ``services/draft/feasibility.py`` is the only
file that loads rows and offloads these functions to a thread.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Mapping
from typing import Any

from shared.core.enums import HERO_TYPE_CLASSES, DraftPickStatus, DraftPlayerStatus, HeroClass
from shared.domain.roster import PlayerRoster
from shared.domain.roster_shape import FLEX_SLOT_CODE, ROSTER_SLOT_CODES, RosterShape
from shared.models.balancer.draft import DraftPick, DraftPlayer, DraftTeam
from src.domain.draft.entities import (
    DraftAssignment,
    DraftFeasibilityReport,
    DraftFeasibilityState,
    DraftPickOption,
    DraftSlot,
    EligiblePlayer,
    SlotDeficit,
)
from src.domain.draft.ranks import seat_role
from src.domain.matching import maximum_bipartite_matching

__all__ = (
    # re-exported types — every function below takes or returns these, so a
    # caller importing "the feasibility algorithm" gets its vocabulary too.
    "DraftAssignment",
    "DraftFeasibilityReport",
    "DraftFeasibilityState",
    "DraftPickOption",
    "DraftSlot",
    "EligiblePlayer",
    "SlotDeficit",
    # algorithm
    "analyze_draft_feasibility",
    "build_feasibility_state",
    "describe_role_deficits",
    "evaluate_pick_options",
)


def _as_role(value: Any) -> HeroClass | None:
    """Parse a role slot code; ``flex`` is a roster slot, never a rated role."""
    role = HeroClass.parse(value)
    return role if role is not HeroClass.flex else None


def build_feasibility_state(
    *,
    shape: RosterShape,
    teams: Collection[DraftTeam],
    players: Collection[DraftPlayer],
    picks: Collection[DraftPick],
    rosters: Mapping[int, PlayerRoster],
) -> DraftFeasibilityState:
    """Translate a snapshot into the pure matching input.

    Which roles a player can fill is asked of ``rosters`` -- the one engine's
    answer, keyed by ``DraftPlayer.id`` -- so feasibility, the pick options and
    the board can never disagree about it. A player the balancer ranks on no
    role contributes no eligibility, which is what makes the draft REPORT the
    shortage instead of quietly picking them at rank 0.
    """

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
        roster = rosters.get(player.id)
        if player.status == DraftPlayerStatus.AVAILABLE.value:
            playable_roles = roster.playable_roles if roster is not None else frozenset()
            if playable_roles:
                eligible_players.append(EligiblePlayer(player_id=player.id, playable_roles=playable_roles))
            continue
        if player.status != DraftPlayerStatus.PICKED.value or player.drafted_by_team_id is None:
            continue
        # Which slot a picked player occupies: on a role-less roster there is only
        # flex, so every pick lands there and a missing role is no longer a reason
        # to skip the player. Otherwise the drafted role names the slot, and the
        # "role slot already full -> spill into flex" rule lives in
        # _remaining_capacity, where the per-team counters already exist, instead
        # of being recomputed here and again for every hypothetical pick.
        if not shape.has_role_slots:
            assignments.append(
                DraftAssignment(
                    player_id=player.id,
                    team_id=player.drafted_by_team_id,
                    slot_code=FLEX_SLOT_CODE,
                )
            )
            continue
        # A pick's frozen role, else the seat's own: a captain's pinned role or
        # the lead one (``ranks.seat_role``).
        assigned_role = picked_role_by_player.get(player.id) or seat_role(roster, player.captain_role)
        if assigned_role is not None:
            assignments.append(
                DraftAssignment(
                    player_id=player.id,
                    team_id=player.drafted_by_team_id,
                    slot_code=assigned_role.slot_code,
                )
            )
    return DraftFeasibilityState(
        team_ids=team_ids,
        slot_targets=shape.slots,
        players=tuple(eligible_players),
        assignments=tuple(assignments),
    )


def _ordered_slot_codes(slot_targets: Mapping[str, int]) -> tuple[str, ...]:
    return tuple(code for code in ROSTER_SLOT_CODES if slot_targets.get(code, 0) > 0)


def _slot_fits(player: EligiblePlayer, slot_code: str) -> bool:
    """The one new rule of the slot vocabulary: flex takes anybody."""
    if slot_code == FLEX_SLOT_CODE:
        return True
    role = _as_role(slot_code)
    return role is not None and role in player.playable_roles


def describe_role_deficits(report: DraftFeasibilityReport) -> str:
    """Return a safe, compact explanation suitable for API errors."""

    return ", ".join(
        f"{deficit.slot_code}: {deficit.unmatched_slots} open, {deficit.eligible_players} eligible"
        for deficit in report.slot_deficits
    )


def _remaining_capacity(
    *,
    team_ids: Collection[int],
    slot_targets: Mapping[str, int],
    assignments: Collection[DraftAssignment],
) -> tuple[dict[tuple[int, str], int], bool]:
    remaining = {
        (team_id, code): int(slot_targets.get(code, 0))
        for team_id in dict.fromkeys(team_ids)
        for code in _ordered_slot_codes(slot_targets)
    }
    overfilled = False
    for assignment in assignments:
        key = (assignment.team_id, assignment.slot_code)
        if remaining.get(key, 0) > 0:
            remaining[key] -= 1
            continue
        # A role slot with no room left spills into a free flex slot: flex accepts
        # anybody, so an extra tank on a {tank: 1, flex: 5} roster is a legal flex
        # pick, not an overfill. Doing it here keeps the rule in one place for
        # already-resolved picks and hypothetical ones alike. Only when neither the
        # named slot nor flex has room is the roster genuinely overfilled.
        flex_key = (assignment.team_id, FLEX_SLOT_CODE)
        if assignment.slot_code != FLEX_SLOT_CODE and remaining.get(flex_key, 0) > 0:
            remaining[flex_key] -= 1
            continue
        overfilled = True
    return remaining, overfilled


def _open_slots(remaining: Mapping[tuple[int, str], int]) -> tuple[DraftSlot, ...]:
    return tuple(
        DraftSlot(team_id=team_id, slot_code=code, ordinal=ordinal)
        for (team_id, code), count in remaining.items()
        for ordinal in range(count)
    )


def analyze_draft_feasibility(
    *,
    team_ids: Collection[int],
    slot_targets: Mapping[str, int],
    players: Collection[EligiblePlayer],
    assignments: Collection[DraftAssignment] = (),
    hypothetical: DraftAssignment | None = None,
) -> DraftFeasibilityReport:
    """Analyze the remaining draft, optionally after one hypothetical pick."""

    all_assignments = (*assignments, *((hypothetical,) if hypothetical is not None else ()))
    remaining, overfilled = _remaining_capacity(
        team_ids=team_ids,
        slot_targets=slot_targets,
        assignments=all_assignments,
    )
    slots = _open_slots(remaining)
    assigned_player_ids = {assignment.player_id for assignment in all_assignments}
    available_players = tuple(player for player in players if player.player_id not in assigned_player_ids)
    slots_by_code = {
        code: tuple(slot for slot in slots if slot.slot_code == code) for code in _ordered_slot_codes(slot_targets)
    }
    eligible_slots = {
        player.player_id: tuple(
            slot
            for code in _ordered_slot_codes(slot_targets)
            if _slot_fits(player, code)
            for slot in slots_by_code[code]
        )
        for player in available_players
    }
    matching = maximum_bipartite_matching(
        candidates=tuple(player.player_id for player in available_players),
        slots=slots,
        eligible_slots=eligible_slots,
    )
    unmatched_codes = {slot.slot_code for slot in matching.unmatched_slots}
    blocking_players = tuple(
        player.player_id for player in available_players if any(_slot_fits(player, code) for code in unmatched_codes)
    )
    unmatched_counts = Counter(slot.slot_code for slot in matching.unmatched_slots)
    slot_deficits = tuple(
        SlotDeficit(
            slot_code=code,
            unmatched_slots=unmatched_counts[code],
            eligible_players=sum(_slot_fits(player, code) for player in available_players),
        )
        for code in _ordered_slot_codes(slot_targets)
        if unmatched_counts[code]
    )
    reason_code = "role_overfilled" if overfilled else ("role_shortage" if matching.unmatched_slots else None)
    return DraftFeasibilityReport(
        is_feasible=not overfilled and not matching.unmatched_slots,
        total_open_slots=len(slots),
        matched_slots=matching.matched_count,
        unmatched_slots=matching.unmatched_slots,
        slot_deficits=slot_deficits,
        blocking_player_ids=blocking_players,
        reason_code=reason_code,
    )


def evaluate_pick_options(
    *,
    team_id: int,
    team_ids: Collection[int],
    slot_targets: Mapping[str, int],
    players: Collection[EligiblePlayer],
    assignments: Collection[DraftAssignment] = (),
) -> tuple[DraftPickOption, ...]:
    """Return safe/blocked role choices for every available player."""

    remaining, _ = _remaining_capacity(
        team_ids=team_ids,
        slot_targets=slot_targets,
        assignments=assignments,
    )
    options: list[DraftPickOption] = []
    # Players with the same declared role set are interchangeable for the
    # feasibility question. Cache one forced-pick matching per role-set/role
    # pair; at the supported scale this reduces hundreds of equivalent graph
    # runs to at most 21 (seven non-empty subsets of three canonical roles).
    report_cache: dict[tuple[frozenset[HeroClass], HeroClass], tuple[int, DraftFeasibilityReport]] = {}
    for player in players:
        for role in HERO_TYPE_CLASSES:
            if role not in player.playable_roles:
                continue
            # A role a team can still take: its own role slot, or any free flex
            # slot. Only when both are gone is the option genuinely unavailable.
            if remaining.get((team_id, role.slot_code), 0) + remaining.get((team_id, FLEX_SLOT_CODE), 0) <= 0:
                options.append(
                    DraftPickOption(
                        player_id=player.player_id,
                        role=role,
                        is_safe=False,
                        reason_code="slot_filled",
                    )
                )
                continue
            cache_key = (player.playable_roles, role)
            cached = report_cache.get(cache_key)
            if cached is None:
                report = analyze_draft_feasibility(
                    team_ids=team_ids,
                    slot_targets=slot_targets,
                    players=players,
                    assignments=assignments,
                    hypothetical=DraftAssignment(player_id=player.player_id, team_id=team_id, slot_code=role.slot_code),
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
