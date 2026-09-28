"""Phase selection, round resolution and the v1 -> v2 conversion.

The v1 sequence generators live here now (they moved out of
``tournament-service/.../veto_session.py`` unchanged): a ruleset phase with a
``generator`` expands to the very same token list the flat v1 config produced,
so a migrated bracket/slot config keeps its exact step order.

Design: ``docs/plans/2026-09-28-pick-ban-constructor.md`` §1, §3, §11.
"""

from __future__ import annotations

from typing import Any

from shared.core.enums import FirstBanRotation

from .registry import RoundCtx, evaluate
from .schema import Constraint, DisputeRule, Phase, ResolvedStep, Ruleset, Step

#: How many lead bans a bracket sequence spends before its picks.
LEAD_BANS = 2

_V1_ACTIONS = {"ban": "ban", "pick": "pick", "protect": "protect"}


def build_sequence_for_best_of(best_of: int, pool_size: int) -> list[str]:
    """Generate a side-agnostic sequence that plays exactly ``best_of`` maps."""
    if pool_size < 1:
        return []
    if best_of <= 1:
        tokens = ["ban_first" if index % 2 == 0 else "ban_second" for index in range(pool_size - 1)]
        tokens.append("decider")
        return tokens

    played = min(best_of, pool_size)
    picks = played - 1 if played % 2 else played
    bans = max(0, min(LEAD_BANS, pool_size - played))

    tokens = ["ban_first" if index % 2 == 0 else "ban_second" for index in range(bans)]
    tokens.extend("pick_first" if index % 2 == 0 else "pick_second" for index in range(picks))
    if played % 2:
        tokens.append("decider")
    return tokens


def build_slot_sequence(candidate_counts: list[int], *, rotation: str) -> list[str]:
    """Generate the side-agnostic sequence for a slot-mode config."""
    tokens: list[str] = []
    for slot_index, candidate_count in enumerate(candidate_counts):
        opens_first = rotation != FirstBanRotation.ALTERNATE or slot_index % 2 == 0
        opener, responder = ("ban_first", "ban_second") if opens_first else ("ban_second", "ban_first")
        tokens.extend(opener if ban_index % 2 == 0 else responder for ban_index in range(candidate_count - 1))
        tokens.append("decider")
    return tokens


# ── v1 -> v2 ────────────────────────────────────────────────────────────────


def steps_from_v1_tokens(tokens: list[str], *, kind: str) -> list[Step]:
    """Every v1 token becomes a count-1, open, single-actor step (§11).

    A hero sequence drops ``decider``: "whatever survived is the pick" is a
    map-veto idea, and a hero round leaves the whole unbanned pool playable.
    """
    steps: list[Step] = []
    for index, token in enumerate(tokens):
        if token == "decider":
            if kind == "hero":
                continue
            steps.append(_v1_step(f"s{index + 1}", action="decider", actors="system"))
            continue
        action, _, actors = token.rpartition("_")
        if action not in _V1_ACTIONS or actors not in ("first", "second"):
            raise ValueError(f"unknown pick-ban token {token!r}")
        steps.append(_v1_step(f"s{index + 1}", action=action, actors=actors))
    return steps


def _v1_step(step_id: str, *, action: str, actors: str) -> Step:
    return Step(
        id=step_id,
        action=action,  # type: ignore[arg-type]
        actors=actors,  # type: ignore[arg-type]
        count=1,
        min=None,
        blind=False,
        target=None,
        #: v1 bans lasted exactly the map they were made on.
        lifetime=1 if action == "ban" else None,
        timer_seconds=None,
        on_timeout=None,
        dispute=DisputeRule(enabled=False, max=0),
        eligible={},
        constraints=[],
    )


