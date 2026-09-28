"""Ruleset validation: everything that decides whether a ruleset may be saved.

Errors block the upsert; warnings are shown in the constructor but do not.
Every issue carries a stable snake_case ``code`` and a JSON path into the
document, so the editor can highlight the offending field.

Design: ``docs/plans/2026-09-28-pick-ban-constructor.md`` §1, §2.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .registry import (
    CONSTRAINTS,
    HERO_GROUPS,
    LEAVES,
    MAX_TREE_DEPTH,
    MAX_TREE_NODES,
    ParamSpec,
    normalize_group,
)
from .schema import Issue, Phase, Ruleset, RulesetError, Step, parse_ruleset

__all__ = ["Issue", "validate_ruleset"]

MAX_COUNT = 20
MAX_DISPUTE = 5
MIN_TIMER_SECONDS = 5
#: Rounds the "no phase covers this map" warning checks.
PREVIEW_MAPS = range(1, 6)

_ID_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789_-")


def _error(path: str, code: str, message: str) -> Issue:
    return Issue(path, code, "error", message)


def _warning(path: str, code: str, message: str) -> Issue:
    return Issue(path, code, "warning", message)


def validate_ruleset(
    ruleset_json: Any,
    *,
    kind: str,
    mode: str = "pool",
    groups: Sequence[str] | None = None,
) -> list[Issue]:
    """Validate a ruleset document for ``kind``/``mode``.

    ``groups`` is the item-group vocabulary of the kind (gamemode slugs for
    maps); ``None`` means "do not check map group names" — the hero groups are
    a closed set and always checked.
    """
    try:
        ruleset = parse_ruleset(ruleset_json)
    except RulesetError as exc:
        return list(exc.issues)

    known_groups = _known_groups(kind, groups)
    issues: list[Issue] = []
    if not ruleset.phases:
        issues.append(_error("phases", "phases_empty", "a ruleset needs at least one phase"))

    seen_phase_ids: set[str] = set()
    seen_step_ids: set[str] = set()
    for index, phase in enumerate(ruleset.phases):
        path = f"phases[{index}]"
        _validate_id(phase.id, f"{path}.id", issues)
        if phase.id in seen_phase_ids:
            issues.append(_error(f"{path}.id", "duplicate_phase_id", f"phase id {phase.id!r} is used twice"))
        seen_phase_ids.add(phase.id)
        _validate_phase(phase, path, issues, kind=kind, mode=mode, known_groups=known_groups)
        for step_index, step in enumerate(phase.steps):
            step_path = f"{path}.steps[{step_index}]"
            _validate_id(step.id, f"{step_path}.id", issues)
            if step.id in seen_step_ids:
                issues.append(_error(f"{step_path}.id", "duplicate_step_id", f"step id {step.id!r} is used twice"))
            seen_step_ids.add(step.id)
            _validate_step(step, step_path, issues, kind=kind, phase=phase, known_groups=known_groups)

    if ruleset.timer_seconds is not None and ruleset.timer_seconds < MIN_TIMER_SECONDS:
        issues.append(
            _error("timer_seconds", "timer_range", f"a timer must be at least {MIN_TIMER_SECONDS} seconds or null")
        )

    # Warnings interpret the rules by running them (phase selection), which is
    # only meaningful once the rules themselves are sound.
    if not any(issue.severity == "error" for issue in issues):
        issues.extend(_coverage_warnings(ruleset, kind=kind))
    return issues


def _known_groups(kind: str, groups: Sequence[str] | None) -> set[str] | None:
    if kind == "hero":
        return set(HERO_GROUPS)
    if groups is None:
        return None
    return {normalized for group in groups if (normalized := normalize_group(group))}


def _validate_id(value: str, path: str, issues: list[Issue]) -> None:
    if not value or len(value) > 32 or not set(value) <= _ID_CHARS:
        issues.append(_error(path, "invalid_id", "ids are 1..32 chars of [a-z0-9_-]"))


# ── phases ──────────────────────────────────────────────────────────────────


def _validate_phase(
    phase: Phase,
    path: str,
    issues: list[Issue],
    *,
    kind: str,
    mode: str,
    known_groups: set[str] | None,
) -> None:
    if phase.name is not None and len(phase.name) > 64:
        issues.append(_error(f"{path}.name", "name_too_long", "a phase name is at most 64 characters"))

    _validate_condition(phase.when, f"{path}.when", issues, context="round", kind=kind, known_groups=known_groups)
    _validate_condition(
        phase.pool_filter, f"{path}.pool_filter", issues, context="pool", kind=kind, known_groups=known_groups
    )

    if phase.generator is not None:
        if kind != "map":
            issues.append(_error(f"{path}.generator", "generator_map_only", "generators exist for map veto only"))
        elif phase.generator == "bracket" and mode != "pool":
            issues.append(
                _error(f"{path}.generator", "generator_requires_pool_mode", "the bracket generator needs pool mode")
            )
        elif phase.generator == "slot_veto" and mode != "slots":
            issues.append(
                _error(f"{path}.generator", "generator_requires_slots_mode", "the slot generator needs slots mode")
            )
        if phase.steps:
            issues.append(_error(f"{path}.steps", "generator_with_steps", "a generated phase cannot declare steps"))
        return

    if not phase.steps:
        issues.append(_error(f"{path}.steps", "phase_without_steps", "a phase needs at least one step"))
    elif kind == "map" and not any(step.action in ("pick", "decider") for step in phase.steps):
        issues.append(
            _error(f"{path}.steps", "map_phase_without_pick", "a map phase must settle a map with a pick or a decider")
        )

    deciders = [index for index, step in enumerate(phase.steps) if step.action == "decider"]
    if len(deciders) > 1:
        issues.append(
            _error(f"{path}.steps[{deciders[1]}]", "decider_duplicate", "a phase may hold at most one decider")
        )
    if deciders and deciders[0] != len(phase.steps) - 1:
        issues.append(
            _error(f"{path}.steps[{deciders[0]}]", "decider_not_last", "a decider must be the phase's last step")
        )


# ── steps ───────────────────────────────────────────────────────────────────


def _validate_step(
    step: Step,
    path: str,
    issues: list[Issue],
    *,
    kind: str,
    phase: Phase,
    known_groups: set[str] | None,
) -> None:
    if step.action == "decider":
        if kind != "map":
            issues.append(_error(f"{path}.action", "decider_map_only", "a decider exists for map veto only"))
        if step.actors != "system":
            issues.append(_error(f"{path}.actors", "decider_actors", "a decider is resolved by the system"))
        if step.count != 1:
            issues.append(_error(f"{path}.count", "decider_count", "a decider settles exactly one item"))

    if not 1 <= step.count <= MAX_COUNT:
        issues.append(_error(f"{path}.count", "count_range", f"count must be between 1 and {MAX_COUNT}"))
    if step.min is not None and not 0 <= step.min <= step.count:
        issues.append(_error(f"{path}.min", "min_range", "min must be between 0 and count"))

    if step.blind and step.actors == "system":
        issues.append(_error(f"{path}.blind", "blind_system", "a system step has nothing to hide"))

    if step.target is not None:
        if kind != "hero":
            issues.append(_error(f"{path}.target", "target_hero_only", "targets name a roster player: hero bans only"))
        if step.actors == "system":
            issues.append(_error(f"{path}.target", "target_system", "a system step cannot name opponent players"))
        if step.action not in ("ban", "pick", "protect"):
            issues.append(_error(f"{path}.target", "target_action", "only ban, pick and protect can name a target"))

    if step.lifetime is not None:
        if step.action != "ban":
            issues.append(_error(f"{path}.lifetime", "lifetime_ban_only", "only a ban has a lifetime"))
        elif step.lifetime < 1:
            issues.append(_error(f"{path}.lifetime", "lifetime_range", "a lifetime is at least 1 map, or null"))

    if step.timer_seconds is not None and step.timer_seconds < MIN_TIMER_SECONDS:
        issues.append(
            _error(
                f"{path}.timer_seconds", "timer_range", f"a timer must be at least {MIN_TIMER_SECONDS} seconds or null"
            )
        )
    if not 0 <= step.dispute.max <= MAX_DISPUTE:
        issues.append(_error(f"{path}.dispute.max", "dispute_range", f"dispute max is between 0 and {MAX_DISPUTE}"))

    _validate_condition(
        step.eligible,
        f"{path}.eligible",
        issues,
        context="item",
        kind=kind,
        known_groups=known_groups,
        has_target=step.target is not None,
    )

    for index, constraint in enumerate(step.constraints):
        constraint_path = f"{path}.constraints[{index}]"
        spec = CONSTRAINTS.get(constraint.type)
        if spec is None:
            issues.append(
                _error(f"{constraint_path}.type", "unknown_constraint", f"unknown constraint {constraint.type!r}")
            )
            continue
        if spec.requires_target and step.target is None:
            issues.append(
                _error(
                    constraint_path,
                    "constraint_requires_target",
                    f"{constraint.type} only applies to a step with a target",
                )
            )
        _validate_params(spec.params, constraint.params, constraint_path, issues, known_groups=known_groups)


# ── condition trees ─────────────────────────────────────────────────────────


def _validate_condition(
    node: Any,
    path: str,
    issues: list[Issue],
    *,
    context: str,
    kind: str,
    known_groups: set[str] | None,
    has_target: bool = False,
    depth: int = 1,
    budget: list[int] | None = None,
) -> None:
    if budget is None:
        budget = [MAX_TREE_NODES]
    if depth > MAX_TREE_DEPTH:
        issues.append(_error(path, "condition_too_deep", f"a condition tree is at most {MAX_TREE_DEPTH} levels deep"))
        return
    budget[0] -= 1
    if budget[0] < 0:
        issues.append(_error(path, "condition_too_large", f"a condition tree is at most {MAX_TREE_NODES} nodes"))
        return

    if not isinstance(node, dict):
        issues.append(_error(path, "condition_invalid", "a condition is an object"))
        return
    if not node:
        return

    keys = set(node)
    if keys & {"AND", "OR", "NOT"}:
        if len(keys) != 1:
            issues.append(_error(path, "condition_invalid", "a group node holds exactly one of AND, OR, NOT"))
            return
        operator = next(iter(keys))
        children = node[operator]
        if operator == "NOT":
            _validate_condition(
                children,
                f"{path}.NOT",
                issues,
                context=context,
                kind=kind,
                known_groups=known_groups,
                has_target=has_target,
                depth=depth + 1,
                budget=budget,
            )
            return
        if not isinstance(children, list) or not children:
            issues.append(_error(f"{path}.{operator}", "condition_invalid", f"{operator} needs a non-empty list"))
            return
        for index, child in enumerate(children):
            _validate_condition(
                child,
                f"{path}.{operator}[{index}]",
                issues,
                context=context,
                kind=kind,
                known_groups=known_groups,
                has_target=has_target,
                depth=depth + 1,
                budget=budget,
            )
        return

    if keys - {"type", "params"}:
        issues.append(_error(path, "condition_invalid", "a leaf node holds only type and params"))
        return
    leaf_type = node.get("type")
    spec = LEAVES.get(str(leaf_type))
    if spec is None:
        issues.append(_error(f"{path}.type", "unknown_leaf", f"unknown condition {leaf_type!r}"))
        return
    if context not in spec.contexts:
        issues.append(_error(path, "leaf_context", f"{spec.type} cannot be used in a {context} condition"))
        return
    if kind not in spec.kinds:
        issues.append(_error(path, "leaf_kind", f"{spec.type} does not apply to {kind} pick-ban"))
    if spec.requires_target and (context == "pool" or not has_target):
        issues.append(_error(path, "leaf_requires_target", f"{spec.type} needs a step that names a target"))
    params = node.get("params") or {}
    if not isinstance(params, dict):
        issues.append(_error(f"{path}.params", "condition_invalid", "params is an object"))
        return
    if context == "pool" and spec.relative and str(params.get("by")) != "any":
        issues.append(
            _error(f"{path}.params.by", "leaf_relative_in_pool", f"a pool filter can only read {spec.type} by 'any'")
        )
    _validate_params(spec.params, params, path, issues, known_groups=known_groups)


def _validate_params(
    specs: tuple[ParamSpec, ...],
    params: Mapping[str, Any],
    path: str,
    issues: list[Issue],
    *,
    known_groups: set[str] | None,
) -> None:
    declared = {spec.name for spec in specs}
    for name in params:
        if name not in declared:
            issues.append(_error(f"{path}.params.{name}", "unknown_param", f"unknown parameter {name!r}"))

    for spec in specs:
        param_path = f"{path}.params.{spec.name}"
        if spec.name not in params:
            if spec.required:
                issues.append(_error(param_path, "missing_param", f"parameter {spec.name!r} is required"))
            continue
        value = params[spec.name]
        if value is None:
            if not spec.nullable:
                issues.append(_error(param_path, "invalid_param", f"parameter {spec.name!r} cannot be null"))
            continue
        _validate_param_value(spec, value, param_path, issues, known_groups=known_groups)


def _validate_param_value(
    spec: ParamSpec,
    value: Any,
    path: str,
    issues: list[Issue],
    *,
    known_groups: set[str] | None,
) -> None:
    match spec.kind:
        case "enum":
            if spec.values is not None and str(value) not in spec.values:
                issues.append(_error(path, "invalid_param", f"expected one of {', '.join(spec.values)}"))
        case "int":
            if isinstance(value, bool) or not isinstance(value, int):
                issues.append(_error(path, "invalid_param", "expected an integer"))
                return
            if spec.min is not None and value < spec.min:
                issues.append(_error(path, "param_range", f"must be at least {spec.min}"))
            if spec.max is not None and value > spec.max:
                issues.append(_error(path, "param_range", f"must be at most {spec.max}"))
        case "bool":
            if not isinstance(value, bool):
                issues.append(_error(path, "invalid_param", "expected a boolean"))
        case "item_list":
            if not isinstance(value, list) or not value:
                issues.append(_error(path, "invalid_param", "expected a non-empty list of item ids"))
                return
            if any(isinstance(item, bool) or not isinstance(item, int) for item in value):
                issues.append(_error(path, "invalid_param", "item ids are integers"))
        case "group_list":
            if not isinstance(value, list) or not value:
                issues.append(_error(path, "invalid_param", "expected a non-empty list of groups"))
                return
            for group in value:
                _validate_group(group, path, issues, known_groups=known_groups)
        case "group":
            _validate_group(value, path, issues, known_groups=known_groups)


def _validate_group(value: Any, path: str, issues: list[Issue], *, known_groups: set[str] | None) -> None:
    if not isinstance(value, str) or not value.strip():
        issues.append(_error(path, "invalid_param", "expected a group name"))
        return
    if known_groups is not None and normalize_group(value) not in known_groups:
        issues.append(_error(path, "unknown_group", f"unknown group {value!r}"))


# ── warnings ────────────────────────────────────────────────────────────────


def _coverage_warnings(ruleset: Ruleset, *, kind: str) -> list[Issue]:
    """Rounds no phase covers, and previous-round actors on a round-1 phase."""
    from .compile import select_phase
    from .registry import RoundCtx

    issues: list[Issue] = []
    uncovered: list[int] = []
    for map_index in PREVIEW_MAPS:
        # Checked against both a long series and one ending here, so a phase
        # gated on `is_last_map` does not read as a hole.
        covered = any(
            select_phase(ruleset, RoundCtx(round=map_index, best_of=best_of, kind=kind)) is not None
            for best_of in (max(PREVIEW_MAPS), map_index)
        )
        if not covered:
            uncovered.append(map_index)
    if uncovered:
        rounds = ", ".join(str(index) for index in uncovered)
        issues.append(_warning("phases", "map_not_covered", f"no phase matches map {rounds}"))

    for index, phase in enumerate(ruleset.phases):
        if not _matches_round_one_only(phase, kind=kind):
            continue
        for step_index, step in enumerate(phase.steps):
            if step.actors in ("winner_prev", "loser_prev"):
                issues.append(
                    _warning(
                        f"phases[{index}].steps[{step_index}].actors",
                        "previous_round_on_first_map",
                        f"{step.actors} falls back to first/second on the opening map",
                    )
                )
    return issues


def _matches_round_one_only(phase: Phase, *, kind: str) -> bool:
    from .compile import phase_matches
    from .registry import RoundCtx

    if not phase_matches(phase, RoundCtx(round=1, best_of=5, kind=kind)):
        return False
    return not any(phase_matches(phase, RoundCtx(round=round, best_of=5, kind=kind)) for round in range(2, 6))
