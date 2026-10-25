"""Presets, catalog and series preview.

A preset that does not validate is a broken button in the constructor, and the
preview numbers are what an organizer reads before committing to a format.
"""

from functools import partial
from unittest.mock import patch

import pytest

from shared.disciplines import DISCIPLINES, DisciplineSpec
from shared.domain import pick_ban_rules as pbr

#: Overwatch's own hero presets, by id: they live in its module, not in core.
OVERWATCH = {preset.id: preset for preset in pbr.presets_for("overwatch") if preset.kind == "hero"}
ANTI = OVERWATCH["hero_anti_one_trick"].ruleset
HERO_POOL = {"tank": 13, "damage": 20, "support": 15}
preview_series = partial(pbr.preview_series, discipline="overwatch")


def _mix_only(preset: pbr.Preset) -> bool:
    return any(
        step.member is not None or step.action == "assign" for phase in preset.ruleset.phases for step in phase.steps
    )


def test_every_preset_validates_clean_for_its_kind_and_modes_in_its_discipline():
    for code in DISCIPLINES:
        for preset in pbr.presets_for(code):
            for mode in preset.modes:
                issues = pbr.validate_ruleset(
                    preset.ruleset.to_json(),
                    kind=preset.kind,
                    mode=mode,
                    discipline=code,
                    owner="mix" if _mix_only(preset) else "tournament",
                )
                assert [issue.to_json() for issue in issues if issue.severity == "error"] == []


def test_the_overwatch_presets_are_the_documented_five_then_the_generic_two():
    assert [preset.id for preset in pbr.presets_for("overwatch")] == [
        "hero_classic",
        "hero_protect_ban",
        "hero_blind_2",
        "hero_role_bans",
        "hero_anti_one_trick",
        "map_bracket",
        "map_slot_veto",
    ]


def test_the_lol_preset_is_side_selection_only_and_rotates_to_the_loser():
    preset = pbr.presets_for("lol")[0]
    assert (preset.id, preset.kind, preset.modes) == ("lol_side_selection", "hero", ("pool",))
    assert preset.first_ban_rotation == "result_loser_first"
    (phase,) = preset.ruleset.phases
    (step,) = phase.steps
    assert (step.action, step.actors, step.count, step.blind, step.target) == ("side_pick", "first", 1, False, None)
    assert preset.to_json()["first_ban_rotation"] == "result_loser_first"
    # The every-preset loop above iterates every registered discipline, LoL included.
    assert "lol" in DISCIPLINES
    issues = pbr.validate_ruleset(preset.ruleset.to_json(), kind="hero", mode="pool", discipline="lol")
    assert [issue.to_json() for issue in issues if issue.severity == "error"] == []


def test_the_tournament_preset_is_the_anti_one_trick_rules():
    map1, map2 = ANTI.phases
    (blind2,) = map1.steps
    assert (blind2.actors, blind2.count, blind2.blind, blind2.lifetime, blind2.target) == ("both", 2, True, 1, None)
    (per_player,) = map2.steps
    assert (per_player.actors, per_player.count, per_player.blind, per_player.lifetime) == ("both", 5, True, 2)
    assert per_player.target == "opponent_player"
    assert per_player.eligible == {"type": "target_role_match", "params": {}}
    assert [constraint.type for constraint in per_player.constraints] == ["one_per_target"]


def test_hero_role_bans_caps_one_ban_per_role():
    (phase,) = OVERWATCH["hero_role_bans"].ruleset.phases
    (step,) = phase.steps
    assert step.count == 3
    assert [constraint.to_json() for constraint in step.constraints] == [
        {"type": "max_per_group", "params": {"max": 1, "scope": "step", "group": None}}
    ]


def test_hero_protect_ban_runs_protects_before_bans():
    (phase,) = OVERWATCH["hero_protect_ban"].ruleset.phases
    assert [(step.action, step.actors) for step in phase.steps] == [
        ("protect", "first"),
        ("protect", "second"),
        ("ban", "first"),
        ("ban", "second"),
        ("ban", "second"),
        ("ban", "first"),
    ]


# ── catalog ─────────────────────────────────────────────────────────────────


