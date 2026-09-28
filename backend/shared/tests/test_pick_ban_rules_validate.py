"""What the constructor may save. Every rule here is one an organizer can hit
by dragging a step into the wrong place, so each has a stable code and a path.
"""

import pytest

from shared.domain import pick_ban_rules as pbr


def step(**overrides):
    payload = {
        "id": "s1",
        "action": "ban",
        "actors": "first",
        "count": 1,
        "min": None,
        "blind": False,
        "target": None,
        "lifetime": None,
        "timer_seconds": None,
        "on_timeout": None,
        "dispute": {"enabled": False, "max": 0},
        "eligible": {},
        "constraints": [],
    }
    payload.update(overrides)
    return payload


def ruleset(*steps, phase=None, **overrides):
    phase_payload = {
        "id": "main",
        "name": None,
        "when": {},
        "pool_filter": {},
        "generator": None,
        "steps": list(steps),
    }
    phase_payload.update(phase or {})
    payload = {"version": 2, "timer_seconds": None, "on_timeout": "random_fill", "phases": [phase_payload]}
    payload.update(overrides)
    return payload


def codes(document, *, kind="hero", mode="pool", severity="error", groups=None):
    return [
        issue.code
        for issue in pbr.validate_ruleset(document, kind=kind, mode=mode, groups=groups)
        if issue.severity == severity
    ]


def test_a_valid_hero_ruleset_has_no_issues():
    assert pbr.validate_ruleset(ruleset(step()), kind="hero", mode="pool") == []


# ── shape ───────────────────────────────────────────────────────────────────


def test_non_object_is_rejected():
    assert codes([]) == ["schema_invalid"]


def test_unknown_field_is_rejected_with_its_path():
    issues = pbr.validate_ruleset(ruleset(step(nope=1)), kind="hero", mode="pool")
    assert [(issue.path, issue.code) for issue in issues] == [
        ("phases[0].steps[0].nope", "schema_invalid"),
    ]


def test_parse_ruleset_raises_with_issues():
    with pytest.raises(pbr.RulesetError) as exc:
        pbr.parse_ruleset({"version": 3, "phases": []})
    assert [issue.path for issue in exc.value.issues] == ["version"]


def test_a_ruleset_needs_a_phase():
    assert codes({"version": 2, "phases": []}) == ["phases_empty"]


def test_ids_are_unique_and_slug_shaped():
    document = ruleset(step(id="a"), step(id="a"))
    assert codes(document) == ["duplicate_step_id"]
    document = ruleset(step(id="Nope Nope"))
    assert codes(document) == ["invalid_id"]


def test_duplicate_phase_ids_are_rejected():
    document = ruleset(step())
    document["phases"].append(dict(document["phases"][0], steps=[step(id="s2")]))
    assert codes(document) == ["duplicate_phase_id"]


# ── generators ──────────────────────────────────────────────────────────────


def test_generator_is_map_only():
    assert codes(ruleset(phase={"generator": "bracket", "steps": []})) == ["generator_map_only"]


def test_bracket_needs_pool_mode_and_slot_veto_needs_slots():
    assert codes(ruleset(phase={"generator": "bracket", "steps": []}), kind="map", mode="slots") == [
        "generator_requires_pool_mode"
    ]
    assert codes(ruleset(phase={"generator": "slot_veto", "steps": []}), kind="map", mode="pool") == [
        "generator_requires_slots_mode"
    ]


def test_a_generated_phase_declares_no_steps():
    document = ruleset(step(action="pick"), phase={"generator": "bracket"})
    assert codes(document, kind="map", mode="pool") == ["generator_with_steps"]


# ── decider ─────────────────────────────────────────────────────────────────


def test_decider_is_map_only():
    assert "decider_map_only" in codes(ruleset(step(action="decider", actors="system")))


def test_decider_is_resolved_by_the_system_and_settles_one_item():
    document = ruleset(step(action="decider", actors="first", count=2))
    assert set(codes(document, kind="map")) >= {"decider_actors", "decider_count"}


