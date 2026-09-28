"""Runtime semantics over submissions (§5): cursor, eligibility, validation,
projection, reveal, undo and dispute.

Pure functions over two structural protocols, so the SQLAlchemy rows satisfy
them without this module importing a model. Submissions are the action log and
the only source of truth; ``pick_ban_entry`` is a projection this module
recomputes after every mutation.

Design: ``docs/plans/2026-09-28-pick-ban-constructor.md`` §5, §6.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from random import Random
from typing import Any, Protocol

from .registry import AppliedItem, History, ItemCtx, evaluate, normalize_group
from .schema import ResolvedStep

DRAFT = "draft"
LOCKED = "locked"
REVEALED = "revealed"
VOIDED = "voided"

AVAILABLE = "available"
PICKED = "picked"
BANNED = "banned"
PROTECTED = "protected"

#: ``pick_ban_entry.picked_by`` marker for anything the engine resolved itself.
SYSTEM_PICKED_BY = "decider"


class SubmissionLike(Protocol):
    """One side's action on one step (``tournament.pick_ban_submission``)."""

    step_index: int
    side: str
    attempt: int
    state: str
    items_json: list[dict[str, Any]]
    locked_at: datetime | None
    revealed_at: datetime | None


class EntryLike(Protocol):
    """One row of the round's board (``tournament.pick_ban_entry``)."""

    item_id: int
    round: int | None
    order: int
    action_index: int | None
    picked_by: str | None
    protected_by: str | None
    status: str
    carried_from_round: int | None


@dataclass(frozen=True, slots=True)
class TargetPlayer:
    player_id: int
    #: Roster role, lowercase (``tank``/``damage``/``support``/``flex``) or None.
    role: str | None


@dataclass(frozen=True, slots=True)
class RuntimeCtx:
    """Everything the rules read that is not the step itself.

    ``available_item_ids`` are the round's entries still available (carried
    bans are not among them); ``targets`` maps an ACTING side to the players it
    may name — i.e. the opponent's roster.
    """

    kind: str
    round: int | None = None
    best_of: int = 1
    available_item_ids: tuple[int, ...] = ()
    groups: Mapping[int, str | None] = field(default_factory=dict)
    history: History = History()
    targets: Mapping[str, Sequence[TargetPlayer]] = field(default_factory=dict)

    def group_of(self, item_id: int) -> str | None:
        return normalize_group(self.groups.get(item_id))

    def targets_for(self, side: str) -> tuple[TargetPlayer, ...]:
        return tuple(self.targets.get(side, ()))


@dataclass(frozen=True, slots=True)
class EligibleSet:
    item_ids: tuple[int, ...]
    #: Keyed by target player id when the step names a target, else ``None``.
    by_target: dict[int, tuple[int, ...]] | None

    def to_json(self) -> dict[str, Any]:
        return {
            "item_ids": list(self.item_ids),
            "by_target": (
                {str(player_id): list(items) for player_id, items in self.by_target.items()}
                if self.by_target is not None
                else None
            ),
        }


@dataclass(frozen=True, slots=True)
class CarriedBan:
    item_id: int
    side: str
    from_round: int


@dataclass(frozen=True, slots=True)
class DisputeState:
    available: bool
    step_index: int | None
    attempts_used: int
    max: int

    def to_json(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "step_index": self.step_index,
            "attempts_used": self.attempts_used,
            "max": self.max,
        }


# ── submissions ─────────────────────────────────────────────────────────────


def current_attempt(submissions: Iterable[SubmissionLike], step_index: int) -> int:
    """The attempt a step is on: 1 until a dispute or admin reopen bumps it."""
    attempts = [row.attempt for row in submissions if row.step_index == step_index]
    return max(attempts) if attempts else 1


def side_submission(submissions: Iterable[SubmissionLike], step_index: int, side: str) -> SubmissionLike | None:
    """A side's live submission for a step: its row at the current attempt,
    unless that row was voided."""
    attempt = current_attempt(submissions, step_index)
    for row in submissions:
        if row.step_index == step_index and row.side == side and row.attempt == attempt and row.state != VOIDED:
            return row
    return None