def test_catalog_exposes_typed_specs_and_presets():
    payload = pbr.catalog(
        discipline="overwatch", groups={"hero": ["tank", "damage", "support"], "map": ["control", "hybrid"]}
    )
    assert payload["groups"] == {"hero": ["tank", "damage", "support"], "map": ["control", "hybrid"]}
    assert [preset["id"] for preset in payload["presets"]] == [preset.id for preset in pbr.presets_for("overwatch")]

    leaves = {leaf["type"]: leaf for leaf in payload["leaves"]}
    assert set(leaves) == set(pbr.LEAVES)
    assert leaves["target_role_match"]["requires_target"] is True
    assert leaves["banned_by"]["relative"] is True
    assert leaves["banned_by"]["contexts"] == ["item", "pool"]
    assert leaves["target_role_match"]["kinds"] == ["hero"]

    by_param = {param["name"]: param for param in leaves["map_index"]["params"]}
    assert by_param["op"]["kind"] == "enum"
    assert by_param["op"]["values"] == ["==", "!=", ">=", ">", "<=", "<"]
    assert by_param["value"] == {
        "name": "value",
        "kind": "int",
        "required": True,
        "values": None,
        "min": 1,
        "max": None,
        "nullable": False,
    }

    constraints = {row["type"]: row for row in payload["constraints"]}
    assert constraints["one_per_target"]["requires_target"] is True
    group_param = next(param for param in constraints["max_per_group"]["params"] if param["name"] == "group")
    assert (group_param["kind"], group_param["required"], group_param["nullable"]) == ("group", False, True)


def test_catalog_groups_are_what_the_caller_resolved_never_a_built_in_class_list():
    assert pbr.catalog(discipline="overwatch")["groups"] == {"hero": [], "map": []}


def test_catalog_presets_are_the_disciplines_own_plus_the_generic_ones():
    overwatch = [preset["id"] for preset in pbr.catalog(discipline="overwatch")["presets"]]
    lol = [preset["id"] for preset in pbr.catalog(discipline="lol")["presets"]]
    assert overwatch == [*OVERWATCH, "map_bracket", "map_slot_veto"]
    assert not {preset_id for preset_id in lol if preset_id.startswith("hero_")}
    assert {"map_bracket", "map_slot_veto"} <= set(lol)


def test_catalog_refuses_a_discipline_nobody_installed_instead_of_substituting_one():
    for code in ("", "starcraft", "OVERWATCH"):
        with pytest.raises(pbr.UnknownDiscipline):
            pbr.catalog(discipline=code)
        with pytest.raises(pbr.UnknownDiscipline):
            pbr.presets_for(code)


def test_a_preset_serializes_its_rotation_and_none_means_leave_it_alone():
    assert {preset["first_ban_rotation"] for preset in pbr.catalog(discipline="overwatch")["presets"]} == {None}
    with_rotation = pbr.Preset("rotating", "hero", ("pool",), ANTI, first_ban_rotation="result_loser_first")
    assert with_rotation.to_json()["first_ban_rotation"] == "result_loser_first"


def test_a_preset_rotation_must_be_a_spelling_the_config_column_accepts():
    with pytest.raises(ValueError):
        pbr.Preset("bad", "hero", ("pool",), ANTI, first_ban_rotation="loser_first")


@pytest.fixture
def rotating_discipline():
    """A stand-in module declaring one lazy side-selection-shaped preset that carries a rotation."""
    calls: list[str] = []

    def presets() -> tuple[pbr.Preset, ...]:
        calls.append("called")
        return (pbr.Preset("rotating_ban", "hero", ("pool",), ANTI, first_ban_rotation="result_loser_first"),)

    spec = DisciplineSpec("rotating", "Rotating", (), character_classes=("bruiser",), pick_ban_presets=presets)
    with patch.dict(DISCIPLINES, {spec.code: spec}):
        assert calls == []  # registering a module never invokes the hook
        yield spec, calls


def test_a_modules_presets_are_invoked_lazily_and_reach_only_its_own_catalog(rotating_discipline):
    spec, calls = rotating_discipline
    payload = pbr.catalog(discipline=spec.code)
    assert calls == ["called"]
    by_id = {preset["id"]: preset for preset in payload["presets"]}
    assert by_id["rotating_ban"]["first_ban_rotation"] == "result_loser_first"
    assert "rotating_ban" not in {preset["id"] for preset in pbr.catalog(discipline="overwatch")["presets"]}


