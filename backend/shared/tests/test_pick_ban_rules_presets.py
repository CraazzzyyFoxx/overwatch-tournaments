"""Presets, catalog and series preview.

A preset that does not validate is a broken button in the constructor, and the
preview numbers are what an organizer reads before committing to a format.
"""

import pytest

from shared.domain import pick_ban_rules as pbr

ANTI = pbr.PRESETS_BY_ID["hero_anti_one_trick"].ruleset
HERO_POOL = {"tank": 13, "damage": 20, "support": 15}


def test_every_preset_validates_clean_for_its_kind_and_modes():
    for preset in pbr.PRESETS:
        for mode in preset.modes:
            issues = pbr.validate_ruleset(preset.ruleset.to_json(), kind=preset.kind, mode=mode)
            assert [issue.to_json() for issue in issues if issue.severity == "error"] == []


def test_the_seven_presets_are_the_documented_ones():
    assert [preset.id for preset in pbr.PRESETS] == [
        "hero_classic",
        "hero_protect_ban",
        "hero_blind_2",
        "hero_role_bans",
        "hero_anti_one_trick",
        "map_bracket",
        "map_slot_veto",
    ]


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
    (phase,) = pbr.PRESETS_BY_ID["hero_role_bans"].ruleset.phases
    (step,) = phase.steps
    assert step.count == 3
    assert [constraint.to_json() for constraint in step.constraints] == [
        {"type": "max_per_group", "params": {"max": 1, "scope": "step", "group": None}}
    ]


def test_hero_protect_ban_runs_protects_before_bans():
    (phase,) = pbr.PRESETS_BY_ID["hero_protect_ban"].ruleset.phases
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
    payload = pbr.catalog({"hero": ["tank", "damage", "support"], "map": ["control", "hybrid"]})
    assert payload["groups"] == {"hero": ["tank", "damage", "support"], "map": ["control", "hybrid"]}
    assert [preset["id"] for preset in payload["presets"]] == [preset.id for preset in pbr.PRESETS]

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


def test_catalog_falls_back_to_the_hero_class_vocabulary():
    assert pbr.catalog()["groups"] == {"hero": list(pbr.HERO_GROUPS), "map": []}


# ── preview ─────────────────────────────────────────────────────────────────


def test_preview_counts_the_anti_one_trick_ban_pressure():
    preview = pbr.preview_series(ANTI, kind="hero", mode="pool", best_of=5, pool_groups=HERO_POOL)
    assert [row["map_index"] for row in preview["maps"]] == [1, 2, 3, 4, 5]
    assert [row["phase_id"] for row in preview["maps"]] == ["map1", "map2plus", "map2plus", "map2plus", "map2plus"]
    assert [row["max_new_bans"] for row in preview["maps"]] == [4, 10, 10, 10, 10]
    # Map 1's bans expire after their map; map N carries map N-1's ten.
    assert [row["max_active_bans"] for row in preview["maps"]] == [4, 10, 20, 20, 20]


def test_preview_reports_the_worst_case_per_role():
    preview = pbr.preview_series(ANTI, kind="hero", mode="pool", best_of=2, pool_groups=HERO_POOL)
    assert preview["maps"][0]["worst_case_remaining"] == {"tank": 9, "damage": 16, "support": 11}
    assert preview["maps"][1]["worst_case_remaining"] == {"tank": 3, "damage": 10, "support": 5}


def test_preview_warns_once_per_group_when_a_role_can_be_wiped_out():
    preview = pbr.preview_series(ANTI, kind="hero", mode="pool", best_of=5, pool_groups={"tank": 6, "damage": 30})
    codes = [(issue["code"], issue["severity"]) for issue in preview["issues"]]
    assert codes == [("group_nearly_exhausted", "warning")]
    assert "tank" in preview["issues"][0]["message"]