def current_step(steps: Sequence[ResolvedStep], submissions: Iterable[SubmissionLike]) -> ResolvedStep | None:
    """The first step some acting side has not revealed yet; ``None`` once the
    resolved sequence is exhausted."""
    rows = list(submissions)
    for step in steps:
        for side in step.sides:
            row = side_submission(rows, step.index, side)
            if row is None or row.state != REVEALED:
                return step
    return None


def _items_of(submission: SubmissionLike) -> list[dict[str, Any]]:
    return [dict(item) for item in (submission.items_json or [])]


def applied_items(steps: Sequence[ResolvedStep], submissions: Iterable[SubmissionLike]) -> list[AppliedItem]:
    """What the board shows, in application order: revealed submissions plus
    the live drafts of OPEN steps (an open step's items are public at once)."""
    rows = list(submissions)
    applied: list[AppliedItem] = []
    for step in steps:
        for side in step.sides:
            row = side_submission(rows, step.index, side)
            if row is None:
                continue
            if row.state != REVEALED and (step.blind or row.state not in (DRAFT, LOCKED)):
                continue
            for item in _items_of(row):
                applied.append(
                    AppliedItem(
                        step_index=step.index,
                        round=step.round,
                        side=side,
                        action=step.action,
                        item_id=int(item["item_id"]),
                    )
                )
    return applied


def history_of(steps: Sequence[ResolvedStep], submissions: Iterable[SubmissionLike]) -> History:
    """Applied items as the condition leaves read them."""
    return History(items=tuple(applied_items(steps, submissions)))


def visible_submissions(
    steps: Sequence[ResolvedStep], submissions: Iterable[SubmissionLike], viewer_side: str | None
) -> list[SubmissionLike]:
    """Blind privacy (D4): the server never serializes another side's unrevealed
    draft. Revealed rows, every row of an open step, and the viewer's own."""
    by_index = {step.index: step for step in steps}
    rows = list(submissions)
    visible: list[SubmissionLike] = []
    for row in rows:
        if row.state == VOIDED or row.attempt != current_attempt(rows, row.step_index):
            continue
        step = by_index.get(row.step_index)
        if row.state == REVEALED or (step is not None and not step.blind) or row.side == viewer_side:
            visible.append(row)
    return visible


def step_progress(step: ResolvedStep, submissions: Iterable[SubmissionLike]) -> dict[str, dict[str, Any]]:
    """Per acting side ``{locked, filled}`` — reported even while a blind draft
    itself stays hidden."""
    rows = list(submissions)
    progress: dict[str, dict[str, Any]] = {}
    for side in step.acting_sides:
        row = side_submission(rows, step.index, side)
        progress[side] = {
            "locked": row is not None and row.state in (LOCKED, REVEALED),
            "filled": len(_items_of(row)) if row is not None else 0,
        }
    return progress


def ready_to_reveal(step: ResolvedStep, submissions: Iterable[SubmissionLike]) -> bool:
    """True once every side of the step has a locked (or already revealed)
    submission — the moment a blind step opens up."""
    rows = list(submissions)
    for side in step.sides:
        row = side_submission(rows, step.index, side)
        if row is None or row.state not in (LOCKED, REVEALED):
            return False
    return True


# ── projection ──────────────────────────────────────────────────────────────


def project_entries(
    entries: Sequence[EntryLike], steps: Sequence[ResolvedStep], submissions: Iterable[SubmissionLike]
) -> None:
    """Recompute the board from the action log (D2).

    Deterministic and idempotent: reset every non-carried entry, then replay
    the applied items in order. Carried bans are fixed and never touched.
    """
    for entry in entries:
        if entry.carried_from_round is None:
            entry.status = AVAILABLE
            entry.picked_by = None
            entry.protected_by = None
            entry.action_index = None

    by_round: dict[tuple[int | None, int], list[EntryLike]] = {}
    for entry in entries:
        if entry.carried_from_round is None:
            by_round.setdefault((entry.round, entry.item_id), []).append(entry)

    action_index = 0
    picked = 0
    for applied in applied_items(steps, submissions):
        candidates = by_round.get((applied.round, applied.item_id)) or by_round.get((None, applied.item_id))
        if not candidates:
            continue
        entry = candidates[0]
        side = SYSTEM_PICKED_BY if applied.side == "system" else applied.side
        match applied.action:
            case "ban":
                if entry.status != AVAILABLE:
                    continue  # already banned by the other side of a blind step (D8), or protected
                entry.status = BANNED
                entry.picked_by = side
            case "protect":
                if entry.status != AVAILABLE:
                    continue
                entry.status = PROTECTED
                entry.protected_by = side
            case "pick" | "decider":
                if entry.status != AVAILABLE:
                    continue
                picked += 1
                entry.status = PICKED
                entry.picked_by = SYSTEM_PICKED_BY if applied.action == "decider" else side
                entry.order = picked
            case _:
                continue
        entry.action_index = action_index
        action_index += 1