def test_a_module_cannot_shadow_a_generic_preset_id():
    clash = pbr.Preset("map_bracket", "map", ("pool",), pbr.GENERIC_PRESETS_BY_ID["map_bracket"].ruleset)
    spec = DisciplineSpec("clashing", "Clashing", (), pick_ban_presets=lambda: (clash,))
    with patch.dict(DISCIPLINES, {spec.code: spec}), pytest.raises(ValueError, match="more than once"):
        pbr.presets_for(spec.code)


def test_a_mix_plays_its_own_games_hero_presets() -> None:
    assert pbr.mix_ban_preset("deadlock", "deadlock_hero_bans").id == "deadlock_hero_bans"
    assert pbr.mix_ban_preset("lol", "lol_side_selection").id == "lol_side_selection"
    assert pbr.mix_ban_preset("overwatch", "hero_classic").id == "hero_classic"


def test_a_mix_refuses_a_map_preset() -> None:
    assert pbr.mix_ban_preset("overwatch", "map_bracket") is None


def test_a_mix_plays_a_preset_whose_per_player_bans_only_start_on_map_two() -> None:
    """A mix round is map 1 of a Bo1: anti-one-trick's map-1 phase is a blind two-ban, its per-player phase never runs."""
    assert pbr.mix_ban_preset("overwatch", "hero_anti_one_trick").id == "hero_anti_one_trick"


def test_a_mix_refuses_a_preset_that_bans_a_player_on_map_one() -> None:
    per_player = pbr.Ruleset(phases=[ANTI.phases[1].model_copy(update={"when": {}})])
    presets = (
        pbr.Preset("per_player_always", "hero", ("pool",), per_player),
        pbr.Preset("per_player_later", "hero", ("pool",), ANTI),
    )
    spec = DisciplineSpec("targeting", "Targeting", (), pick_ban_presets=lambda: presets)
    with patch.dict(DISCIPLINES, {spec.code: spec}):
        assert pbr.mix_ban_preset(spec.code, "per_player_always") is None
        assert pbr.mix_ban_preset(spec.code, "per_player_later").id == "per_player_later"


def test_a_mix_refuses_another_games_preset_and_an_unknown_game() -> None:
    assert pbr.mix_ban_preset("overwatch", "deadlock_hero_bans") is None
    assert pbr.mix_ban_preset("not-a-game", "deadlock_hero_bans") is None


#: LoL's tournament draft after the side pick (spec §11.6 R4-7).
_LOL_ORDER = [
    *(("ban", side) for side in ("blue", "red", "blue", "red", "blue", "red")),
    *(("pick", side) for side in ("blue", "red", "red", "blue", "blue", "red")),
    *(("ban", side) for side in ("red", "blue", "red", "blue")),
    *(("pick", side) for side in ("red", "blue", "blue", "red")),
]


def test_the_mix_pick_presets_play_their_documented_orders() -> None:
    lol = {preset.id: preset for preset in pbr.presets_for("lol")}
    for code, member in (("lol_draft", "next"), ("lol_captains", None)):
        (phase,) = lol[code].ruleset.phases
        side, *draft = phase.steps
        assert (side.action, side.actors) == ("side_pick", "first")
        if code == "lol_captains":
            *draft, assign = draft
            assert (assign.action, assign.actors, assign.count) == ("assign", "both", 5)
        assert [(step.action, step.actors) for step in draft] == [(action, f"side:{s}") for action, s in _LOL_ORDER]
        assert {step.member for step in draft if step.action == "pick"} == {member}
    deadlock = {preset.id: preset for preset in pbr.presets_for("deadlock")}
    bans = [("ban", "first", None), ("ban", "second", None), ("ban", "first", None), ("ban", "second", None)]
    (phase,) = deadlock["deadlock_bans_pick"].ruleset.phases
    assert [(step.action, step.actors, step.member) for step in phase.steps] == [*bans, ("pick", "both", "each")]
    # Turn by turn: the same bans, then the snake A-BB-AA-BB-AA-B, each pick the next player's of its team.
    (phase,) = deadlock["deadlock_bans_pick_turns"].ruleset.phases
    snake = ["first", "second", "second", "first"] * 3
    assert [(step.action, step.actors, step.member) for step in phase.steps] == [
        *bans,
        *(("pick", actors, "next") for actors in snake),
    ]
    # In two halves: a ban each (A, B), the snake's first six picks, a ban each (B, A), its last six.
    (phase,) = deadlock["deadlock_two_phase_draft"].ruleset.phases
    assert [(step.action, step.actors, step.member) for step in phase.steps] == [
        ("ban", "first", None),
        ("ban", "second", None),
        *(("pick", actors, "next") for actors in snake[:6]),
        ("ban", "second", None),
        ("ban", "first", None),
        *(("pick", actors, "next") for actors in snake[6:]),
    ]
    assert not any(_mix_only(preset) for preset in pbr.presets_for("overwatch"))


