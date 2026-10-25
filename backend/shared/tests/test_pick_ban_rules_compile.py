"""Compilation: v1 -> v2 conversion, generators, phase selection, actors.

The conversion table is the migration's contract — every one of the tournament's
existing configs runs through it on 2026-10-03, and a migrated config must
behave exactly like it did under v1 (design D1, §11).
"""

import pytest

from shared.domain import pick_ban_rules as pbr

# ── v1 sequence generators (moved verbatim out of tournament-service) ────────


@pytest.mark.parametrize(
    ("best_of", "pool_size", "expected"),
    [
        # Bo1 bans everything but one map, then the decider names it.
        (1, 4, ["ban_first", "ban_second", "ban_first", "decider"]),
        # Bo3 over 7 maps: two lead bans, two picks, decider for the last map.
        (3, 7, ["ban_first", "ban_second", "pick_first", "pick_second", "decider"]),
        # Nothing to ban when the pool is exactly the series length.
        (3, 3, ["pick_first", "pick_second", "decider"]),
        (5, 7, ["ban_first", "ban_second", "pick_first", "pick_second", "pick_first", "pick_second", "decider"]),
        # An even best_of picks every map, no decider.
        (2, 5, ["ban_first", "ban_second", "pick_first", "pick_second"]),
        (3, 0, []),
    ],
)
def test_build_sequence_for_best_of_matches_v1(best_of, pool_size, expected):
    assert pbr.build_sequence_for_best_of(best_of, pool_size) == expected


def test_build_slot_sequence_alternates_the_slot_opener():
    assert pbr.build_slot_sequence([3, 3], rotation="alternate") == [
        "ban_first",
        "ban_second",
        "decider",
        "ban_second",
        "ban_first",
        "decider",
    ]


def test_build_slot_sequence_fixed_keeps_one_opener():
    assert pbr.build_slot_sequence([3, 3], rotation="fixed") == [
        "ban_first",
        "ban_second",
        "decider",
        "ban_first",
        "ban_second",
        "decider",
    ]


# ── v1 token -> step ────────────────────────────────────────────────────────


def test_v1_token_becomes_a_count_one_open_single_actor_step():
    (step,) = pbr.steps_from_v1_tokens(["ban_second"], kind="map")
    assert step.action == "ban"
    assert step.actors == "second"
    assert step.count == 1
    assert step.min is None
    assert step.blind is False
    assert step.target is None
    assert step.lifetime == 1
    assert step.timer_seconds is None
    assert step.on_timeout is None
    assert step.dispute.enabled is False
    assert step.dispute.max == 0
    assert step.eligible == {}
    assert step.constraints == []


def test_v1_decider_becomes_a_system_step():
    (step,) = pbr.steps_from_v1_tokens(["decider"], kind="map")
    assert (step.action, step.actors) == ("decider", "system")


def test_hero_sequence_drops_the_decider():
    steps = pbr.steps_from_v1_tokens(["ban_first", "ban_second", "decider"], kind="hero")
    assert [step.action for step in steps] == ["ban", "ban"]


def test_step_ids_are_unique_and_id_shaped():
    steps = pbr.steps_from_v1_tokens(["ban_first", "ban_first", "protect_second"], kind="hero")
    ids = [step.id for step in steps]
    assert len(set(ids)) == 3
    assert not pbr.validate_ruleset(
        {
            "version": 2,
            "timer_seconds": None,
            "on_timeout": "wait",
            "phases": [
                {
                    "id": "main",
                    "name": None,
                    "when": {},
                    "pool_filter": {},
                    "generator": None,
                    "steps": [step.model_dump() for step in steps],
                }
            ],
        },
        kind="hero",
        mode="pool",
        discipline="overwatch",
    )


def test_unknown_token_is_rejected():
    with pytest.raises(ValueError):
        pbr.steps_from_v1_tokens(["nuke_first"], kind="map")


# ── ruleset_from_v1 ─────────────────────────────────────────────────────────


def v1(**overrides):
    payload = {
        "kind": "hero",
        "mode": "pool",
        "preset": "custom",
        "sequence": ["ban_first", "ban_second"],
        "no_repeat_scope": "none",
        "unique_attribute": None,
        "turn_timer_seconds": 45,
    }
    payload.update(overrides)
    return pbr.ruleset_from_v1(**payload)


