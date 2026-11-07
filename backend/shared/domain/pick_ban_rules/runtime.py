"""Runtime semantics over submissions: cursor, eligibility, validation,
projection, reveal, undo and dispute.

Pure functions over two structural protocols, so the SQLAlchemy rows satisfy
them without this module importing a model. Submissions are the action log and
the only source of truth; ``pick_ban_entry`` is a projection this module
recomputes after every mutation.
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

#: ``pick_ban_entry.picked_by_kind`` for a participation, and for anything the
#: engine resolved itself (``PickBanActorKind``).
TEAM_KIND = "team"
DECIDER_KIND = "decider"


def actor_columns(actor: int | None) -> tuple[str, int | None]:
    """``(picked_by_kind, picked_by_team_id)`` for one resolved actor -- the
    pair the board's CHECK constraint keeps in step."""
    return (TEAM_KIND, actor) if actor is not None else (DECIDER_KIND, None)


class SubmissionLike(Protocol):
    """One participation's action on one step (``encounter.pick_ban_submission``).

    ``encounter_team_id`` is ``None`` exactly when the engine answered.
    """

    step_index: int
    encounter_team_id: int | None
    #: The member a member step's answer is for (``encounter.team_member``); ``None`` for a team step.
    team_member_id: int | None
    attempt: int
    state: str
    items_json: list[dict[str, Any]]
    locked_at: datetime | None
    revealed_at: datetime | None


class EntryLike(Protocol):
    """One row of the round's board (``encounter.pick_ban_entry``)."""

    item_id: int
    round: int | None
    order: int
    action_index: int | None
    picked_by_kind: str | None
    picked_by_team_id: int | None
    picked_for_member_id: int | None
    protected_by_kind: str | None
    protected_by_team_id: int | None
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
    bans are not among them); ``targets`` maps an ACTING participation to the
    players it may name — i.e. the opponents' rosters.
    """

    kind: str
    round: int | None = None
    best_of: int = 1
    available_item_ids: tuple[int, ...] = ()
    groups: Mapping[int, str | None] = field(default_factory=dict)
    history: History = History()
    targets: Mapping[int, Sequence[TargetPlayer]] = field(default_factory=dict)
    #: ``{participation: its seated members in pick order}`` -- a mix room's (spec §11.6 R4-2); empty in a tournament.
    members: Mapping[int, Sequence[int]] = field(default_factory=dict)
    #: ``{member: heroes they may not pick}`` -- the mix's Fearless snapshot (§11.4); empty without Fearless.
    exclusions: Mapping[int, frozenset[int]] = field(default_factory=dict)

    def group_of(self, item_id: int) -> str | None:
        return normalize_group(self.groups.get(item_id))

    def targets_for(self, actor: int | None) -> tuple[TargetPlayer, ...]:
        return tuple(self.targets.get(actor, ())) if actor is not None else ()

    def members_of(self, actor: int | None) -> tuple[int, ...]:
        """``actor``'s seated members in pick order; ``()`` outside a mix room."""
        return tuple(self.members.get(actor, ())) if actor is not None else ()


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
    #: The participation that banned it; ``None`` when the engine did.
    actor: int | None
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


def actor_submission(
    submissions: Iterable[SubmissionLike], step_index: int, actor: int | None, member: int | None = None
) -> SubmissionLike | None:
    """An actor's -- or, on a member step, one member's -- live submission for a step: its row at the current
    attempt, unless that row was voided."""
    attempt = current_attempt(submissions, step_index)
    for row in submissions:
        if (
            row.step_index == step_index
            and row.encounter_team_id == actor
            and row.team_member_id == member
            and row.attempt == attempt
            and row.state != VOIDED
        ):
            return row
    return None