def test_decider_must_close_its_phase():
    document = ruleset(step(id="d", action="decider", actors="system"), step(id="b", action="ban", actors="first"))
    assert "decider_not_last" in codes(document, kind="map")


def test_at_most_one_decider_per_phase():
    document = ruleset(
        step(id="d1", action="decider", actors="system"), step(id="d2", action="decider", actors="system")
    )
    assert "decider_duplicate" in codes(document, kind="map")


def test_a_map_phase_must_settle_a_map():
    assert codes(ruleset(step()), kind="map", mode="pool") == ["map_phase_without_pick"]
    assert codes(ruleset(step(action="pick")), kind="map", mode="pool") == []


def test_a_phase_needs_steps():
    assert codes(ruleset(phase={"steps": []})) == ["phase_without_steps"]


# ── step fields ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("count", [0, 21, -1])
def test_count_is_bounded(count):
    assert "count_range" in codes(ruleset(step(count=count)))


@pytest.mark.parametrize(("count", "minimum"), [(3, 4), (3, -1)])
def test_min_is_between_zero_and_count(count, minimum):
    assert "min_range" in codes(ruleset(step(count=count, min=minimum)))


def test_min_zero_is_allowed():
    assert codes(ruleset(step(count=3, min=0))) == []


def test_target_is_hero_only_and_never_system():
    assert "target_hero_only" in codes(ruleset(step(action="pick", target="opponent_player")), kind="map")
    assert "target_system" in codes(ruleset(step(actors="system", target="opponent_player")))


def test_target_is_not_allowed_on_a_decider():
    document = ruleset(step(action="decider", actors="system", target="opponent_player"))
    assert "target_action" in codes(document, kind="map")


def test_lifetime_is_ban_only_and_at_least_one():
    assert "lifetime_ban_only" in codes(ruleset(step(action="pick", lifetime=1)))
    assert "lifetime_range" in codes(ruleset(step(lifetime=0)))
    assert codes(ruleset(step(lifetime=None))) == []


def test_timers_are_at_least_five_seconds():
    assert "timer_range" in codes(ruleset(step(timer_seconds=4)))
    assert "timer_range" in codes(ruleset(step(), timer_seconds=1))


def test_dispute_max_is_bounded():
    assert "dispute_range" in codes(ruleset(step(dispute={"enabled": True, "max": 6})))


def test_a_system_step_cannot_be_blind():
    assert "blind_system" in codes(ruleset(step(actors="system", blind=True)))


# ── constraints ─────────────────────────────────────────────────────────────


def test_unknown_constraint_is_rejected():
    assert codes(ruleset(step(constraints=[{"type": "nope", "params": {}}]))) == ["unknown_constraint"]


def test_one_per_target_needs_a_target():
    document = ruleset(step(constraints=[{"type": "one_per_target", "params": {}}]))
    assert codes(document) == ["constraint_requires_target"]
    document = ruleset(step(target="opponent_player", constraints=[{"type": "one_per_target", "params": {}}]))
    assert codes(document) == []


def test_constraint_params_are_typed():
    assert "missing_param" in codes(ruleset(step(constraints=[{"type": "max_per_group", "params": {"max": 1}}])))
    assert "param_range" in codes(
        ruleset(step(constraints=[{"type": "max_per_group", "params": {"max": 0, "scope": "step"}}]))
    )
    assert "invalid_param" in codes(
        ruleset(step(constraints=[{"type": "max_per_group", "params": {"max": 1, "scope": "series"}}]))
    )
    assert "unknown_param" in codes(
        ruleset(step(constraints=[{"type": "max_per_group", "params": {"max": 1, "scope": "step", "nope": 1}}]))
    )


def test_max_per_group_accepts_a_null_group():
    document = ruleset(
        step(constraints=[{"type": "max_per_group", "params": {"max": 1, "scope": "round", "group": None}}])
    )
    assert codes(document) == []


def test_group_names_are_checked_against_the_kind():
    document = ruleset(step(constraints=[{"type": "min_per_group", "params": {"min": 1, "group": "bastion"}}]))
    assert codes(document) == ["unknown_group"]
    ok = ruleset(step(constraints=[{"type": "min_per_group", "params": {"min": 1, "group": "Tank"}}]))
    assert codes(ok) == []