def test_config_conversion_keeps_the_timer_and_random_fills_on_timeout():
    ruleset = v1()
    assert ruleset.version == 2
    assert ruleset.timer_seconds == 45
    assert ruleset.on_timeout == "random_fill"
    (phase,) = ruleset.phases
    assert (phase.id, phase.name, phase.when, phase.pool_filter, phase.generator) == ("main", None, {}, {}, None)
    assert [step.actors for step in phase.steps] == ["first", "second"]


def test_map_slots_config_converts_to_the_slot_generator():
    ruleset = v1(kind="map", mode="slots", preset="custom", sequence=["ban_first"])
    (phase,) = ruleset.phases
    assert phase.generator == "slot_veto"
    assert phase.steps == []


def test_map_pool_preset_converts_to_the_bracket_generator():
    (phase,) = v1(kind="map", preset="bracket", sequence=["ban_first"]).phases
    assert phase.generator == "bracket"
    assert phase.steps == []


def test_custom_map_pool_config_keeps_its_own_sequence():
    (phase,) = v1(kind="map", preset="custom", sequence=["ban_first", "pick_second", "decider"]).phases
    assert phase.generator is None
    assert [step.action for step in phase.steps] == ["ban", "pick", "decider"]


def test_no_repeat_encounter_becomes_a_pool_filter():
    (phase,) = v1(no_repeat_scope="encounter").phases
    assert phase.pool_filter == {"NOT": {"type": "banned_by", "params": {"by": "any", "scope": "series"}}}
    assert all(step.eligible == {} for step in phase.steps)


def test_no_repeat_same_side_becomes_an_eligibility_rule_on_ban_steps():
    (phase,) = v1(no_repeat_scope="encounter_same_side", sequence=["ban_first", "protect_second"]).phases
    assert phase.pool_filter == {}
    ban, protect = phase.steps
    assert ban.eligible == {"NOT": {"type": "banned_by", "params": {"by": "self", "scope": "series"}}}
    assert protect.eligible == {}


def test_unique_role_becomes_a_round_scoped_max_per_group():
    (phase,) = v1(unique_attribute="role", sequence=["ban_first", "protect_second", "pick_first"]).phases
    ban, protect, pick = phase.steps
    expected = {"type": "max_per_group", "params": {"max": 1, "scope": "round", "group": None}}
    assert [constraint.to_json() for constraint in ban.constraints] == [expected]
    assert [constraint.to_json() for constraint in protect.constraints] == [expected]
    assert pick.constraints == []


def test_converted_configs_validate_clean():
    for kind, mode, preset in (("hero", "pool", "custom"), ("map", "slots", "custom"), ("map", "pool", "bracket")):
        ruleset = v1(
            kind=kind,
            mode=mode,
            preset=preset,
            sequence=["ban_first", "pick_second", "decider"],
            no_repeat_scope="encounter",
            unique_attribute="role",
        )
        # A hero pick needs a game that fields a hero once per match (spec §11.2); Overwatch fields one per team.
        discipline = "deadlock" if kind == "hero" else "overwatch"
        assert pbr.validate_ruleset(ruleset.to_json(), kind=kind, mode=mode, discipline=discipline) == []


# ── phase selection ─────────────────────────────────────────────────────────


ANTI = {preset.id: preset for preset in pbr.presets_for("overwatch")}["hero_anti_one_trick"].ruleset


@pytest.mark.parametrize(("round_number", "phase_id"), [(1, "map1"), (2, "map2plus"), (5, "map2plus")])
def test_phase_selection_by_map_index(round_number, phase_id):
    phase = pbr.select_phase(ANTI, pbr.RoundCtx(round=round_number, best_of=5, kind="hero"))
    assert phase is not None and phase.id == phase_id


def test_first_matching_phase_wins():
    ruleset = pbr.parse_ruleset(
        {
            "version": 2,
            "timer_seconds": None,
            "on_timeout": "wait",
            "phases": [
                {"id": "any", "when": {}, "steps": [{"id": "a", "action": "ban", "actors": "first"}]},
                {"id": "late", "when": {"type": "map_index", "params": {"op": ">=", "value": 2}}, "steps": []},
            ],
        }
    )
    phase = pbr.select_phase(ruleset, pbr.RoundCtx(round=3, best_of=5, kind="hero"))
    assert phase is not None and phase.id == "any"


def test_no_phase_matches_resolves_to_no_steps():
    assert pbr.select_phase(ANTI, pbr.RoundCtx(round=0, best_of=5, kind="hero")) is None
    assert (
        pbr.resolve_round(ANTI, kind="hero", round=0, start_index=0, participants=SEATS, opener=SLOT1, best_of=5) == []
    )