def current_step(steps: Sequence[ResolvedStep], submissions: Iterable[SubmissionLike]) -> ResolvedStep | None:
    """The first step some actor has not revealed yet; ``None`` once the
    resolved sequence is exhausted.

    An UNBOUND step (a ``side:<code>`` actor whose side is not handed out yet)
    stops the cursor rather than being walked past: it has no actors to compare
    against, and skipping it would silently drop a step of the draft.
    """
    rows = list(submissions)
    for step in steps:
        if step.is_unbound:
            return step
        for actor, member in step.answers:
            row = actor_submission(rows, step.index, actor, member)
            if row is None or row.state != REVEALED:
                return step
    return None


def assigned_sides(
    steps: Sequence[ResolvedStep],
    submissions: Iterable[SubmissionLike],
    sides: Sequence[str],
    *,
    participants: Sequence[int],
    round: int | None,
) -> dict[str, int]:
    """``{side code: participation}`` as this round's played ``side_pick`` steps
    settled it.

    Read off the action log, not off ``game_team``: the log is the source of
    truth for everything else the room decides, and binding an actor to a row
    the projection has not written yet would make the two disagree.

    A ``side_pick`` submission carries ONE item whose ``item_id`` is the index
    into ``sides`` -- a side is not a board entry, so there is nothing else for
    it to name. The chooser takes the side they named and the remaining sides
    go to the remaining participations in seat order, which is exactly what
    ``_apply_side_pick`` writes onto ``game_team``.
    """
    rows = list(submissions)
    assigned: dict[str, int] = {}
    for step in steps:
        if step.action != "side_pick" or step.round != round:
            continue
        for actor in step.acting_actors:
            row = actor_submission(rows, step.index, actor)
            if row is None or row.state != REVEALED:
                continue
            items = _items_of(row)
            if not items or not sides:
                continue
            assigned.setdefault(sides[int(items[0]["item_id"]) % len(sides)], actor)
    if not assigned:
        return assigned
    remaining = [side for side in sides if side not in assigned]
    others = [actor for actor in participants if actor not in assigned.values()]
    for side, actor in zip(remaining, others, strict=False):
        assigned[side] = actor
    return assigned


def _items_of(submission: SubmissionLike) -> list[dict[str, Any]]:
    return [dict(item) for item in (submission.items_json or [])]


def applied_items(steps: Sequence[ResolvedStep], submissions: Iterable[SubmissionLike]) -> list[AppliedItem]:
    """What the board shows, in application order: revealed submissions plus
    the live drafts of OPEN steps (an open step's items are public at once)."""
    rows = list(submissions)
    applied: list[AppliedItem] = []
    for step in steps:
        for actor, member in step.answers:
            row = actor_submission(rows, step.index, actor, member)
            if row is None:
                continue
            if row.state != REVEALED and (step.blind or row.state not in (DRAFT, LOCKED)):
                continue
            for item in _items_of(row):
                # A member step's hero is its member's; an assignment's item names its member itself.
                owner = member if step.member is not None else item.get("member_id")
                applied.append(
                    AppliedItem(
                        step_index=step.index,
                        round=step.round,
                        actor=actor,
                        action=step.action,
                        item_id=int(item["item_id"]),
                        member=None if owner is None else int(owner),
                    )
                )
    return applied


def history_of(steps: Sequence[ResolvedStep], submissions: Iterable[SubmissionLike]) -> History:
    """Applied items as the condition leaves read them."""
    return History(items=tuple(applied_items(steps, submissions)))


def visible_submissions(
    steps: Sequence[ResolvedStep], submissions: Iterable[SubmissionLike], viewer: int | None
) -> list[SubmissionLike]:
    """Blind privacy: the server never serializes another participation's
    unrevealed draft. Revealed rows, every row of an open step, and the
    viewer's own."""
    by_index = {step.index: step for step in steps}
    rows = list(submissions)
    visible: list[SubmissionLike] = []
    for row in rows:
        if row.state == VOIDED or row.attempt != current_attempt(rows, row.step_index):
            continue
        step = by_index.get(row.step_index)
        if (
            row.state == REVEALED
            or (step is not None and not step.blind)
            or (viewer is not None and row.encounter_team_id == viewer)
        ):
            visible.append(row)
    return visible