def test_a_mix_plays_the_pick_presets_and_a_tournament_may_not() -> None:
    for discipline, code in (
        ("lol", "lol_draft"),
        ("lol", "lol_captains"),
        ("deadlock", "deadlock_bans_pick"),
        ("deadlock", "deadlock_bans_pick_turns"),
        ("deadlock", "deadlock_two_phase_draft"),
    ):
        preset = pbr.mix_ban_preset(discipline, code)
        assert preset is not None and preset.id == code
        issues = pbr.validate_ruleset(preset.ruleset.to_json(), kind="hero", mode="pool", discipline=discipline)
        assert "mix_only" in {issue.code for issue in issues if issue.severity == "error"}


# ── preview ─────────────────────────────────────────────────────────────────


def test_preview_counts_the_anti_one_trick_ban_pressure():
    preview = preview_series(ANTI, kind="hero", mode="pool", best_of=5, pool_groups=HERO_POOL)
    assert [row["map_index"] for row in preview["maps"]] == [1, 2, 3, 4, 5]
    assert [row["phase_id"] for row in preview["maps"]] == ["map1", "map2plus", "map2plus", "map2plus", "map2plus"]
    assert [row["max_new_bans"] for row in preview["maps"]] == [4, 10, 10, 10, 10]
    # Map 1's bans expire after their map; map N carries map N-1's ten.
    assert [row["max_active_bans"] for row in preview["maps"]] == [4, 10, 20, 20, 20]


def test_preview_reports_the_worst_case_per_role():
    preview = preview_series(ANTI, kind="hero", mode="pool", best_of=2, pool_groups=HERO_POOL)
    assert preview["maps"][0]["worst_case_remaining"] == {"tank": 9, "damage": 16, "support": 11}
    assert preview["maps"][1]["worst_case_remaining"] == {"tank": 3, "damage": 10, "support": 5}


def test_preview_warns_once_per_group_when_a_role_can_be_wiped_out():
    preview = preview_series(ANTI, kind="hero", mode="pool", best_of=5, pool_groups={"tank": 6, "damage": 30})
    codes = [(issue["code"], issue["severity"]) for issue in preview["issues"]]
    assert codes == [("group_nearly_exhausted", "warning")]
    assert "tank" in preview["issues"][0]["message"]


def test_a_max_per_group_cap_bounds_the_worst_case():
    ruleset = OVERWATCH["hero_role_bans"].ruleset
    preview = preview_series(ruleset, kind="hero", mode="pool", best_of=1, pool_groups=HERO_POOL)
    # 3 blind bans per side, but at most one per role each: 2 per role, not 6.
    assert preview["maps"][0]["worst_case_remaining"] == {"tank": 11, "damage": 18, "support": 13}


#: The 2026-10-03 roster shape: one tank, two damage, two support per team.
ROSTER = {"tank": 1, "damage": 2, "support": 2}
TOURNAMENT_POOL = {"tank": 13, "damage": 19, "support": 12}


def test_roster_slots_bound_a_per_player_ban_step():
    """Five bans per side, but one per opponent player and each matching that
    player's role: a role absorbs at most as many bans as the team fields."""
    preview = preview_series(
        ANTI, kind="hero", mode="pool", best_of=5, pool_groups=TOURNAMENT_POOL, roster_slots=ROSTER
    )
    assert preview["maps"][2]["worst_case_remaining"] == {"tank": 9, "damage": 11, "support": 4}
    assert [row["max_active_bans"] for row in preview["maps"]] == [4, 10, 20, 20, 20]
    assert preview["issues"] == []