# ── actor resolution ────────────────────────────────────────────────────────


#: Participation ids: the resolved actor vocabulary (§13.4), slot 1 and slot 2.
SLOT1, SLOT2 = 11, 22
SEATS = (SLOT1, SLOT2)


@pytest.mark.parametrize(
    ("actors", "prev", "expected"),
    [
        ("first", None, [SLOT2]),
        ("second", None, [SLOT1]),
        ("both", None, [SLOT2, SLOT1]),
        # The pre-slot spelling, still read off a stored document.
        ("home", None, [SLOT1]),
        ("away", None, [SLOT2]),
        ("slot:1", None, [SLOT1]),
        ("slot:2", None, [SLOT2]),
        ("system", None, [None]),
        ("winner_prev", SLOT1, [SLOT1]),
        ("loser_prev", SLOT1, [SLOT2]),
        # No previous round, or a drawn one (no winner): fall back to
        # first/second.
        ("winner_prev", None, [SLOT2]),
        ("loser_prev", None, [SLOT1]),
    ],
)
def test_resolve_actors(actors, prev, expected):
    assert pbr.resolve_actors(actors, participants=SEATS, opener=SLOT2, prev_winner=prev) == expected


def test_a_side_actor_needs_the_side_pick_that_assigned_it():
    assert pbr.resolve_actors("side:attack", participants=SEATS, opener=SLOT1, sides={"attack": SLOT2}) == [SLOT2]
    with pytest.raises(ValueError, match="before any step assigned side"):
        pbr.resolve_actors("side:attack", participants=SEATS, opener=SLOT1)


def test_a_slot_outside_the_card_is_refused():
    with pytest.raises(ValueError, match="does not seat"):
        pbr.resolve_actors("slot:3", participants=SEATS, opener=SLOT1)


# ── resolve_round ───────────────────────────────────────────────────────────


def test_resolve_round_inherits_timer_and_fills_min():
    steps = pbr.resolve_round(ANTI, kind="hero", round=2, start_index=7, participants=SEATS, opener=SLOT2, best_of=5)
    (step,) = steps
    assert step.index == 7
    assert step.round == 2
    assert step.phase_id == "map2plus"
    assert step.step_id == "perplayer5"
    assert step.actors == [SLOT2, SLOT1]
    assert step.count == 5
    assert step.min == 5  # null inherits count
    assert step.timer_seconds == 90  # inherited from the ruleset
    assert step.on_timeout == "random_fill"
    assert step.lifetime == 2


def test_resolve_round_bracket_generator_matches_the_v1_sequence():
    ruleset = pbr.GENERIC_PRESETS_BY_ID["map_bracket"].ruleset
    steps = pbr.resolve_round(
        ruleset, kind="map", round=None, start_index=0, participants=SEATS, opener=SLOT1, best_of=3, pool_size=7
    )
    tokens = pbr.build_sequence_for_best_of(3, 7)
    assert len(steps) == len(tokens)
    assert [step.action for step in steps] == ["ban", "ban", "pick", "pick", "decider"]
    assert [step.actors for step in steps] == [[SLOT1], [SLOT2], [SLOT1], [SLOT2], [None]]
    assert all(step.round is None for step in steps)


def test_resolve_round_slot_generator_uses_fixed_rotation_per_round():
    ruleset = pbr.GENERIC_PRESETS_BY_ID["map_slot_veto"].ruleset
    first = pbr.resolve_round(
        ruleset, kind="map", round=1, start_index=0, participants=SEATS, opener=SLOT1, best_of=3, candidate_count=3
    )
    second = pbr.resolve_round(
        ruleset,
        kind="map",
        round=2,
        start_index=len(first),
        participants=SEATS,
        opener=SLOT2,
        best_of=3,
        candidate_count=3,
    )
    # The opener already rotates per round; the generator itself must not rotate
    # again, or the two rotations would cancel out.
    assert [step.actors for step in first] == [[SLOT1], [SLOT2], [None]]
    assert [step.actors for step in second] == [[SLOT2], [SLOT1], [None]]
    assert [step.index for step in second] == [3, 4, 5]


def test_hero_round_drops_a_decider_step():
    ruleset = pbr.parse_ruleset(
        {
            "version": 2,
            "phases": [
                {
                    "id": "main",
                    "steps": [
                        {"id": "b", "action": "ban", "actors": "first"},
                        {"id": "d", "action": "decider", "actors": "system"},
                    ],
                }
            ],
        }
    )
    steps = pbr.resolve_round(ruleset, kind="hero", round=1, start_index=0, participants=SEATS, opener=SLOT1, best_of=1)
    assert [step.action for step in steps] == ["ban"]