def ruleset_from_v1(
    *,
    kind: str,
    mode: str,
    preset: str | None,
    sequence: list[str],
    no_repeat_scope: str | None,
    unique_attribute: str | None,
    turn_timer_seconds: int | None,
) -> Ruleset:
    """Convert a v1 ``PickBanConfig`` into the equivalent ruleset (§11).

    Behaviour-preserving by construction: the same steps in the same order, the
    ledger's no-repeat scope expressed as a ``banned_by`` filter, and the
    role-uniqueness flag as a ``max_per_group`` constraint.
    """
    generator: str | None = None
    if kind == "map":
        if mode == "slots":
            generator = "slot_veto"
        elif preset not in (None, "custom"):
            generator = "bracket"

    steps = [] if generator else steps_from_v1_tokens(list(sequence or []), kind=kind)
    pool_filter: dict[str, Any] = {}

    if no_repeat_scope == "encounter":
        pool_filter = {"NOT": {"type": "banned_by", "params": {"by": "any", "scope": "series"}}}
    elif no_repeat_scope == "encounter_same_side":
        for step in steps:
            if step.action == "ban":
                step.eligible = {"NOT": {"type": "banned_by", "params": {"by": "self", "scope": "series"}}}

    if unique_attribute == "role":
        for step in steps:
            if step.action in ("ban", "protect"):
                step.constraints = [
                    *step.constraints,
                    Constraint(type="max_per_group", params={"max": 1, "scope": "round", "group": None}),
                ]

    phase = Phase(
        id="main",
        name=None,
        when={},
        pool_filter=pool_filter,
        generator=generator,  # type: ignore[arg-type]
        steps=steps,
    )
    return Ruleset(version=2, timer_seconds=turn_timer_seconds, on_timeout="random_fill", phases=[phase])


# ── phase selection / round resolution ──────────────────────────────────────


def phase_matches(phase: Phase, ctx: RoundCtx) -> bool:
    return evaluate(phase.when, ctx)


def select_phase(ruleset: Ruleset, ctx: RoundCtx) -> Phase | None:
    """The first phase whose ``when`` matches the round; ``None`` when the
    ruleset says nothing about this map."""
    for phase in ruleset.phases:
        if phase_matches(phase, ctx):
            return phase
    return None


def resolve_sides(actors: str, *, opener: str, prev_outcome: str | None) -> list[str]:
    """Actor resolution (§1). ``winner_prev``/``loser_prev`` fall back to
    first/second when there is no previous round or it was drawn/unknown."""
    other = "away" if opener == "home" else "home"
    match actors:
        case "first":
            return [opener]
        case "second":
            return [other]
        case "both":
            return [opener, other]
        case "home" | "away":
            return [actors]
        case "system":
            return ["system"]
        case "winner_prev":
            return [prev_outcome] if prev_outcome in ("home", "away") else [opener]
        case "loser_prev":
            if prev_outcome in ("home", "away"):
                return ["away" if prev_outcome == "home" else "home"]
            return [other]
    raise ValueError(f"unknown actors {actors!r}")


def resolve_round(
    ruleset: Ruleset,
    *,
    kind: str,
    round: int | None,
    start_index: int,
    opener: str,
    prev_outcome: str | None = None,
    best_of: int = 1,
    pool_size: int = 0,
    candidate_count: int = 0,
) -> list[ResolvedStep]:
    """The resolved steps one round of this ruleset adds to the session.

    ``round is None`` is flat mode (one sequence settles the whole series); the
    phase is still selected as if it were map 1, and the resolved steps carry
    ``round: null`` exactly as v1 entries do.
    """
    ctx = RoundCtx(round=round if round is not None else 1, best_of=max(best_of, 1), kind=kind)
    phase = select_phase(ruleset, ctx)
    if phase is None:
        return []

    if phase.generator == "bracket":
        steps = steps_from_v1_tokens(build_sequence_for_best_of(ctx.best_of, pool_size), kind=kind)
    elif phase.generator == "slot_veto":
        # FIXED rotation on purpose: one generated round is one slot, and the
        # opener already alternates per round through `first_ban_rotation`.
        steps = steps_from_v1_tokens(
            build_slot_sequence([candidate_count], rotation=FirstBanRotation.FIXED.value), kind=kind
        )
    else:
        steps = list(phase.steps)

    resolved: list[ResolvedStep] = []
    for step in steps:
        if step.action == "decider" and kind != "map":
            continue
        count = 1 if step.action == "decider" else step.count
        resolved.append(
            ResolvedStep(
                index=start_index + len(resolved),
                round=round,
                phase_id=phase.id,
                step_id=step.id,
                action=step.action,
                sides=resolve_sides(step.actors, opener=opener, prev_outcome=prev_outcome),  # type: ignore[arg-type]
                count=count,
                min=count if step.min is None else min(step.min, count),
                blind=step.blind,
                target=step.target,
                lifetime=step.lifetime if step.action == "ban" else None,
                timer_seconds=step.timer_seconds if step.timer_seconds is not None else ruleset.timer_seconds,
                on_timeout=step.on_timeout or ruleset.on_timeout,
                dispute=step.dispute,
                eligible=step.eligible,
                constraints=list(step.constraints),
            )
        )
    return resolved