def test_without_roster_slots_the_worst_case_stays_pessimistic():
    preview = preview_series(ANTI, kind="hero", best_of=5, pool_groups=TOURNAMENT_POOL)
    assert preview["maps"][2]["worst_case_remaining"] == {"tank": 0, "damage": 0, "support": 0}
    assert [issue["code"] for issue in preview["issues"]] == ["group_nearly_exhausted"] * 3


def test_roster_slots_only_bound_a_role_matched_one_per_target_step():
    """Map 1 bans any hero from anyone: the roster says nothing about it."""
    preview = preview_series(ANTI, kind="hero", best_of=1, pool_groups=TOURNAMENT_POOL, roster_slots=ROSTER)
    # 2 blind bans per side, all four of which could be tanks.
    assert preview["maps"][0]["worst_case_remaining"]["tank"] == 9


def test_flex_players_widen_every_roles_ceiling():
    preview = preview_series(
        ANTI,
        kind="hero",
        best_of=3,
        pool_groups=TOURNAMENT_POOL,
        roster_slots={"tank": 1, "damage": 2, "support": 1, "flex": 1},
    )
    # The flex player can be banned any hero, so the tank ceiling is 1 + 1 per
    # side across the two active maps: 13 - (2 + 2) * 2 = 5.
    assert preview["maps"][2]["worst_case_remaining"]["tank"] == 5


def test_roster_keys_are_case_insensitive_and_extra_roles_are_ignored():
    lenient = preview_series(
        ANTI,
        kind="hero",
        best_of=5,
        pool_groups=TOURNAMENT_POOL,
        roster_slots={"Tank": 1, "DAMAGE": 2, "support": 2, "coach": 3, "bench": 0},
    )
    strict = preview_series(ANTI, kind="hero", best_of=5, pool_groups=TOURNAMENT_POOL, roster_slots=ROSTER)
    assert lenient["maps"] == strict["maps"]


def test_preview_resolves_a_generated_map_series():
    preview = preview_series(
        pbr.GENERIC_PRESETS_BY_ID["map_bracket"].ruleset,
        kind="map",
        mode="pool",
        best_of=3,
        pool_groups={"control": 7},
    )
    (row,) = preview["maps"]
    assert [step["action"] for step in row["steps"]] == ["ban", "ban", "pick", "pick", "decider"]
    assert row["worst_case_remaining"] is None


def test_the_pool_size_is_its_own_input_not_the_sum_of_the_groups():
    # A game whose maps have no gamemode has no groups: seven ungrouped maps are still a seven-map pool.
    ruleset = pbr.GENERIC_PRESETS_BY_ID["map_bracket"].ruleset
    sized = preview_series(ruleset, kind="map", mode="pool", best_of=3, pool_groups={}, pool_size=7)
    unsized = preview_series(ruleset, kind="map", mode="pool", best_of=3, pool_groups={})
    actions = [step["action"] for step in sized["maps"][0]["steps"]]
    assert actions == ["ban", "ban", "pick", "pick", "decider"]
    assert sized["maps"][0]["steps"] != unsized["maps"][0]["steps"]


def test_preview_refuses_to_guess_at_a_broken_ruleset():
    preview = preview_series({"version": 2, "phases": []}, kind="hero", best_of=3)
    assert preview["maps"] == []
    assert [issue["code"] for issue in preview["issues"]] == ["phases_empty"]


def test_preview_reports_a_map_no_phase_covers():
    ruleset = pbr.parse_ruleset(
        {
            "version": 2,
            "phases": [
                {
                    "id": "only1",
                    "when": {"type": "map_index", "params": {"op": "==", "value": 1}},
                    "steps": [{"id": "b", "action": "ban", "actors": "both", "count": 1}],
                }
            ],
        }
    )
    preview = preview_series(ruleset, kind="hero", best_of=3, pool_groups=HERO_POOL)
    assert [row["phase_id"] for row in preview["maps"]] == ["only1", None, None]
    assert [row["steps"] for row in preview["maps"][1:]] == [[], []]


@pytest.mark.parametrize("best_of", [1, 2, 3, 5])
def test_preview_covers_every_supported_series_length(best_of):
    preview = preview_series(ANTI, kind="hero", best_of=best_of, pool_groups=HERO_POOL)
    assert len(preview["maps"]) == best_of