def test_a_max_per_group_cap_bounds_the_worst_case():
    ruleset = pbr.PRESETS_BY_ID["hero_role_bans"].ruleset
    preview = pbr.preview_series(ruleset, kind="hero", mode="pool", best_of=1, pool_groups=HERO_POOL)
    # 3 blind bans per side, but at most one per role each: 2 per role, not 6.
    assert preview["maps"][0]["worst_case_remaining"] == {"tank": 11, "damage": 18, "support": 13}


#: The 2026-10-03 roster shape: one tank, two damage, two support per team.
ROSTER = {"tank": 1, "damage": 2, "support": 2}
TOURNAMENT_POOL = {"tank": 13, "damage": 19, "support": 12}


def test_roster_slots_bound_a_per_player_ban_step():
    """Five bans per side, but one per opponent player and each matching that
    player's role: a role absorbs at most as many bans as the team fields."""
    preview = pbr.preview_series(
        ANTI, kind="hero", mode="pool", best_of=5, pool_groups=TOURNAMENT_POOL, roster_slots=ROSTER
    )
    assert preview["maps"][2]["worst_case_remaining"] == {"tank": 9, "damage": 11, "support": 4}
    assert [row["max_active_bans"] for row in preview["maps"]] == [4, 10, 20, 20, 20]
    assert preview["issues"] == []


def test_without_roster_slots_the_worst_case_stays_pessimistic():
    preview = pbr.preview_series(ANTI, kind="hero", best_of=5, pool_groups=TOURNAMENT_POOL)
    assert preview["maps"][2]["worst_case_remaining"] == {"tank": 0, "damage": 0, "support": 0}
    assert [issue["code"] for issue in preview["issues"]] == ["group_nearly_exhausted"] * 3


def test_roster_slots_only_bound_a_role_matched_one_per_target_step():
    """Map 1 bans any hero from anyone: the roster says nothing about it."""
    preview = pbr.preview_series(ANTI, kind="hero", best_of=1, pool_groups=TOURNAMENT_POOL, roster_slots=ROSTER)
    # 2 blind bans per side, all four of which could be tanks.
    assert preview["maps"][0]["worst_case_remaining"]["tank"] == 9


def test_flex_players_widen_every_roles_ceiling():
    preview = pbr.preview_series(
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
    lenient = pbr.preview_series(
        ANTI,
        kind="hero",
        best_of=5,
        pool_groups=TOURNAMENT_POOL,
        roster_slots={"Tank": 1, "DAMAGE": 2, "support": 2, "coach": 3, "bench": 0},
    )
    strict = pbr.preview_series(ANTI, kind="hero", best_of=5, pool_groups=TOURNAMENT_POOL, roster_slots=ROSTER)
    assert lenient["maps"] == strict["maps"]


def test_preview_resolves_a_generated_map_series():
    preview = pbr.preview_series(
        pbr.PRESETS_BY_ID["map_bracket"].ruleset, kind="map", mode="pool", best_of=3, pool_groups={"control": 7}
    )
    (row,) = preview["maps"]
    assert [step["action"] for step in row["steps"]] == ["ban", "ban", "pick", "pick", "decider"]
    assert row["worst_case_remaining"] is None


def test_preview_refuses_to_guess_at_a_broken_ruleset():
    preview = pbr.preview_series({"version": 2, "phases": []}, kind="hero", best_of=3)
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
    preview = pbr.preview_series(ruleset, kind="hero", best_of=3, pool_groups=HERO_POOL)
    assert [row["phase_id"] for row in preview["maps"]] == ["only1", None, None]
    assert [row["steps"] for row in preview["maps"][1:]] == [[], []]


@pytest.mark.parametrize("best_of", [1, 2, 3, 5])
def test_preview_covers_every_supported_series_length(best_of):
    preview = pbr.preview_series(ANTI, kind="hero", best_of=best_of, pool_groups=HERO_POOL)
    assert len(preview["maps"]) == best_of