def step_progress(step: ResolvedStep, submissions: Iterable[SubmissionLike]) -> dict[int, dict[str, Any]]:
    """Per acting participation ``{locked, filled}`` -- reported even while a blind draft itself stays hidden. A
    member step's team is locked once every member owing it has answered; ``filled`` counts its members' items."""
    rows = list(submissions)
    progress: dict[int, dict[str, Any]] = {actor: {"locked": True, "filled": 0} for actor in step.acting_actors}
    for actor, member in step.answers:
        if actor is None:
            continue
        row = actor_submission(rows, step.index, actor, member)
        progress[actor]["locked"] = progress[actor]["locked"] and row is not None and row.state in (LOCKED, REVEALED)
        progress[actor]["filled"] += len(_items_of(row)) if row is not None else 0
    return progress


def ready_to_reveal(step: ResolvedStep, submissions: Iterable[SubmissionLike]) -> bool:
    """True once every actor of the step has a locked (or already revealed)
    submission — the moment a blind step opens up."""
    rows = list(submissions)
    for actor, member in step.answers:
        row = actor_submission(rows, step.index, actor, member)
        if row is None or row.state not in (LOCKED, REVEALED):
            return False
    return True


# ── projection ──────────────────────────────────────────────────────────────


def project_entries(
    entries: Sequence[EntryLike], steps: Sequence[ResolvedStep], submissions: Iterable[SubmissionLike]
) -> None:
    """Recompute the board from the action log.

    Deterministic and idempotent: reset every non-carried entry, then replay
    the applied items in order. Carried bans are fixed and never touched.
    """
    for entry in entries:
        if entry.carried_from_round is None:
            entry.status = AVAILABLE
            entry.picked_by_kind = None
            entry.picked_by_team_id = None
            entry.picked_for_member_id = None
            entry.protected_by_kind = None
            entry.protected_by_team_id = None
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
        kind, actor = actor_columns(applied.actor)
        match applied.action:
            case "ban":
                if entry.status != AVAILABLE:
                    continue  # already banned by the other actor of a blind step, or protected
                entry.status = BANNED
                entry.picked_by_kind, entry.picked_by_team_id = kind, actor
            case "protect":
                if entry.status != AVAILABLE:
                    continue
                entry.status = PROTECTED
                entry.protected_by_kind, entry.protected_by_team_id = kind, actor
            case "pick" | "decider":
                if entry.status != AVAILABLE:
                    continue
                picked += 1
                entry.status = PICKED
                entry.picked_by_kind, entry.picked_by_team_id = (
                    (DECIDER_KIND, None) if applied.action == "decider" else (kind, actor)
                )
                entry.order = picked
                entry.picked_for_member_id = applied.member
            case "assign":
                # An assignment names whose hero an already-picked one of the team's is; it moves nothing.
                if entry.status == PICKED and entry.picked_by_team_id == applied.actor:
                    entry.picked_for_member_id = applied.member
                continue
            case _:
                # ``side_pick`` settles a side, not an item: it applies nothing
                # to the board.
                continue
        entry.action_index = action_index
        action_index += 1


def carried_bans(steps: Sequence[ResolvedStep], submissions: Iterable[SubmissionLike], round: int) -> list[CarriedBan]:
    """Bans of earlier rounds still active on ``round``: ``lifetime is null or
    r + lifetime > round``. The first actor wins on duplicates."""
    rows = list(submissions)
    seen: dict[int, CarriedBan] = {}
    for step in steps:
        if step.action != "ban" or step.round is None or step.round >= round:
            continue
        if step.lifetime is not None and step.round + step.lifetime <= round:
            continue
        for actor in step.actors:
            row = actor_submission(rows, step.index, actor)
            if row is None or row.state != REVEALED:
                continue
            for item in _items_of(row):
                item_id = int(item["item_id"])
                seen.setdefault(
                    item_id,
                    CarriedBan(item_id=item_id, actor=actor, from_round=step.round),
                )
    return list(seen.values())