def test_map_group_names_are_checked_against_the_supplied_vocabulary():
    document = ruleset(
        step(action="pick", eligible={"type": "item_group", "params": {"groups": ["koth"]}}),
    )
    assert codes(document, kind="map", groups=["control", "hybrid"]) == ["unknown_group"]
    assert codes(document, kind="map", groups=None) == []


# ── condition trees ─────────────────────────────────────────────────────────


def test_unknown_leaf_is_rejected():
    assert codes(ruleset(step(eligible={"type": "nope", "params": {}}))) == ["unknown_leaf"]


def test_leaf_context_is_enforced():
    assert codes(ruleset(step(eligible={"type": "map_index", "params": {"op": "==", "value": 1}}))) == ["leaf_context"]
    assert codes(ruleset(step(), phase={"when": {"type": "item_in", "params": {"item_ids": [1]}}})) == ["leaf_context"]


def test_leaf_kind_is_enforced():
    document = ruleset(step(action="pick", target=None, eligible={"type": "target_role_match", "params": {}}))
    assert "leaf_kind" in codes(document, kind="map")


def test_target_leaves_need_a_target_step():
    assert codes(ruleset(step(eligible={"type": "target_role_match", "params": {}}))) == ["leaf_requires_target"]
    ok = ruleset(step(target="opponent_player", eligible={"type": "target_role_match", "params": {}}))
    assert codes(ok) == []


def test_pool_filter_refuses_relative_leaves():
    document = ruleset(
        step(), phase={"pool_filter": {"type": "banned_by", "params": {"by": "self", "scope": "series"}}}
    )
    assert codes(document) == ["leaf_relative_in_pool"]
    ok = ruleset(step(), phase={"pool_filter": {"type": "banned_by", "params": {"by": "any", "scope": "series"}}})
    assert codes(ok) == []


def test_pool_filter_refuses_target_leaves():
    # A pool filter has no acting side and no target, so the leaf is not even
    # offered in that context.
    document = ruleset(step(), phase={"pool_filter": {"type": "target_role_match", "params": {}}})
    assert codes(document) == ["leaf_context"]


def test_group_nodes_are_structural():
    assert codes(ruleset(step(eligible={"AND": []}))) == ["condition_invalid"]
    assert codes(ruleset(step(eligible={"AND": [{}], "OR": [{}]}))) == ["condition_invalid"]
    assert codes(ruleset(step(eligible={"type": "item_in", "params": {"item_ids": [1]}, "extra": 1}))) == [
        "condition_invalid"
    ]
    assert codes(ruleset(step(eligible={"NOT": {"type": "item_in", "params": {"item_ids": [1]}}}))) == []


def test_condition_depth_and_size_are_capped():
    deep = {"type": "item_in", "params": {"item_ids": [1]}}
    for _ in range(25):
        deep = {"NOT": deep}
    assert "condition_too_deep" in codes(ruleset(step(eligible=deep)))

    wide = {"AND": [{"type": "item_in", "params": {"item_ids": [1]}} for _ in range(250)]}
    assert "condition_too_large" in codes(ruleset(step(eligible=wide)))


# ── warnings ────────────────────────────────────────────────────────────────


def test_uncovered_maps_are_a_warning_not_an_error():
    document = ruleset(step(), phase={"when": {"type": "map_index", "params": {"op": "==", "value": 1}}})
    assert codes(document) == []
    assert codes(document, severity="warning") == ["map_not_covered"]


def test_a_covered_series_has_no_coverage_warning():
    assert codes(pbr.PRESETS_BY_ID["hero_anti_one_trick"].ruleset.to_json(), severity="warning") == []


def test_previous_round_actors_on_the_opening_map_warn():
    document = ruleset(
        step(actors="winner_prev"), phase={"when": {"type": "map_index", "params": {"op": "<=", "value": 1}}}
    )
    assert "previous_round_on_first_map" in codes(document, severity="warning")
