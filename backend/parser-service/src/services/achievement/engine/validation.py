"""Condition tree validation: structure, types, grain compatibility."""

from __future__ import annotations

from typing import Any

from shared.models.achievement import AchievementGrain

from .conditions import get_registered_types, validate_stat_name

# Types accepted inside player sub-condition trees (team_players_match / captain_property).
SUBCONDITION_ONLY_TYPES = {
    "player_role",
    "player_flag",
    "player_sub_role",
    "player_div",
    "is_newcomer",
}

# Types that have no standalone executor and therefore cannot appear at the top
# level. ``is_newcomer`` is dual-use — it has a real top-level executor (e.g. the
# legacy ``dirty-smurf`` rule) and is also valid inside player sub-conditions — so
# it is intentionally excluded here.
TOP_LEVEL_FORBIDDEN_TYPES = SUBCONDITION_ONLY_TYPES - {"is_newcomer"}

# Grain produced by each leaf condition type.
LEAF_GRAINS: dict[str, AchievementGrain] = {
    # Match grain
    "stat_threshold": AchievementGrain.user_match,
    "match_criteria": AchievementGrain.user_match,
    "match_win": AchievementGrain.user_match,
    "hero_stat": AchievementGrain.user_match,
    "match_mvp_check": AchievementGrain.user_match,
    # Tournament grain
    "standing_position": AchievementGrain.user_tournament,
    "standing_record": AchievementGrain.user_tournament,
    "div_change": AchievementGrain.user_tournament,
    "div_level": AchievementGrain.user_tournament,
    "is_captain": AchievementGrain.user_tournament,
    "is_newcomer": AchievementGrain.user_tournament,
    "tournament_type": AchievementGrain.user_tournament,
    "hero_kd_best": AchievementGrain.user_tournament,
    "team_players_match": AchievementGrain.user_tournament,
    "captain_property": AchievementGrain.user_tournament,
    "encounter_score": AchievementGrain.user_tournament,
    "encounter_revenge": AchievementGrain.user_tournament,
    "bracket_path": AchievementGrain.user_tournament,
    "tournament_format": AchievementGrain.user_tournament,
    "log_stat_rank": AchievementGrain.user_tournament,
    "tournament_winrate": AchievementGrain.user_tournament,
    "hero_pickrate": AchievementGrain.user_tournament,
    "team_otp_count": AchievementGrain.user_tournament,
    "reached_playoffs": AchievementGrain.user_tournament,  # user when scope="global"
    # Global grain
    "global_stat_sum": AchievementGrain.user,
    "tournament_count": AchievementGrain.user,
    "global_winrate": AchievementGrain.user,
    "distinct_count": AchievementGrain.user,  # can be user or user_tournament depending on scope
    "consecutive": AchievementGrain.user,
    "stable_streak": AchievementGrain.user,
    "standing_count": AchievementGrain.user,
    "div_span": AchievementGrain.user,
    "teammate_recurrence": AchievementGrain.user,
}

# Grain ordering: finer grains are "larger" (more specific).
GRAIN_ORDER = {
    AchievementGrain.user: 0,
    AchievementGrain.user_tournament: 1,
    AchievementGrain.user_match: 2,
}


def validate_condition_tree(condition: dict[str, Any]) -> list[str]:
    """Validate a condition tree. Returns a list of error strings (empty = valid)."""
    errors: list[str] = []
    _validate_node(condition, errors, path="root")
    return errors


def validate_rule_definition(
    condition_tree: dict[str, Any],
    grain: AchievementGrain | str | None,
) -> tuple[list[str], AchievementGrain | None]:
    """Validate a full rule definition, including metadata consistency."""
    errors = validate_condition_tree(condition_tree)
    inferred_grain = infer_grain(condition_tree) if not errors else None
    if inferred_grain is not None and grain is not None and AchievementGrain(grain) != inferred_grain:
        errors.append(
            f"rule.grain must match inferred grain '{inferred_grain.value}'"
        )
    return errors, inferred_grain


def infer_grain(condition: dict[str, Any]) -> AchievementGrain:
    """Infer the resulting grain of a condition tree."""
    grains = _collect_grains(condition)
    if not grains:
        return AchievementGrain.user
    # Return the finest (most specific) grain
    return max(grains, key=lambda g: GRAIN_ORDER[g])


def _validate_node(
    node: dict[str, Any],
    errors: list[str],
    path: str,
    *,
    in_player_subcondition: bool = False,
) -> None:
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
                )
            return

    if "NOT" in node:
        if in_player_subcondition:
            errors.append(f"{path}.NOT: NOT is not supported inside player sub-conditions")
            return
        _validate_node(node["NOT"], errors, f"{path}.NOT")
        return

    # Leaf node
    ctype = node.get("type")
    if not ctype:
        errors.append(f"{path}: missing 'type' field")
        return

    registered = get_registered_types()
    # Also allow sub-condition types
    all_valid = registered + ["player_role", "player_flag", "player_sub_role", "player_div"]
    if ctype not in all_valid:
        errors.append(f"{path}: unknown condition type '{ctype}'")
        return

    if in_player_subcondition and ctype not in SUBCONDITION_ONLY_TYPES:
        errors.append(f"{path}: unsupported player sub-condition type '{ctype}'")
        return

    if not in_player_subcondition and ctype in TOP_LEVEL_FORBIDDEN_TYPES:
        errors.append(f"{path}: '{ctype}' cannot be used as a top-level condition")
        return

    params = node.get("params", {})
    if not isinstance(params, dict):
        errors.append(f"{path}.params: expected dict")
        return

    # Type-specific param validation
    _validate_leaf_params(ctype, params, errors, path)


