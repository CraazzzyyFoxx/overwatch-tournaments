"""Condition tree validation: structure, types, grain compatibility.

Every per-node fact — result grain, which params it takes, which tables it
reads — lives on the node's own ``@register(...)`` call (``engine/conditions``).
This module only enforces the shape; it never keeps a second copy of the node
list, which is how the editor's palette and the validator used to drift apart.
"""

from __future__ import annotations

from typing import Any

from shared.models.achievements.achievement import AchievementGrain
from src.services.achievement.engine.conditions import LeafSpec, get_specs, validate_stat_name

# Grain ordering: finer grains are "larger" (more specific).
GRAIN_ORDER = {
    AchievementGrain.user: 0,
    AchievementGrain.user_tournament: 1,
    AchievementGrain.user_encounter: 2,
    AchievementGrain.user_match: 3,
}

# ``user_encounter`` and ``user_match`` are both 3-tuples: (user, tournament, X).
# Arity alone cannot tell them apart, which is fine — a rule declares exactly one
# grain and ``_reject_mixed_grains`` refuses trees that mix them.
GRAIN_ARITY = {
    AchievementGrain.user: 1,
    AchievementGrain.user_tournament: 2,
    AchievementGrain.user_encounter: 3,
    AchievementGrain.user_match: 3,
}

STANDING_RECORD_FIELDS = frozenset({"wins", "losses", "draws", "points", "buchholz", "matches"})

# Params whose value is drawn from a closed set. Membership is not derivable from
# the spec (the spec names the key, not its domain), so it is stated once here
# instead of in each node's executor.
_ENUM_PARAMS: dict[str, dict[str, tuple[str, ...]]] = {
    "match_criteria": {"field": ("closeness", "match_time", "time")},
    "div_change": {"direction": ("up", "down")},
    "team_players_match": {"mode": ("all", "any", "count")},
    "standing_record": {"field": tuple(sorted(STANDING_RECORD_FIELDS))},
}

# Structural limits on a condition tree, enforced at validation time (before a
# rule is ever saved). A pathologically deep or huge tree would otherwise blow
# the recursion limit in the evaluator on every evaluation run (review L13);
# capping here turns that into a clean validation error instead.
MAX_CONDITION_TREE_DEPTH = 40
MAX_CONDITION_TREE_NODES = 500


def _specs() -> dict[str, LeafSpec]:
    return get_specs()


def __getattr__(name: str) -> Any:
    """Derived views of the registry, resolved on access.

    ``LEAF_GRAINS`` and the two sub-condition sets used to be hand-maintained
    tables; they are now projections of the registered specs. Module-level
    ``__getattr__`` keeps them importable by name without freezing a copy at
    import time (condition modules register on import, order not guaranteed).
    """
    if name == "LEAF_GRAINS":
        return {spec.name: spec.grain for spec in _specs().values()}
    if name == "SUBCONDITION_ONLY_TYPES":
        return {spec.name for spec in _specs().values() if spec.subcondition_only}
    if name == "TOP_LEVEL_FORBIDDEN_TYPES":
        return {spec.name for spec in _specs().values() if spec.subcondition_only}
    raise AttributeError(name)


def validate_condition_tree(condition: dict[str, Any]) -> list[str]:
    """Validate a condition tree. Returns a list of error strings (empty = valid)."""
    errors: list[str] = []
    # ``budget`` is a single-element mutable cell tracking the remaining node
    # allowance across the whole recursion; when it hits zero we record one error
    # and stop descending.
    _validate_node(condition, errors, path="root", depth=0, budget=[MAX_CONDITION_TREE_NODES])
    return errors


def validate_rule_definition(
    condition_tree: dict[str, Any],
    grain: AchievementGrain | str | None,
) -> tuple[list[str], AchievementGrain | None]:
    """Validate a full rule definition, including metadata consistency."""
    errors = validate_condition_tree(condition_tree)
    inferred_grain = infer_grain(condition_tree) if not errors else None
    if inferred_grain is not None and grain is not None and AchievementGrain(grain) != inferred_grain:
        errors.append(f"rule.grain must match inferred grain '{inferred_grain.value}'")
    return errors, inferred_grain


def leaf_grain(ctype: str, params: dict[str, Any] | None = None) -> AchievementGrain | None:
    """Grain of one leaf, including parametric types whose grain depends on params."""
    spec = _specs().get(ctype)
    if spec is None:
        return None
    return spec.resolve_grain(params)


def infer_grain(condition: dict[str, Any]) -> AchievementGrain:
    """Infer the resulting grain of a condition tree.

    Mixed grains are a validation error; this still returns the finest grain so
    callers that run after a failed validate have a stable fallback.
    """
    grains = _collect_grains(condition)
    if not grains:
        return AchievementGrain.user
    unique = set(grains)
    if len(unique) == 1:
        return next(iter(unique))
    return max(grains, key=lambda g: GRAIN_ORDER[g])


def derive_depends_on(condition: dict[str, Any]) -> list[str]:
    """Source tables a tree reads — the union of its leaves' declared tables.

    This is what an evaluation trigger matches its ``changed_tables`` against, so
    getting it wrong means a rule silently stops re-evaluating. Deriving it from
    the tree removes the chance of an author (or an imported rule) getting it
    wrong at all.
    """
    tables: set[str] = set()
    _collect_depends_on(condition, tables)
    return sorted(tables)