# ── eligibility ─────────────────────────────────────────────────────────────


def _item_ctx(step: ResolvedStep, actor: int | None, ctx: RuntimeCtx, item_id: int, target_role: str | None) -> ItemCtx:
    return ItemCtx(
        item_id=item_id,
        group=ctx.group_of(item_id),
        kind=ctx.kind,
        actor=actor,
        target_role=target_role,
        round=ctx.round,
        history=replace(ctx.history, current_step_index=step.index),
        groups=ctx.groups,
    )


def filter_pool(pool_filter: Mapping[str, Any] | None, item_ids: Sequence[int], ctx: RuntimeCtx) -> list[int]:
    """The configured candidates a round may actually open with: a pool filter
    has no acting participation and no target, so only absolute leaves apply
    (validation enforces that)."""
    return [
        item_id
        for item_id in item_ids
        if evaluate(
            pool_filter,
            ItemCtx(
                item_id=item_id,
                group=ctx.group_of(item_id),
                kind=ctx.kind,
                actor=None,
                target_role=None,
                round=ctx.round,
                history=ctx.history,
                groups=ctx.groups,
            ),
        )
    ]


def _team_picks(step: ResolvedStep, actor: int | None, ctx: RuntimeCtx) -> list[int]:
    """The heroes ``actor`` picked on earlier steps of this round, in pick order."""
    return [
        applied.item_id
        for applied in ctx.history.items
        if applied.action == "pick"
        and applied.actor == actor
        and applied.round == ctx.round
        and applied.step_index < step.index
    ]


def _assignable(heroes: Sequence[int], members: Sequence[int], ctx: RuntimeCtx) -> dict[int, list[int]]:
    """``{member: the heroes of ``heroes`` their Fearless allows}`` -- the graph an assignment matches on."""
    return {
        member: [hero for hero in heroes if hero not in ctx.exclusions.get(member, frozenset())] for member in members
    }