def _validate_leaf_params(
    ctype: str,
    params: dict[str, Any],
    errors: list[str],
    path: str,
) -> None:
    """Validate params for a specific leaf type."""
    if ctype == "stat_threshold":
        _require_keys(params, ["stat", "op", "value"], errors, path)
        _validate_stat_param(params, errors, path)
    elif ctype == "match_criteria":
        _require_keys(params, ["field", "op", "value"], errors, path)
        valid_fields = ("closeness", "match_time", "time")
        if params.get("field") not in valid_fields:
            errors.append(f"{path}.params.field: must be one of {valid_fields}")
    elif ctype == "match_win":
        pass  # no params needed
    elif ctype == "standing_position":
        _require_keys(params, ["op", "value"], errors, path)
    elif ctype == "standing_record":
        _require_keys(params, ["field", "op", "value"], errors, path)
    elif ctype == "div_change":
        _require_keys(params, ["direction", "min_shift"], errors, path)
        if params.get("direction") not in ("up", "down"):
            errors.append(f"{path}.params.direction: must be 'up' or 'down'")
    elif ctype == "div_level":
        _require_keys(params, ["op", "value"], errors, path)
    elif ctype == "team_players_match":
        _require_keys(params, ["mode", "condition"], errors, path)
        if params.get("mode") not in ("all", "any", "count"):
            errors.append(f"{path}.params.mode: must be 'all', 'any', or 'count'")
        if params.get("mode") == "count":
            _require_keys(params, ["count_op", "count_value"], errors, path)
        sub = params.get("condition")
        if sub:
            _validate_node(
                sub,
                errors,
                f"{path}.params.condition",
                in_player_subcondition=True,
            )
    elif ctype == "captain_property":
        _require_keys(params, ["condition"], errors, path)
        sub = params.get("condition")
        if sub:
            _validate_node(
                sub,
                errors,
                f"{path}.params.condition",
                in_player_subcondition=True,
            )
    elif ctype == "hero_kd_best":
        pass  # all params optional
    elif ctype == "hero_stat":
        _require_keys(params, ["hero_slug", "stat", "op", "value"], errors, path)
        _validate_stat_param(params, errors, path)
    elif ctype == "encounter_score":
        _require_keys(params, ["scores"], errors, path)
    elif ctype == "encounter_revenge":
        pass
    elif ctype == "global_stat_sum":
        _require_keys(params, ["stat", "op", "value"], errors, path)
        _validate_stat_param(params, errors, path)
    elif ctype == "match_mvp_check":
        if "stat" in params:
            _validate_stat_param(params, errors, path)
    elif ctype == "global_winrate":
        pass  # flexible params
    elif ctype == "tournament_count":
        _require_keys(params, ["op", "value"], errors, path)
    elif ctype == "distinct_count":
        _require_keys(params, ["field", "op", "value"], errors, path)
    elif ctype == "consecutive":
        _require_keys(params, ["metric", "min_streak"], errors, path)
    elif ctype == "stable_streak":
        _require_keys(params, ["fields", "min_streak"], errors, path)
    elif ctype == "log_stat_rank":
        _require_keys(params, ["stat"], errors, path)
        _validate_stat_param(params, errors, path)
    elif ctype == "standing_count":
        _require_keys(params, ["op", "value"], errors, path)
    elif ctype == "tournament_winrate":
        _require_keys(params, ["op", "value"], errors, path)
    elif ctype == "div_span":
        _require_keys(params, ["op", "value"], errors, path)
    elif ctype == "hero_pickrate":
        pass  # op/value optional with defaults
    elif ctype == "teammate_recurrence":
        pass  # op/value optional with defaults
    elif ctype == "team_otp_count":
        pass  # op/value optional with defaults
    elif ctype == "reached_playoffs":
        pass  # scope/op/value optional with defaults
    elif ctype == "player_role":
        _require_keys(params, ["role"], errors, path)
    elif ctype == "player_flag":
        _require_keys(params, ["flag"], errors, path)
    elif ctype == "player_sub_role":
        _require_keys(params, ["sub_role"], errors, path)
    elif ctype == "player_div":
        _require_keys(params, ["op", "value"], errors, path)


def _require_keys(
    params: dict[str, Any],
    keys: list[str],
    errors: list[str],
    path: str,
) -> None:
    for key in keys:
        if key not in params:
            errors.append(f"{path}.params: missing required key '{key}'")


def _validate_stat_param(
    params: dict[str, Any],
    errors: list[str],
    path: str,
) -> None:
    raw = params.get("stat")
    if not isinstance(raw, str):
        return
    stat_error = validate_stat_name(raw)
    if stat_error is not None:
        errors.append(f"{path}.params.stat: {stat_error}")


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
    if ctype and ctype in LEAF_GRAINS:
        scope = node.get("params", {}).get("scope")
        if ctype == "distinct_count" and scope == "tournament":
            grains.append(AchievementGrain.user_tournament)
        elif ctype == "reached_playoffs" and scope == "global":
            grains.append(AchievementGrain.user)
        else:
            grains.append(LEAF_GRAINS[ctype])

    return grains