def carried_bans(steps: Sequence[ResolvedStep], submissions: Iterable[SubmissionLike], round: int) -> list[CarriedBan]:
    """Bans of earlier rounds still active on ``round``: ``lifetime is null or
    r + lifetime > round``. First side wins on duplicates."""
    rows = list(submissions)
    seen: dict[int, CarriedBan] = {}
    for step in steps:
        if step.action != "ban" or step.round is None or step.round >= round:
            continue
        if step.lifetime is not None and step.round + step.lifetime <= round:
            continue
        for side in step.sides:
            row = side_submission(rows, step.index, side)
            if row is None or row.state != REVEALED:
                continue
            for item in _items_of(row):
                item_id = int(item["item_id"])
                seen.setdefault(
                    item_id,
                    CarriedBan(
                        item_id=item_id,
                        side=SYSTEM_PICKED_BY if side == "system" else side,
                        from_round=step.round,
                    ),
                )
    return list(seen.values())


# ── eligibility ─────────────────────────────────────────────────────────────


def _item_ctx(step: ResolvedStep, side: str, ctx: RuntimeCtx, item_id: int, target_role: str | None) -> ItemCtx:
    return ItemCtx(
        item_id=item_id,
        group=ctx.group_of(item_id),
        kind=ctx.kind,
        side=None if side == "system" else side,
        target_role=target_role,
        round=ctx.round,
        history=replace(ctx.history, current_step_index=step.index),
    )


def filter_pool(pool_filter: Mapping[str, Any] | None, item_ids: Sequence[int], ctx: RuntimeCtx) -> list[int]:
    """The configured candidates a round may actually open with: a pool filter
    has no acting side and no target, so only absolute leaves apply (validation
    enforces that)."""
    return [
        item_id
        for item_id in item_ids
        if evaluate(
            pool_filter,
            ItemCtx(
                item_id=item_id,
                group=ctx.group_of(item_id),
                kind=ctx.kind,
                side=None,
                target_role=None,
                round=ctx.round,
                history=ctx.history,
            ),
        )
    ]


def eligible_items(step: ResolvedStep, side: str, ctx: RuntimeCtx) -> EligibleSet:
    """What ``side`` may choose on ``step`` right now. For a target step the
    answer is per opponent player, and ``item_ids`` is their union."""
    if step.target is None:
        items = tuple(
            item_id
            for item_id in ctx.available_item_ids
            if evaluate(step.eligible, _item_ctx(step, side, ctx, item_id, None))
        )
        return EligibleSet(item_ids=items, by_target=None)

    by_target: dict[int, tuple[int, ...]] = {}
    union: list[int] = []
    for player in ctx.targets_for(side):
        items = tuple(
            item_id
            for item_id in ctx.available_item_ids
            if evaluate(step.eligible, _item_ctx(step, side, ctx, item_id, player.role))
        )
        by_target[player.player_id] = items
        union.extend(item for item in items if item not in union)
    return EligibleSet(item_ids=tuple(union), by_target=by_target)


def _max_per_group_rules(step: ResolvedStep) -> list[tuple[int, str, str | None]]:
    return [
        (
            int(constraint.params.get("max", 1)),
            str(constraint.params.get("scope", "step")),
            normalize_group(constraint.params.get("group")),
        )
        for constraint in step.constraints
        if constraint.type == "max_per_group"
    ]


def _round_group_counts(step: ResolvedStep, side: str, ctx: RuntimeCtx) -> dict[str | None, int]:
    """The side's applied items of the same action in EARLIER steps of the round."""
    counts: dict[str | None, int] = {}
    for applied in ctx.history.items:
        if applied.side != side or applied.action != step.action or applied.round != ctx.round:
            continue
        if applied.step_index >= step.index:
            continue
        group = ctx.group_of(applied.item_id)
        counts[group] = counts.get(group, 0) + 1
    return counts