def test_resolved_step_round_trips_through_json():
    (step,) = pbr.resolve_round(ANTI, kind="hero", round=1, start_index=0, participants=SEATS, opener=SLOT1, best_of=5)
    assert pbr.ResolvedStep.from_json(step.to_json()) == step


# ── member steps (spec §11.6 R4-1, R4-2) ─────────────────────────────────────

MEMBERS = {SLOT1: (101, 102, 103), SLOT2: (201, 202, 203)}


def _member_steps(*steps: dict) -> list[pbr.ResolvedStep]:
    ruleset = pbr.parse_ruleset({"version": 2, "phases": [{"id": "main", "steps": list(steps)}]})
    return pbr.resolve_round(
        ruleset, kind="hero", round=1, start_index=0, participants=SEATS, opener=SLOT1, members=MEMBERS
    )


def test_next_steps_go_to_each_teams_members_in_pick_order():
    steps = _member_steps(
        {"id": "p1", "action": "pick", "actors": "first", "member": "next"},
        {"id": "p2", "action": "pick", "actors": "second", "member": "next"},
        {"id": "p3", "action": "pick", "actors": "both", "member": "next"},
    )
    assert [step.member_seats for step in steps] == [[(SLOT1, 101)], [(SLOT2, 201)], [(SLOT1, 102), (SLOT2, 202)]]
    assert steps[0].answers == [(SLOT1, 101)]


def test_an_each_step_owes_every_member_of_its_teams():
    (step,) = _member_steps({"id": "all", "action": "pick", "actors": "both", "member": "each"})
    assert step.answers == [(SLOT1, 101), (SLOT1, 102), (SLOT1, 103), (SLOT2, 201), (SLOT2, 202), (SLOT2, 203)]


def test_a_side_bound_member_step_gets_its_member_once_its_side_does():
    (resolved,) = _member_steps({"id": "p", "action": "pick", "actors": "first", "member": "next"})
    waiting = resolved.model_copy(update={"actors": [], "actors_token": "side:blue", "member_seats": []})
    assert pbr.bind_members([waiting], MEMBERS)[0].member_seats == []

    (bound,) = pbr.bind_members([waiting.model_copy(update={"actors": [SLOT2]})], MEMBERS)

    assert bound.member_seats == [(SLOT2, 201)]
    assert bound.unbound().member_seats == []
    assert pbr.ResolvedStep.from_json(bound.to_json()) == bound


def test_a_free_pick_names_its_player_and_hands_the_teams_later_turns_the_rest_in_pick_order():
    steps = _member_steps(
        *(
            {"id": f"p{index}", "action": "pick", "actors": actors, "member": "any"}
            for index, actors in enumerate(("first", "second", "first", "first"))
        )
    )
    assert pbr.free_pick_choices(steps, steps[0], SLOT1, MEMBERS) == [101, 102, 103]

    rebound = pbr.rebind_free_pick(steps, steps[0], SLOT1, 103, MEMBERS)

    # The clock's stand-in for a later turn is the first player left in pick order; the other team is untouched.
    assert [step.member_seats for step in rebound] == [[(SLOT1, 103)], [(SLOT2, 201)], [(SLOT1, 101)], [(SLOT1, 102)]]
    assert pbr.free_pick_choices(rebound, rebound[2], SLOT1, MEMBERS) == [101, 102]
    with pytest.raises(ValueError):
        pbr.rebind_free_pick(rebound, rebound[2], SLOT1, 103, MEMBERS)


def test_team_steps_store_no_member_keys():
    # R-F4a: a ruleset and a session of team steps only stay byte-compatible with readers that predate member picks.
    ruleset = pbr.parse_ruleset(
        {"version": 2, "phases": [{"id": "main", "steps": [{"id": "b", "action": "ban", "actors": "first"}]}]}
    )
    (stored,) = ruleset.to_json()["phases"][0]["steps"]
    assert "member" not in stored
    assert pbr.parse_ruleset(ruleset.to_json()) == ruleset

    (step,) = pbr.resolve_round(ruleset, kind="hero", round=1, start_index=0, participants=SEATS, opener=SLOT1)
    assert {"member", "member_seats", "captains_only"}.isdisjoint(step.to_json())
    assert pbr.ResolvedStep.from_json(step.to_json()) == step