def _collect_depends_on(node: dict[str, Any], tables: set[str]) -> None:
    if not isinstance(node, dict) or not node:
        return

    for op in ("AND", "OR"):
        children = node.get(op)
        if isinstance(children, list):
            for child in children:
                _collect_depends_on(child, tables)
            return

    if "NOT" in node:
        _collect_depends_on(node["NOT"], tables)
        return

    spec = _specs().get(node.get("type", ""))
    if spec is not None:
        tables.update(spec.depends_on)

    params = node.get("params")
    if isinstance(params, dict) and isinstance(params.get("condition"), dict):
        _collect_depends_on(params["condition"], tables)


def _validate_node(
    node: dict[str, Any],
    errors: list[str],
    path: str,
    *,
    in_player_subcondition: bool = False,
    depth: int = 0,
    budget: list[int] | None = None,
) -> None:
    if budget is None:
        budget = [MAX_CONDITION_TREE_NODES]

    if depth > MAX_CONDITION_TREE_DEPTH:
        errors.append(f"{path}: condition tree exceeds maximum nesting depth of {MAX_CONDITION_TREE_DEPTH}")
        return
    if budget[0] <= 0:
        # A previous node already exhausted the allowance and recorded the error.
        return
    budget[0] -= 1
    if budget[0] == 0:
        errors.append(f"condition tree exceeds maximum size of {MAX_CONDITION_TREE_NODES} nodes")
        return

    if not isinstance(node, dict):
        errors.append(f"{path}: expected dict, got {type(node).__name__}")
        return

    # Empty dict is valid (no conditions yet)
    if not node:
        return

    # Logical operators
    for op in ("AND", "OR"):
        if op in node:
            children = node[op]
            if not isinstance(children, list) or len(children) < 1:
                errors.append(f"{path}.{op}: must be a non-empty list")
                return
            for i, child in enumerate(children):
                _validate_node(
                    child,
                    errors,
                    f"{path}.{op}[{i}]",
                    in_player_subcondition=in_player_subcondition,
                    depth=depth + 1,
                    budget=budget,
                )
            if not in_player_subcondition:
                _reject_mixed_grains(node, errors, path)
            return

    if "NOT" in node:
        if in_player_subcondition:
            errors.append(f"{path}.NOT: NOT is not supported inside player sub-conditions")
            return
        _validate_node(node["NOT"], errors, f"{path}.NOT", depth=depth + 1, budget=budget)
        _reject_mixed_grains(node, errors, path)
        return

    # Leaf node
    ctype = node.get("type")
    if not ctype:
        errors.append(f"{path}: missing 'type' field")
        return

    spec = _specs().get(ctype)
    if spec is None:
        errors.append(f"{path}: unknown condition type '{ctype}'")
        return

    if in_player_subcondition and not spec.subcondition_ok:
        errors.append(f"{path}: unsupported player sub-condition type '{ctype}'")
        return

    if not in_player_subcondition and spec.subcondition_only:
        errors.append(f"{path}: '{ctype}' cannot be used as a top-level condition")
        return

    params = node.get("params", {})
    if not isinstance(params, dict):
        errors.append(f"{path}.params: expected dict")
        return

    _validate_leaf_params(spec, params, errors, path, depth=depth, budget=budget)


def _validate_leaf_params(
    spec: LeafSpec,
    params: dict[str, Any],
    errors: list[str],
    path: str,
    *,
    depth: int = 0,
    budget: list[int] | None = None,
) -> None:
    """Validate one leaf's params against its registered contract."""
    for key in spec.required:
        if key not in params:
            errors.append(f"{path}.params: missing required key '{key}'")

    known = set(spec.required) | set(spec.optional)
    for key in sorted(set(params) - known):
        # A param the node never reads is a silent no-op — the rule looks
        # configured and behaves as if it were not.
        errors.append(f"{path}.params: unknown key '{key}' for '{spec.name}'")

    for key, allowed in _ENUM_PARAMS.get(spec.name, {}).items():
        value = params.get(key)
        if value is not None and value not in allowed:
            errors.append(f"{path}.params.{key}: must be one of {', '.join(allowed)}")

    if "stat" in known:
        raw = params.get("stat")
        if isinstance(raw, str):
            stat_error = validate_stat_name(raw)
            if stat_error is not None:
                errors.append(f"{path}.params.stat: {stat_error}")

    if spec.name == "team_players_match" and params.get("mode") == "count":
        for key in ("count_op", "count_value"):
            if key not in params:
                errors.append(f"{path}.params: missing required key '{key}'")

    sub = params.get("condition")
    if "condition" in known and isinstance(sub, dict):
        _validate_node(
            sub,
            errors,
            f"{path}.params.condition",
            in_player_subcondition=True,
            depth=depth + 1,
            budget=budget,
        )


def _reject_mixed_grains(node: dict[str, Any], errors: list[str], path: str) -> None:
    grains = {grain.value for grain in _collect_grains(node)}
    if len(grains) > 1:
        names = ", ".join(sorted(grains))
        errors.append(f"{path}: mixed result grains ({names}) are not supported; every leaf must share one grain")


def _collect_grains(node: dict[str, Any]) -> list[AchievementGrain]:
    """Recursively collect grain levels from all leaf nodes."""
    grains = []

    for op in ("AND", "OR"):
        if op in node:
            for child in node[op]:
                grains.extend(_collect_grains(child))
            return grains

    if "NOT" in node:
        return _collect_grains(node["NOT"])

    ctype = node.get("type")
    if not ctype:
        return grains
    params = node.get("params") if isinstance(node.get("params"), dict) else None
    grain = leaf_grain(ctype, params)
    if grain is not None:
        grains.append(grain)

    return grains