def validate_items(
    step: ResolvedStep,
    side: str,
    items: Sequence[Mapping[str, Any]],
    ctx: RuntimeCtx,
    *,
    final: bool = False,
) -> list[str]:
    """Why this draft is not acceptable. Empty = valid.

    ``final=False`` checks everything a partial draft can break (count ceiling,
    duplicates, eligibility, targets, ``one_per_target``, ``max_per_group``);
    ``final=True`` adds what only a complete draft can satisfy (``min``,
    ``min_per_group``).
    """
    issues: list[str] = []
    eligible = eligible_items(step, side, ctx)
    allowed_targets = {player.player_id for player in ctx.targets_for(side)}
    available = set(ctx.available_item_ids)

    if len(items) > step.count:
        issues.append("too_many_items")

    seen_items: set[int] = set()
    seen_targets: set[int] = set()
    group_counts: dict[str | None, int] = {}
    one_per_target = any(constraint.type == "one_per_target" for constraint in step.constraints)

    for item in items:
        item_id = int(item["item_id"])
        target_player_id = item.get("target_player_id")
        if item_id in seen_items:
            issues.append("duplicate_item")
        seen_items.add(item_id)

        if item_id not in available:
            issues.append("item_not_available")
        elif step.target is None:
            if item_id not in eligible.item_ids:
                issues.append("item_not_eligible")
        else:
            if target_player_id is None:
                issues.append("target_required")
            elif target_player_id not in allowed_targets:
                issues.append("target_unknown")
            elif item_id not in (eligible.by_target or {}).get(int(target_player_id), ()):
                issues.append("item_not_eligible")

        if step.target is None and target_player_id is not None:
            issues.append("target_not_allowed")
        if one_per_target and target_player_id is not None:
            if target_player_id in seen_targets:
                issues.append("one_per_target")
            seen_targets.add(int(target_player_id))

        group = ctx.group_of(item_id)
        group_counts[group] = group_counts.get(group, 0) + 1

    rules = _max_per_group_rules(step)
    if rules:
        carried = _round_group_counts(step, side, ctx)
        for maximum, scope, group in rules:
            for candidate, count in group_counts.items():
                if group is not None and candidate != group:
                    continue
                total = count + (carried.get(candidate, 0) if scope == "round" else 0)
                if total > maximum:
                    issues.append("max_per_group")

    if final:
        if len(items) < effective_min(step, side, ctx):
            issues.append("not_enough_items")
        for constraint in step.constraints:
            if constraint.type != "min_per_group":
                continue
            group = normalize_group(constraint.params.get("group"))
            if group_counts.get(group, 0) < int(constraint.params.get("min", 1)):
                issues.append("min_per_group")

    return list(dict.fromkeys(issues))


def effective_min(step: ResolvedStep, side: str, ctx: RuntimeCtx) -> int:
    """``min`` capped by what is actually choosable, so an exhausted pool can
    never deadlock a lock: distinct eligible items, or for a target step with
    ``one_per_target`` the maximum target/item matching."""
    eligible = eligible_items(step, side, ctx)
    if step.target is not None and any(constraint.type == "one_per_target" for constraint in step.constraints):
        capacity = _max_matching(eligible.by_target or {})
    else:
        capacity = len(eligible.item_ids)
    return min(step.min, capacity)


def _max_matching(by_target: Mapping[int, Sequence[int]]) -> int:
    """Kuhn's algorithm: how many targets can be given a distinct item."""
    assigned: dict[int, int] = {}  # item_id -> player_id

    def try_assign(player_id: int, items: Sequence[int], seen: set[int]) -> bool:
        for item_id in items:
            if item_id in seen:
                continue
            seen.add(item_id)
            holder = assigned.get(item_id)
            if holder is None or try_assign(holder, by_target[holder], seen):
                assigned[item_id] = player_id
                return True
        return False

    matched = 0
    for player_id, items in by_target.items():
        if try_assign(player_id, items, set()):
            matched += 1
    return matched


# ── filling ─────────────────────────────────────────────────────────────────