def eligible_items(step: ResolvedStep, actor: int | None, ctx: RuntimeCtx, member: int | None = None) -> EligibleSet:
    """What ``actor`` -- on a member step, for ``member`` -- may choose on ``step`` right now. For a target step the
    answer is per opponent player, and ``item_ids`` is their union. An assignment offers the team's picks, less the
    member's Fearless; a mix team's own pick only a hero that keeps the team's picks assignable (spec §11.6 R4-8)."""
    excluded = ctx.exclusions.get(member, frozenset()) if member is not None else frozenset()
    if step.action == "assign":
        return EligibleSet(
            item_ids=tuple(hero for hero in _team_picks(step, actor, ctx) if hero not in excluded), by_target=None
        )
    if step.target is None:
        items = tuple(
            item_id
            for item_id in ctx.available_item_ids
            if item_id not in excluded and evaluate(step.eligible, _item_ctx(step, actor, ctx, item_id, None))
        )
        roster = ctx.members_of(actor)
        if step.action == "pick" and step.member is None and roster:
            picked = _team_picks(step, actor, ctx)
            items = tuple(
                item for item in items if len(_matching(_assignable([*picked, item], roster, ctx))) == len(picked) + 1
            )
        return EligibleSet(item_ids=items, by_target=None)

    by_target: dict[int, tuple[int, ...]] = {}
    union: list[int] = []
    for player in ctx.targets_for(actor):
        items = tuple(
            item_id
            for item_id in ctx.available_item_ids
            if evaluate(step.eligible, _item_ctx(step, actor, ctx, item_id, player.role))
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


def _round_group_counts(step: ResolvedStep, actor: int | None, ctx: RuntimeCtx) -> dict[str | None, int]:
    """The actor's applied items of the same action in EARLIER steps of the round."""
    counts: dict[str | None, int] = {}
    for applied in ctx.history.items:
        if applied.actor != actor or applied.action != step.action or applied.round != ctx.round:
            continue
        if applied.step_index >= step.index:
            continue
        group = ctx.group_of(applied.item_id)
        counts[group] = counts.get(group, 0) + 1
    return counts


def validate_items(
    step: ResolvedStep,
    actor: int | None,
    items: Sequence[Mapping[str, Any]],
    ctx: RuntimeCtx,
    *,
    final: bool = False,
    member: int | None = None,
) -> list[str]:
    """Why this draft is not acceptable. Empty = valid.

    ``final=False`` checks everything a partial draft can break (count ceiling,
    duplicates, eligibility, targets, ``one_per_target``, ``max_per_group``);
    ``final=True`` adds what only a complete draft can satisfy (``min``,
    ``min_per_group``). ``member`` is whom a member step's item is for; an
    assignment is judged by :func:`_assignment_issues`.
    """
    if step.action == "assign":
        return _assignment_issues(step, actor, items, ctx, final=final)
    issues: list[str] = []
    eligible = eligible_items(step, actor, ctx, member)
    allowed_targets = {player.player_id for player in ctx.targets_for(actor)}
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
        carried = _round_group_counts(step, actor, ctx)
        for maximum, scope, group in rules:
            for candidate, count in group_counts.items():
                if group is not None and candidate != group:
                    continue
                total = count + (carried.get(candidate, 0) if scope == "round" else 0)
                if total > maximum:
                    issues.append("max_per_group")

    if final:
        if len(items) < effective_min(step, actor, ctx, member):
            issues.append("not_enough_items")
        for constraint in step.constraints:
            if constraint.type != "min_per_group":
                continue
            group = normalize_group(constraint.params.get("group"))
            if group_counts.get(group, 0) < int(constraint.params.get("min", 1)):
                issues.append("min_per_group")

    return list(dict.fromkeys(issues))


def _assignment_issues(
    step: ResolvedStep, actor: int | None, items: Sequence[Mapping[str, Any]], ctx: RuntimeCtx, *, final: bool
) -> list[str]:
    """Why an assignment draft is not acceptable: each of the team's picks to a different member of the team, never
    a hero that member's Fearless excludes, and never a choice that leaves another pick nobody can play -- a draft
    must still extend to a complete assignment (spec §11.6 R4-1, R4-8)."""
    picks = _team_picks(step, actor, ctx)
    roster = ctx.members_of(actor)
    issues: list[str] = []
    if len(items) > step.count:
        issues.append("too_many_items")
    seen_items: set[int] = set()
    seen_members: set[int] = set()
    for item in items:
        item_id = int(item["item_id"])
        raw = item.get("member_id")
        member = int(raw) if raw is not None else None
        if item_id in seen_items:
            issues.append("duplicate_item")
        seen_items.add(item_id)
        if member is None or member not in roster:
            issues.append("member_unknown")
            continue
        if member in seen_members:
            issues.append("duplicate_member")
        seen_members.add(member)
        if item_id not in picks:
            issues.append("item_not_picked")
        elif item_id in ctx.exclusions.get(member, frozenset()):
            issues.append("item_not_eligible")
    if not issues:
        rest = _assignable(
            [hero for hero in picks if hero not in seen_items], [m for m in roster if m not in seen_members], ctx
        )
        if len(items) + len(_matching(rest)) < len(_matching(_assignable(picks, roster, ctx))):
            issues.append("item_not_eligible")
    if final and len(items) < effective_min(step, actor, ctx):
        issues.append("not_enough_items")
    return list(dict.fromkeys(issues))


def effective_min(step: ResolvedStep, actor: int | None, ctx: RuntimeCtx, member: int | None = None) -> int:
    """``min`` capped by what is actually choosable, so an exhausted pool can never deadlock a lock: distinct eligible
    items, for a target step with ``one_per_target`` the maximum target/item matching, and for an assignment the
    maximum member/hero matching."""
    if step.action == "assign":
        roster = ctx.members_of(actor)
        return min(step.min, len(_matching(_assignable(_team_picks(step, actor, ctx), roster, ctx))))
    eligible = eligible_items(step, actor, ctx, member)
    if step.target is not None and any(constraint.type == "one_per_target" for constraint in step.constraints):
        capacity = len(_matching(eligible.by_target or {}))
    else:
        capacity = len(eligible.item_ids)
    return min(step.min, capacity)


def _matching(by_target: Mapping[int, Sequence[int]]) -> dict[int, int]:
    """Kuhn's algorithm: a maximum matching of targets (players, or members) to distinct items, ``{item: target}``.
    Keys and lists are tried in their given order, so a shuffled input is a random maximum matching."""
    assigned: dict[int, int] = {}

    def try_assign(target: int, items: Sequence[int], seen: set[int]) -> bool:
        for item_id in items:
            if item_id in seen:
                continue
            seen.add(item_id)
            holder = assigned.get(item_id)
            if holder is None or try_assign(holder, by_target[holder], seen):
                assigned[item_id] = target
                return True
        return False

    for target, items in by_target.items():
        try_assign(target, items, set())
    return assigned


# ── filling ─────────────────────────────────────────────────────────────────


def random_fill(
    step: ResolvedStep,
    actor: int | None,
    items: Sequence[Mapping[str, Any]],
    ctx: RuntimeCtx,
    rng: Random | None = None,
    *,
    member: int | None = None,
) -> list[dict[str, Any]]:
    """Extend a draft to ``count`` with random eligible items that keep every constraint satisfiable -- on a member
    step from what ``member`` may take, on an assignment by a random matching (spec §11.6 R4-9). CSPRNG by default;
    a seeded ``Random`` for tests."""
    chooser = rng or secrets.SystemRandom()
    if step.action == "assign":
        return _random_assignment(step, actor, items, ctx, chooser)
    filled = [dict(item) for item in items]
    eligible = eligible_items(step, actor, ctx, member)

    while len(filled) < step.count:
        candidates = _fill_candidates(step, actor, ctx, filled, eligible, chooser, member)
        if not candidates:
            break
        filled.append(chooser.choice(candidates))
    return filled


def _fill_candidates(
    step: ResolvedStep,
    actor: int | None,
    ctx: RuntimeCtx,
    filled: list[dict[str, Any]],
    eligible: EligibleSet,
    chooser: Random,
    member: int | None,
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
    return [option for option in options if not validate_items(step, actor, [*filled, option], ctx, member=member)]


def _random_assignment(
    step: ResolvedStep, actor: int | None, items: Sequence[Mapping[str, Any]], ctx: RuntimeCtx, chooser: Random
) -> list[dict[str, Any]]:
    """A timed-out assignment: the captain's draft as far as it still extends to a complete assignment, then the rest
    of the team's picks matched at random to the members still without one, never against a member's Fearless. A
    draft choice that would leave a pick nobody can play is dropped, and its hero rematched."""
    kept: list[dict[str, Any]] = []
    for item in items:
        if not _assignment_issues(step, actor, [*kept, item], ctx, final=False):
            kept.append(dict(item))
    heroes = [hero for hero in _team_picks(step, actor, ctx) if hero not in {int(item["item_id"]) for item in kept}]
    members = [member for member in ctx.members_of(actor) if member not in {int(item["member_id"]) for item in kept}]
    chooser.shuffle(heroes)
    chooser.shuffle(members)
    matched = _matching(_assignable(heroes, members, ctx))
    kept.extend({"item_id": hero, "target_player_id": None, "member_id": member} for hero, member in matched.items())
    return kept[: step.count]


def fill_member_answers(
    step: ResolvedStep, owing: Sequence[tuple[int, int]], ctx: RuntimeCtx, rng: Random | None = None
) -> dict[tuple[int, int], list[dict[str, Any]]]:
    """An expired member step's stand-in answers (spec §11.6 R4-9): every still-owing ``(participation, member)``
    gets a hero they may take, all distinct. Matched jointly rather than one by one -- a hero is the match's once
    (§11.2), so one member's random hero must never strand another, on either team -- over a shuffled order for
    randomness. A seat no hero is left for gets ``[]``. ``ctx`` is the step's, so locked answers keep their heroes."""
    chooser = rng or secrets.SystemRandom()
    seats = list(owing)
    chooser.shuffle(seats)
    options = {
        index: [
            int(option["item_id"])
            for option in _fill_candidates(
                step, actor, ctx, [], eligible_items(step, actor, ctx, member), chooser, member
            )
        ]
        for index, (actor, member) in enumerate(seats)
    }
    heroes = {seats[index]: hero for hero, index in _matching(options).items()}
    return {seat: [{"item_id": heroes[seat], "target_player_id": None}] if seat in heroes else [] for seat in owing}


def resolve_system_step(step: ResolvedStep, ctx: RuntimeCtx, rng: Random | None = None) -> list[dict[str, Any]]:
    """What the engine itself submits for a ``system`` step: a decider settles
    one random available (never carried) entry of the round; any other action
    random-fills its count."""
    chooser = rng or secrets.SystemRandom()
    if step.action == "decider":
        eligible = eligible_items(step, None, ctx)
        if not eligible.item_ids:
            return []
        return [{"item_id": chooser.choice(list(eligible.item_ids)), "target_player_id": None}]
    return random_fill(step, None, [], ctx, chooser)


# ── undo / dispute ──────────────────────────────────────────────────────────


def undo_target(steps: Sequence[ResolvedStep], submissions: Iterable[SubmissionLike]) -> int | None:
    """The step an undo reopens: the latest one holding an applied item from a
    captain (never a trailing system step, which is reverted along with it)."""
    rows = list(submissions)
    target: int | None = None
    for step in steps:
        if step.is_system:
            continue
        for actor, member in step.answers:
            row = actor_submission(rows, step.index, actor, member)
            if row is not None and row.state != VOIDED and _items_of(row):
                target = step.index
                break
    return target


def dispute_target(
    steps: Sequence[ResolvedStep],
    submissions: Iterable[SubmissionLike],
    *,
    actor: int | None = None,
    blocked_rounds: frozenset[int] = frozenset(),
) -> DisputeState:
    """Whether ``actor`` may unilaterally reopen the latest revealed step.

    Allowed when that step is blind, its ``dispute`` is enabled, the attempts
    used are below its max, nothing was submitted on a later step, and the
    round is not already reported (``blocked_rounds``, decided by the caller
    which owns the games/report tables).
    """
    rows = list(submissions)

    def fully_revealed(step: ResolvedStep) -> bool:
        return all(
            (row := actor_submission(rows, step.index, actor, member)) is not None and row.state == REVEALED
            for actor, member in step.answers
        )

    revealed = [step for step in steps if fully_revealed(step)]
    if not revealed:
        return DisputeState(False, None, 0, 0)
    latest = revealed[-1]

    started_later = any(
        actor_submission(rows, step.index, actor, member) is not None
        for step in steps
        if step.index > latest.index
        for actor, member in step.answers
    )
    if started_later:
        return DisputeState(False, None, current_attempt(rows, latest.index) - 1, latest.dispute.max)

    attempts_used = current_attempt(rows, latest.index) - 1
    available = (
        latest.blind
        and latest.dispute.enabled
        and attempts_used < latest.dispute.max
        and (actor is None or actor in latest.acting_actors)
        and (latest.round is None or latest.round not in blocked_rounds)
    )
    return DisputeState(
        available=available,
        step_index=latest.index if available else None,
        attempts_used=attempts_used,
        max=latest.dispute.max,
    )
