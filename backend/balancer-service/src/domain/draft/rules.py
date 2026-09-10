"""Pure draft business rules: validation, seat ordering, pick-slot resolution,
role-edit validation. No database access, no async.

What is deliberately NOT here any more: deriving a player's roles or ranks.
``map_registration`` used to do that from the raw ``registration_role`` rows,
in parallel with tournament-service's own resolver -- one engine now answers
it (``shared.services.roster``) and every rule below takes the resolved
``PlayerRoster`` as an argument.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Final, Protocol, TypeVar

from shared.core.enums import (
    HERO_TYPE_CLASSES,
    DraftCaptainOrder,
    DraftFormat,
    DraftPickStatus,
    DraftPlayerStatus,
    DraftStatus,
    HeroClass,
)
from shared.core.errors import ApiHTTPException
from shared.domain.roster import PlayerRoster
from shared.domain.roster_shape import FLEX_SLOT_CODE, RosterShape
from shared.models.balancer.draft import DraftPick, DraftPlayer, DraftSession, DraftTeam
from src.domain.draft.entities import (
    DraftFeasibilityReport,
    DraftFeasibilityState,
    DraftResult,
    DraftSnapshot,
    EligiblePlayer,
    RoleEditPreview,
    SlotDecision,
)
from src.domain.draft.errors import err as _err
from src.domain.draft.feasibility import analyze_draft_feasibility, describe_role_deficits

__all__ = (
    "DELETABLE_STATUSES",
    "DYNAMIC_ROUND_RULES",
    "arm_clock",
    "available_player_from",
    "average_seat_order",
    "bump_seed_version",
    "is_on_clock_captain",
    "mark_role_shortage_paused",
    "order_captain_ids",
    "preview_role_addition",
    "resolve_pick_slot",
    "role_openings",
    "role_shortage_error",
    "round_seat_order",
    "team_slot_counts",
    "unranked_pool_error",
    "unsafe_pick_error",
    "validate_current_pick",
    "validate_draft_rounds",
    "validate_seed_version",
)

# Every other status is erasable; a LIVE/PAUSED draft has captains on a clock
# and must be cancelled first (services/draft/lifecycle.py::delete_session).
DELETABLE_STATUSES = (
    DraftStatus.SETUP.value,
    DraftStatus.READY.value,
    DraftStatus.COMPLETED.value,
    DraftStatus.CANCELLED.value,
)


# --- lifecycle / seeding -----------------------------------------------------


def validate_draft_rounds(*, rounds: int, shape: RosterShape) -> None:
    """A draft has exactly one pick per roster slot the captain does not fill."""
    if rounds != shape.draft_rounds:
        raise _err(
            "invalid_roster_shape",
            f"rounds must be {shape.draft_rounds}: the roster shape {shape.slots} has "
            f"{shape.team_size} slots and the captain already fills one",
            status_code=422,
        )


def validate_seed_version(draft_session: DraftSession, *, expected_version: int | None) -> None:
    if expected_version is not None and draft_session.version != expected_version:
        raise _err("draft_session_stale", "Draft setup changed; reload the seed preview", status_code=409)


def bump_seed_version(draft_session: DraftSession) -> None:
    draft_session.version = (draft_session.version or 0) + 1


def role_shortage_error(report: DraftFeasibilityReport) -> ApiHTTPException:
    details = describe_role_deficits(report)
    message = "Draft pool cannot fill every team role"
    if details:
        message = f"{message}: {details}"
    return _err("role_shortage", message, status_code=422)


def unranked_pool_error(rosters: Sequence[PlayerRoster]) -> ApiHTTPException:
    """Refuse to seat a registration the balancer cannot rank on any role.

    The old seeder labelled such a player ``damage`` with a NULL rank and let
    them into the pool, where autopick scored them 0 and took them last. There
    is no honest default: the fix is a rank in the balancer, so say so.
    """
    names = ", ".join(
        roster.battle_tag or roster.display_name or f"#{roster.registration_id}" for roster in rosters[:10]
    )
    more = f" and {len(rosters) - 10} more" if len(rosters) > 10 else ""
    return _err(
        "draft_pool_unranked",
        f"These pool registrations have no ranked role: {names}{more}. Set their ranks in the balancer, then seed.",
        status_code=422,
    )


# Round rules whose seat order is only known once the round starts: they rank
# teams by their live average, so seeding and any later resync leave the linear
# order in place and ``DraftSelectionService._apply_dynamic_round_order``
# re-seats the round on its first pick.
DYNAMIC_ROUND_RULES: Final[tuple[str, ...]] = ("team_avg_asc", "team_avg_desc")


class _Seat(Protocol):
    """What seat ordering reads off a team: its id and its seed position."""

    id: int
    draft_position: int


_SeatT = TypeVar("_SeatT", bound=_Seat)


def round_seat_order(
    seats: Sequence[_SeatT],
    *,
    fmt: DraftFormat,
    round_rules: Sequence[str | None],
    round_idx: int,
    captain_ranks: Mapping[int, int],
) -> list[_SeatT]:
    """Seat order for one round: who picks first, second, ... in it.

    ``seats`` is the seed order (position 1 first) and ``round_idx`` is 0-based.
    The single source of truth for what a rule MEANS, shared by seeding and
    ``DraftLifecycleService.resync_pick_order`` -- the two used to hold separate
    copies, which is how a rule changed after seeding could mean one thing in
    the wizard preview and another on the board.
    """
    if fmt == DraftFormat.SNAKE:
        return list(reversed(seats)) if round_idx % 2 == 1 else list(seats)
    if fmt != DraftFormat.CUSTOM:
        return list(seats)

    rule = round_rules[round_idx] if round_idx < len(round_rules) else None
    if rule == "reverse":
        return list(reversed(seats))
    if rule == "weakest_first":
        return sorted(seats, key=lambda t: (captain_ranks.get(t.id, -1), t.draft_position))
    if rule == "strongest_first":
        return sorted(seats, key=lambda t: (captain_ranks.get(t.id, -1), -t.draft_position), reverse=True)
    # "linear", a dynamic rule, an unknown value, or a hole left by an older
    # client: all keep the seed order here.
    return list(seats)


def average_seat_order(
    seats: Sequence[_SeatT],
    *,
    averages: Mapping[int, float],
    captain_ranks: Mapping[int, int],
    descending: bool,
) -> list[_SeatT]:
    """Seat order for a ``team_avg_*`` round: live average, captain, then seed.

    The direction lives in the key rather than in ``reverse=``, because
    ``reverse`` flips the WHOLE key: the seed tie-break would then run backwards
    under ``team_avg_desc`` and forwards under ``team_avg_asc``, so two teams on
    the same average would swap seats purely from the direction of the rule.

    Equal averages break by captain rank IN THE RULE'S DIRECTION -- under
    ``team_avg_asc`` the weaker captain picks first, exactly as the rule already
    does with the averages themselves, and mirrored under ``team_avg_desc``.
    Without it a tie fell through to the seed order, which is whatever order the
    organizer happened to tick the captains in (the pool lists them
    alphabetically), so an equal-average round was decided by battle tag.
    An unranked captain sorts as weakest, as in ``weakest_first``. Only teams
    that tie on BOTH keep the seed order, so the result stays deterministic.

    A team with no average yet sorts as 0.0. In practice every team has one --
    captains are seeded as PICKED players on their own roster -- so this only
    guards a team whose roster was emptied by hand.
    """
    direction = -1 if descending else 1
    return sorted(
        seats,
        key=lambda t: (
            direction * averages.get(t.id, 0.0),
            direction * captain_ranks.get(t.id, -1),
            t.draft_position,
        ),
    )


def order_captain_ids(
    entries: list[tuple[int, int | None]],
    strategy: DraftCaptainOrder,
    seed: int | None = None,
) -> list[int]:
    """Return captain ids in seat order (position 1 picks first).

    ``entries`` are (id, rank_value) in selection order. WEAKEST_FIRST sorts by
    ascending rank (unknown rank treated as weakest), STRONGEST_FIRST descending,
    RANDOM is a deterministic shuffle, MANUAL keeps selection order. Ties break by
    id for full determinism.
    """
    if strategy == DraftCaptainOrder.MANUAL:
        return [rid for rid, _ in entries]
    if strategy == DraftCaptainOrder.WEAKEST_FIRST:
        ordered = sorted(entries, key=lambda e: (e[1] if e[1] is not None else -1, e[0]))
        return [rid for rid, _ in ordered]
    if strategy == DraftCaptainOrder.STRONGEST_FIRST:
        ordered = sorted(entries, key=lambda e: (-(e[1] if e[1] is not None else -1), e[0]))
        return [rid for rid, _ in ordered]
    # RANDOM: deterministic Mulberry32 shuffle keyed by seed, so a preview and its
    # commit (same seed) always agree on the order.
    rng_seed = seed if seed is not None else 0
    state = rng_seed & 0xFFFFFFFF

    def _next() -> float:
        nonlocal state
        state = (state + 0x6D2B79F5) & 0xFFFFFFFF
        t = state
        t = ((t ^ (t >> 15)) * (t | 1)) & 0xFFFFFFFF
        t = (t ^ (t + (((t ^ (t >> 7)) * (t | 61)) & 0xFFFFFFFF))) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296.0

    ordered = [rid for rid, _ in entries]
    for i in range(len(ordered) - 1, 0, -1):
        j = int(_next() * (i + 1))
        ordered[i], ordered[j] = ordered[j], ordered[i]
    return ordered


def arm_clock(pick: DraftPick, pick_time_seconds: int, now: datetime) -> None:
    pick.status = DraftPickStatus.ON_CLOCK.value
    pick.clock_started_at = now
    pick.clock_expires_at = now + timedelta(seconds=pick_time_seconds)
    pick.clock_remaining_ms = None


# --- pick selection -----------------------------------------------------------


def team_slot_counts(
    players: Collection[DraftPlayer],
    picks: Collection[DraftPick],
    team_id: int,
    shape: RosterShape,
    rosters: Mapping[int, PlayerRoster],
) -> dict[str, int]:
    """Filled-slot counts for one team, computed from the request snapshot.

    Role slots are filled by the drafted role -- a resolved pick's frozen
    ``target_role`` wins over the player's current lead role, so off-role picks
    count against the drafted role. Every remaining picked player occupies a flex
    slot: a role slot that is already full, a role the shape has no slot for, and
    a player with no usable role all land there, which is exactly the spill rule
    ``feasibility._remaining_capacity`` applies to the same rows.
    """
    pick_by_player_id = {
        pk.picked_player_id: pk
        for pk in picks
        if pk.picked_player_id is not None
        and pk.draft_team_id == team_id
        and pk.status in (DraftPickStatus.COMPLETED.value, DraftPickStatus.AUTOPICKED.value)
    }
    role_slot_targets = shape.role_slots
    counts = dict.fromkeys(shape.slots, 0)
    taken = 0
    for p in players:
        if p.drafted_by_team_id != team_id or p.status != DraftPlayerStatus.PICKED.value:
            continue
        taken += 1
        pk = pick_by_player_id.get(p.id)
        code = pk.target_role if (pk and pk.target_role) else _lead_slot_code(rosters.get(p.id))
        if code in role_slot_targets and counts[code] < role_slot_targets[code]:
            counts[code] += 1
    if FLEX_SLOT_CODE in counts:
        counts[FLEX_SLOT_CODE] = min(
            shape.flex_slots,
            max(0, taken - sum(counts[code] for code in role_slot_targets)),
        )
    return counts


def _lead_slot_code(roster: PlayerRoster | None) -> str | None:
    lead = roster.primary if roster is not None else None
    return lead.role.slot_code if lead is not None else None


def role_openings(shape: RosterShape, counts: Mapping[str, int]) -> dict[HeroClass, int]:
    """How many more slots each role can still take on this team.

    A role lands either in its own remaining role slot or in any free flex slot,
    so the two capacities add up. ``fit`` only asks whether a role is still open
    and the ``slot_filled`` guard only asks whether it is zero, so one number
    serves both.
    """
    targets = shape.slots
    free_flex = max(0, targets.get(FLEX_SLOT_CODE, 0) - counts.get(FLEX_SLOT_CODE, 0))
    return {
        role: max(0, targets.get(role.slot_code, 0) - counts.get(role.slot_code, 0)) + free_flex
        for role in HERO_TYPE_CLASSES
    }


def validate_current_pick(draft_session: DraftSession, pick: DraftPick) -> None:
    if draft_session.status != DraftStatus.LIVE.value:
        raise _err("draft_not_live", "Draft is not live")
    if pick.id != draft_session.current_pick_id or pick.status != DraftPickStatus.ON_CLOCK.value:
        raise _err("pick_not_on_clock", "This is not the current on-clock pick")


def available_player_from(snapshot: DraftSnapshot, player_id: int) -> DraftPlayer:
    player = next((p for p in snapshot.players if p.id == player_id), None)
    if player is None:
        raise _err("player_not_found", "Player not in this draft", status_code=404)
    if player.status != DraftPlayerStatus.AVAILABLE.value:
        raise _err("player_unavailable", "Player is not available")
    return player


def resolve_pick_slot(
    shape: RosterShape,
    counts: Mapping[str, int],
    roster: PlayerRoster | None,
    target_role: HeroClass | None,
) -> SlotDecision:
    """Validate one pick against the shape and this team's already filled slots.

    Shared by select, autopick and override so the three cannot drift. Raises
    ``illegal_role`` when the player cannot play the requested role,
    ``player_unranked`` when the balancer ranks them on no role at all, and
    ``slot_filled`` when neither a matching role slot nor a flex slot is left.
    """
    if roster is None or not roster.is_draftable:
        raise _err(
            "player_unranked",
            "This player has no ranked role in the balancer and cannot be picked",
            status_code=422,
        )
    # A role-less roster has no role to validate against, so a requested role
    # carries no meaning: drop it instead of rejecting the request.
    requested = target_role if shape.has_role_slots else None
    if not roster.covers(requested):
        raise _err("illegal_role", "Player cannot play the requested role", status_code=422)
    lead = roster.primary
    if lead is None:  # unreachable while ``is_draftable`` holds; never guess a role
        raise _err(
            "player_unranked",
            "This player has no ranked role in the balancer and cannot be picked",
            status_code=422,
        )
    role = requested or lead.role
    if role_openings(shape, counts).get(role, 0) <= 0:
        raise _err(
            "slot_filled",
            f"No roster slot left for {role.slot_code} on this team",
            status_code=422,
        )
    return SlotDecision(role=role, recorded_role=role.slot_code if shape.has_role_slots else None)


def unsafe_pick_error(report: DraftFeasibilityReport) -> ApiHTTPException:
    details = describe_role_deficits(report) or "unknown role deficit"
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


def is_on_clock_captain(
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


# --- role edits ---------------------------------------------------------------
#
# An emergency role now lands on the REGISTRATION, not on a draft-local copy:
# the balancer is the only writer of roles and ranks, so the board, the pool
# verdict and the algorithm all see the edit at once. What is validated here is
# only whether this draft may accept one.

_EDITABLE_STATUSES = {
    DraftStatus.SETUP.value,
    DraftStatus.READY.value,
    DraftStatus.PAUSED.value,
}


def validate_role_edit_request(
    draft_session: DraftSession,
    player: DraftPlayer,
    roster: PlayerRoster | None,
    *,
    role: HeroClass,
    rank_value: int,
    reason: str,
    expected_version: int,
) -> str:
    """Validate both preview and commit; return the normalized private reason.

    ``rank_value`` is required and has no "confirm it is missing" escape hatch:
    a role without a rank is not playable, so adding one would change nothing.
    """

    if draft_session.status not in _EDITABLE_STATUSES:
        raise _err("role_edit_requires_pause", "Pause the draft before editing a player role", status_code=409)
    if player.session_id != draft_session.id:
        raise _err("player_not_found", "Player is not in this draft session", status_code=404)
    if player.status != DraftPlayerStatus.AVAILABLE.value:
        raise _err("player_not_available", "Only a remaining available player can receive an emergency role")
    if player.version != expected_version:
        raise _err("draft_player_stale", "Player snapshot changed; reload the role-edit preview", status_code=409)
    if roster is not None and role in roster.playable_roles:
        raise _err("role_already_exists", f"Player already plays {role.slot_code}", status_code=409)
    if rank_value <= 0:
        raise _err("role_rank_required", "An emergency role needs a rank; a rankless role is not playable")
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise _err("role_edit_reason_required", "A private audit reason is required")
    return normalized_reason


def preview_role_addition(
    state: DraftFeasibilityState,
    *,
    player_id: int,
    role: HeroClass,
) -> RoleEditPreview:
    before = analyze_draft_feasibility(
        team_ids=state.team_ids,
        slot_targets=state.slot_targets,
        players=state.players,
        assignments=state.assignments,
    )
    found = False
    updated_players: list[EligiblePlayer] = []
    for player in state.players:
        if player.player_id == player_id:
            found = True
            updated_players.append(
                EligiblePlayer(
                    player_id=player.player_id,
                    playable_roles=player.playable_roles | {role},
                )
            )
        else:
            updated_players.append(player)
    if not found:
        raise _err("player_not_available", "Player is not available in the remaining draft pool", status_code=404)
    after = analyze_draft_feasibility(
        team_ids=state.team_ids,
        slot_targets=state.slot_targets,
        players=tuple(updated_players),
        assignments=state.assignments,
    )
    return RoleEditPreview(before=before, after=after)