def random_fill(
    step: ResolvedStep,
    side: str,
    items: Sequence[Mapping[str, Any]],
    ctx: RuntimeCtx,
    rng: Random | None = None,
) -> list[dict[str, Any]]:
    """Extend a draft to ``count`` with random eligible items that keep every
    constraint satisfiable. CSPRNG by default; a seeded ``Random`` for tests."""
    chooser = rng or secrets.SystemRandom()
    filled = [dict(item) for item in items]
    eligible = eligible_items(step, side, ctx)

    while len(filled) < step.count:
        candidates = _fill_candidates(step, side, ctx, filled, eligible, chooser)
        if not candidates:
            break
        filled.append(chooser.choice(candidates))
    return filled


def _fill_candidates(
    step: ResolvedStep,
    side: str,
    ctx: RuntimeCtx,
    filled: list[dict[str, Any]],
    eligible: EligibleSet,
    chooser: Random,
) -> list[dict[str, Any]]:
    """Every single addition that leaves the draft valid, shuffled."""
    used = {int(item["item_id"]) for item in filled}
    options: list[dict[str, Any]] = []
    if step.target is None:
        options = [
            {"item_id": item_id, "target_player_id": None} for item_id in eligible.item_ids if item_id not in used
        ]
    else:
        for player_id, item_ids in (eligible.by_target or {}).items():
            options.extend(
                {"item_id": item_id, "target_player_id": player_id} for item_id in item_ids if item_id not in used
            )
    chooser.shuffle(options)
    return [option for option in options if not validate_items(step, side, [*filled, option], ctx)]


def resolve_system_step(step: ResolvedStep, ctx: RuntimeCtx, rng: Random | None = None) -> list[dict[str, Any]]:
    """What the engine itself submits for a ``system`` step: a decider settles
    one random available (never carried) entry of the round; any other action
    random-fills its count."""
    chooser = rng or secrets.SystemRandom()
    if step.action == "decider":
        eligible = eligible_items(step, "system", ctx)
        if not eligible.item_ids:
            return []
        return [{"item_id": chooser.choice(list(eligible.item_ids)), "target_player_id": None}]
    return random_fill(step, "system", [], ctx, chooser)


# ── undo / dispute ──────────────────────────────────────────────────────────


def undo_target(steps: Sequence[ResolvedStep], submissions: Iterable[SubmissionLike]) -> int | None:
    """The step an undo reopens: the latest one holding an applied item from a
    captain (never a trailing system step, which is reverted along with it)."""
    rows = list(submissions)
    target: int | None = None
    for step in steps:
        if step.is_system:
            continue
        for side in step.acting_sides:
            row = side_submission(rows, step.index, side)
            if row is not None and row.state != VOIDED and _items_of(row):
                target = step.index
                break
    return target


def dispute_target(
    steps: Sequence[ResolvedStep],
    submissions: Iterable[SubmissionLike],
    *,
    side: str | None = None,
    blocked_rounds: frozenset[int] = frozenset(),
) -> DisputeState:
    """Whether ``side`` may unilaterally reopen the latest revealed step.

    Allowed when that step is blind, its ``dispute`` is enabled, the attempts
    used are below its max, nothing was submitted on a later step, and the
    round is not already reported (``blocked_rounds``, decided by the caller
    which owns the games/report tables).
    """
    rows = list(submissions)

    def fully_revealed(step: ResolvedStep) -> bool:
        return all(
            (row := side_submission(rows, step.index, member)) is not None and row.state == REVEALED
            for member in step.sides
        )

    revealed = [step for step in steps if fully_revealed(step)]
    if not revealed:
        return DisputeState(False, None, 0, 0)
    latest = revealed[-1]

    started_later = any(
        side_submission(rows, step.index, member) is not None
        for step in steps
        if step.index > latest.index
        for member in step.sides
    )
    if started_later:
        return DisputeState(False, None, current_attempt(rows, latest.index) - 1, latest.dispute.max)

    attempts_used = current_attempt(rows, latest.index) - 1
    available = (
        latest.blind
        and latest.dispute.enabled
        and attempts_used < latest.dispute.max
        and (side is None or side in latest.acting_sides)
        and (latest.round is None or latest.round not in blocked_rounds)
    )
    return DisputeState(
        available=available,
        step_index=latest.index if available else None,
        attempts_used=attempts_used,
        max=latest.dispute.max,
    )
