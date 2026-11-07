"""Series preview: what each map of a Bo1/2/3/5 would actually look like.

Answers the question the constructor exists for — "how many heroes are left on
map 5?" — before a tournament runs on the rules.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from shared.disciplines import discipline as discipline_spec

from .compile import resolve_round, select_phase
from .registry import RoundCtx, normalize_group
from .schema import Issue, ResolvedStep, Ruleset, RulesetError, parse_ruleset
from .validate import validate_ruleset

#: Below this many playable items in a group the rules are a trap, not a draft.
MIN_REMAINING_WARNING = 2

#: Issue code of a progressive map pool too small for the series: the save gate refuses it.
POOL_EXHAUSTED = "pool_exhausted"

#: A preview has no encounter, so the steps resolve against two stand-in
#: participations: only HOW MANY of them a step spends items for matters here.
PREVIEW_PARTICIPANTS = (1, 2)


def preview_series(
    ruleset: Any,
    *,
    kind: str,
    discipline: str,
    mode: str = "pool",
    best_of: int = 3,
    pool_groups: Mapping[str, int] | None = None,
    roster_slots: Mapping[str, int] | None = None,
    pool_size: int | None = None,
) -> dict[str, Any]:
    """Resolve every map of a ``best_of`` series and count the damage.

    ``pool_groups`` is ``{group: item count}`` of the configured pool (for a
    hero pool: heroes per class). ``worst_case_remaining`` is per group and
    only reported for the hero kind — a map pool has no group budget to blow.
    ``pool_size`` is the number of items in the pool; it defaults to the grouped
    total, which is only right when every item has a group.

    ``roster_slots`` is ``{role: players per team}``. Without it a per-player
    ban step is counted as if all of its bans could hit one role; with it the
    rules' own arithmetic applies — one ban per opponent player, each matching
    that player's role, so a role can absorb at most as many bans as the team
    has players in it. Keys are matched case-insensitively; roles that are not
    pool groups are ignored.
    """
    try:
        parsed = ruleset if isinstance(ruleset, Ruleset) else parse_ruleset(ruleset)
    except RulesetError as exc:
        return {"maps": [], "issues": [issue.to_json() for issue in exc.issues]}

    issues = [
        issue
        for issue in validate_ruleset(parsed.to_json(), kind=kind, mode=mode, discipline=discipline)
        if issue.severity == "error"
    ]
    if issues:
        return {"maps": [], "issues": [issue.to_json() for issue in issues]}

    groups = dict(pool_groups or {})
    roster = {
        normalized: int(count)
        for role, count in (roster_slots or {}).items()
        if (normalized := normalize_group(role)) and int(count) > 0
    }
    sides = dict(zip(discipline_spec(discipline).sides, PREVIEW_PARTICIPANTS, strict=False))
    # The pool's cardinality is its own fact: an item with no group (a map whose game has no modes, a champion
    # without a class) still takes part in the series, it just belongs to no group budget.
    pool_size = sum(groups.values()) if pool_size is None else pool_size
    worst: dict[str, tuple[int, int]] = {}  # group -> (fewest remaining, the map it happens on)
    #: Progressive map pool: the first map whose steps need more maps than the series has left (map, needed, left).
    exhausted: tuple[int, int, int] | None = None
    maps: list[dict[str, Any]] = []
    #: round -> (group -> bans that round can land on it), and the round's steps.
    per_round: dict[int, list[tuple[ResolvedStep, dict[str | None, int]]]] = {}

    for map_index in range(1, max(best_of, 1) + 1):
        ctx = RoundCtx(round=map_index, best_of=max(best_of, 1), kind=kind)
        phase = select_phase(parsed, ctx)
        steps = (
            resolve_round(
                parsed,
                kind=kind,
                round=map_index,
                start_index=0,
                participants=PREVIEW_PARTICIPANTS,
                opener=PREVIEW_PARTICIPANTS[0],
                sides=sides,
                best_of=max(best_of, 1),
                pool_size=pool_size,
                candidate_count=pool_size,
            )
            if phase is not None
            else []
        )
        per_round[map_index] = [(step, _group_caps(step, groups, roster)) for step in steps if step.action == "ban"]

        max_new_bans = sum(step.count * len(step.actors) for step in steps if step.action == "ban")
        max_active_bans = sum(
            step.count * len(step.actors)
            for round_number, rows in per_round.items()
            for step, _ in rows
            if _covers(round_number, step, map_index)
        )
        if kind == "map" and mode == "progressive" and pool_size > 0 and exhausted is None:
            # Every earlier map was played once and drops out, and so does every earlier ban still in force.
            carried = sum(
                step.count * len(step.actors)
                for round_number, rows in per_round.items()
                if round_number < map_index
                for step, _ in rows
                if _covers(round_number, step, map_index)
            )
            left = pool_size - carried - (map_index - 1)
            needed = sum(step.count * max(len(step.actors), 1) for step in steps if step.action != "side_pick")
            if needed > left:
                exhausted = (map_index, needed, left)

        remaining: dict[str, int] | None = None
        if kind == "hero" and groups:
            remaining = {}
            for group, size in groups.items():
                spent = sum(
                    caps.get(group, 0)
                    for round_number, rows in per_round.items()
                    for step, caps in rows
                    if _covers(round_number, step, map_index)
                )
                left = max(0, size - spent)
                remaining[group] = left
                if group not in worst or left < worst[group][0]:
                    worst[group] = (left, map_index)

        maps.append(
            {
                "map_index": map_index,
                "phase_id": phase.id if phase is not None else None,
                "steps": [step.to_json() for step in steps],
                "max_new_bans": max_new_bans,
                "max_active_bans": max_active_bans,
                "worst_case_remaining": remaining,
            }
        )

        if phase is not None and phase.generator == "bracket":
            # A bracket settles the WHOLE series in one flat sequence: there is
            # no second round to preview.
            break

    warnings = [
        Issue(
            "phases",
            "group_nearly_exhausted",
            "warning",
            f"map {map_index} can leave only {left} {group} hero(es) playable",
        )
        for group, (left, map_index) in sorted(worst.items())
        if left < MIN_REMAINING_WARNING
    ]
    if exhausted is not None:
        map_index, needed, left = exhausted
        warnings.append(
            Issue(
                "phases",
                POOL_EXHAUSTED,
                "error",
                f"map {map_index} needs {needed} map(s) but only {max(left, 0)} are left in the pool",
            )
        )
    return {"maps": maps, "issues": [issue.to_json() for issue in warnings]}


def _covers(round_number: int, step: ResolvedStep, map_index: int) -> bool:
    """Whether a ban made on ``round_number`` is still active on ``map_index``."""
    if round_number > map_index:
        return False
    return step.lifetime is None or round_number + step.lifetime > map_index


def _group_caps(step: ResolvedStep, groups: Mapping[str, int], roster: Mapping[str, int]) -> dict[str | None, int]:
    """Worst case: how many of this step's bans can all land on ONE group.

    Bounded by any ``max_per_group`` that applies to it, and — when the step
    bans one hero per opponent player and every hero must match that player's
    role — by how many players the team fields in the role.
    """
    caps: dict[str | None, int] = {}
    rules = [
        (
            int(constraint.params.get("max", 1)),
            str(constraint.params.get("scope", "step")),
            constraint.params.get("group"),
        )
        for constraint in step.constraints
        if constraint.type == "max_per_group"
    ]
    per_player = (
        step.target == "opponent_player"
        and any(constraint.type == "one_per_target" for constraint in step.constraints)
        and _requires_role_match(step.eligible)
    )
    for group in groups:
        limits = [
            maximum
            for maximum, _scope, constrained in rules
            if constrained is None or str(constrained).lower() == group.lower()
        ]
        if per_player and roster:
            # A role-less (flex) player matches every hero, so they widen the
            # ceiling of every group rather than any one of them.
            limits.append(roster.get(normalize_group(group) or "", 0) + roster.get("flex", 0))
        caps[group] = min([step.count, *limits]) * len(step.actors)
    return caps


def _requires_role_match(eligible: Mapping[str, Any] | None) -> bool:
    """Whether every item of the step is forced to match its target's role —
    the leaf alone, or one arm of a top-level ``AND`` (anything else, including
    an ``OR`` or a ``NOT``, may let a non-matching hero through)."""
    if not eligible:
        return False
    if eligible.get("type") == "target_role_match":
        return True
    children = eligible.get("AND")
    if not isinstance(children, list):
        return False
    return any(isinstance(child, dict) and child.get("type") == "target_role_match" for child in children)
