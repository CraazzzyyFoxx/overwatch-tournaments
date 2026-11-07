"""Runtime semantics: cursor, blind privacy, projection, eligibility,
constraints, carried bans, random fill, undo and dispute.

Everything here is what the 2026-10-03 tournament runs on, so the fixtures are
its rules: a hero pool with roles, a 5-player roster per side, blind bans.
"""

from random import Random
from types import SimpleNamespace

import pytest

from shared.domain import pick_ban_rules as pbr

# ── fixtures ────────────────────────────────────────────────────────────────

TANKS = [1, 2, 3, 4, 5]
DAMAGE = [10, 11, 12, 13, 14, 15]
SUPPORT = [20, 21, 22, 23, 24]
GROUPS = dict.fromkeys(TANKS, "tank") | dict.fromkeys(DAMAGE, "damage") | dict.fromkeys(SUPPORT, "support")
ALL_ITEMS = tuple(GROUPS)

#: One 5-stack per side: the players the OTHER side bans for.
HOME_PLAYERS = (
    pbr.TargetPlayer(101, "tank"),
    pbr.TargetPlayer(102, "damage"),
    pbr.TargetPlayer(103, "damage"),
    pbr.TargetPlayer(104, "support"),
    pbr.TargetPlayer(105, "support"),
)
AWAY_PLAYERS = (
    pbr.TargetPlayer(201, "tank"),
    pbr.TargetPlayer(202, "damage"),
    pbr.TargetPlayer(203, "damage"),
    pbr.TargetPlayer(204, "support"),
    pbr.TargetPlayer(205, "support"),
)
#: Participation ids: the resolved actor vocabulary (§13.4). Slot 1 and slot 2.
HOME, AWAY = 1001, 1002
#: `targets[actor]` are the players `actor` may name — the opponent's roster.
TARGETS = {HOME: AWAY_PLAYERS, AWAY: HOME_PLAYERS}

ANTI = {preset.id: preset for preset in pbr.presets_for("overwatch")}["hero_anti_one_trick"].ruleset


def submission(step_index, actor, items, *, state="revealed", attempt=1):
    return SimpleNamespace(
        step_index=step_index,
        encounter_team_id=actor,
        team_member_id=None,
        attempt=attempt,
        state=state,
        items_json=[
            {"item_id": item, "target_player_id": None}
            if isinstance(item, int)
            else {"item_id": item[0], "target_player_id": item[1]}
            for item in items
        ],
        locked_at=None,
        revealed_at=None,
    )


def entry(item_id, *, round=None, carried=None):
    return SimpleNamespace(
        item_id=item_id,
        round=round,
        order=0,
        action_index=None,
        picked_by_kind=None,
        picked_by_team_id=None,
        picked_for_member_id=None,
        protected_by_kind=None,
        protected_by_team_id=None,
        status="available",
        carried_from_round=carried,
    )


def ctx(*, round=1, available=ALL_ITEMS, steps=(), submissions=(), **overrides):
    payload = {
        "kind": "hero",
        "round": round,
        "best_of": 5,
        "available_item_ids": tuple(available),
        "groups": GROUPS,
        "history": pbr.history_of(list(steps), list(submissions)),
        "targets": TARGETS,
    }
    payload.update(overrides)
    return pbr.RuntimeCtx(**payload)


def anti_round(round_number, start_index, opener=HOME):
    return pbr.resolve_round(
        ANTI,
        kind="hero",
        round=round_number,
        start_index=start_index,
        participants=(HOME, AWAY),
        opener=opener,
        best_of=5,
    )


def open_steps(*actions_and_actors, round=1):
    """Resolved open (non-blind) single-item steps, for cursor/undo tests."""
    return [
        pbr.ResolvedStep(
            index=index,
            round=round,
            phase_id="main",
            step_id=f"s{index}",
            action=action,
            actors=list(actors),
            count=count,
            min=count,
            blind=False,
            target=None,
            lifetime=1 if action == "ban" else None,
            timer_seconds=None,
            on_timeout="wait",
            dispute=pbr.DisputeRule(enabled=False, max=0),
            eligible={},
            constraints=[],
        )
        for index, (action, actors, count) in enumerate(actions_and_actors)
    ]


# ── cursor ──────────────────────────────────────────────────────────────────


def test_cursor_stays_on_an_open_step_until_its_count_is_revealed():
    steps = open_steps(("ban", [HOME], 2), ("ban", [AWAY], 1))
    assert pbr.current_step(steps, []).index == 0

    drafting = [submission(0, HOME, [1], state="draft")]
    assert pbr.current_step(steps, drafting).index == 0

    revealed = [submission(0, HOME, [1, 2], state="revealed")]
    assert pbr.current_step(steps, revealed).index == 1


def test_cursor_waits_for_every_side_of_a_blind_step():
    (step,) = anti_round(1, 0)
    assert step.actors == [HOME, AWAY]
    locked_one = [submission(0, HOME, [1, 2], state="locked")]
    assert pbr.current_step([step], locked_one).index == 0
    both = [submission(0, HOME, [1, 2]), submission(0, AWAY, [3, 4])]
    assert pbr.current_step([step], both) is None


def test_cursor_ignores_voided_submissions():
    steps = open_steps(("ban", [HOME], 1))
    rows = [submission(0, HOME, [1], state="voided", attempt=2)]
    assert pbr.current_step(steps, rows).index == 0


def test_current_attempt_tracks_the_highest_attempt():
    rows = [submission(0, HOME, [1], state="voided"), submission(0, HOME, [2], attempt=2, state="draft")]
    assert pbr.current_attempt(rows, 0) == 2
    assert pbr.actor_submission(rows, 0, HOME).items_json == [{"item_id": 2, "target_player_id": None}]


# ── blind privacy ───────────────────────────────────────────────────────────


def test_blind_drafts_are_never_serialized_to_the_opponent():
    (step,) = anti_round(1, 0)
    rows = [submission(0, HOME, [1, 2], state="locked"), submission(0, AWAY, [3], state="draft")]

    away_view = pbr.visible_submissions([step], rows, AWAY)
    assert [row.encounter_team_id for row in away_view] == [AWAY]

    home_view = pbr.visible_submissions([step], rows, HOME)
    assert [row.encounter_team_id for row in home_view] == [HOME]

    spectator = pbr.visible_submissions([step], rows, None)
    assert spectator == []


def test_an_open_step_is_public_immediately():
    steps = open_steps(("ban", [HOME], 2))
    rows = [submission(0, HOME, [1], state="draft")]
    assert [row.encounter_team_id for row in pbr.visible_submissions(steps, rows, AWAY)] == [HOME]


def test_revealed_blind_submissions_are_visible_to_everyone():
    (step,) = anti_round(1, 0)
    rows = [submission(0, HOME, [1, 2]), submission(0, AWAY, [3, 4])]
    assert len(pbr.visible_submissions([step], rows, None)) == 2


def test_step_progress_reports_a_hidden_drafts_size():
    (step,) = anti_round(1, 0)
    rows = [submission(0, HOME, [1, 2], state="locked"), submission(0, AWAY, [3], state="draft")]
    assert pbr.step_progress(step, rows) == {
        HOME: {"locked": True, "filled": 2},
        AWAY: {"locked": False, "filled": 1},
    }


def test_ready_to_reveal_needs_every_side_locked():
    (step,) = anti_round(1, 0)
    assert not pbr.ready_to_reveal(step, [submission(0, HOME, [1, 2], state="locked")])
    assert pbr.ready_to_reveal(
        step, [submission(0, HOME, [1, 2], state="locked"), submission(0, AWAY, [3, 4], state="locked")]
    )


# ── projection ──────────────────────────────────────────────────────────────


def test_blind_duplicate_bans_merge_into_one_banned_entry():
    (step,) = anti_round(1, 0)
    rows = [submission(0, HOME, [1, 2]), submission(0, AWAY, [2, 3])]
    entries = [entry(item, round=1) for item in (1, 2, 3, 4)]
    pbr.project_entries(entries, [step], rows)

    banned = [item.item_id for item in entries if item.status == "banned"]
    assert banned == [1, 2, 3]
    # The overlap belongs to the side that applied it first, and consumed one
    # action index — the other submission still lists it.
    by_id = {item.item_id: item for item in entries}
    assert by_id[2].picked_by_team_id == HOME
    assert [by_id[item].action_index for item in (1, 2, 3)] == [0, 1, 2]
    assert by_id[4].status == "available"


def test_projection_orders_picks_and_is_idempotent():
    steps = open_steps(("ban", [HOME], 1), ("pick", [AWAY], 1), ("pick", [HOME], 1), ("decider", [None], 1))
    rows = [
        submission(0, HOME, [1]),
        submission(1, AWAY, [2]),
        submission(2, HOME, [3]),
        submission(3, None, [4]),
    ]
    entries = [entry(item, round=1) for item in (1, 2, 3, 4, 5)]
    pbr.project_entries(entries, steps, rows)
    by_id = {item.item_id: item for item in entries}

    assert by_id[1].status == "banned"
    assert [by_id[item].status for item in (2, 3, 4)] == ["picked", "picked", "picked"]
    assert [by_id[item].order for item in (2, 3, 4)] == [1, 2, 3]
    assert by_id[4].picked_by_kind == "decider"
    assert [by_id[item].action_index for item in (1, 2, 3, 4)] == [0, 1, 2, 3]
    assert by_id[5].status == "available"

    before = [(item.status, item.order, item.action_index, item.picked_by_team_id) for item in entries]
    pbr.project_entries(entries, steps, rows)
    assert [(item.status, item.order, item.action_index, item.picked_by_team_id) for item in entries] == before


def test_projection_resets_what_a_void_took_back():
    steps = open_steps(("ban", [HOME], 1))
    entries = [entry(1, round=1)]
    pbr.project_entries(entries, steps, [submission(0, HOME, [1])])
    assert entries[0].status == "banned"

    pbr.project_entries(entries, steps, [submission(0, HOME, [1], state="voided")])
    assert (entries[0].status, entries[0].picked_by_team_id, entries[0].action_index) == ("available", None, None)


def test_projection_never_touches_a_carried_entry():
    steps = open_steps(("ban", [HOME], 1))
    carried = entry(9, round=2, carried=1)
    carried.status = "banned"
    carried.picked_by_kind, carried.picked_by_team_id = "team", AWAY
    entries = [carried, entry(1, round=2)]
    pbr.project_entries(entries, steps, [])
    assert (carried.status, carried.picked_by_team_id, carried.carried_from_round) == ("banned", AWAY, 1)


def test_a_protected_item_cannot_be_banned():
    steps = open_steps(("protect", [HOME], 1), ("ban", [AWAY], 1))
    entries = [entry(1, round=1)]
    pbr.project_entries(entries, steps, [submission(0, HOME, [1]), submission(1, AWAY, [1])])
    assert entries[0].status == "protected"
    assert entries[0].protected_by_team_id == HOME


# ── carried bans over the anti-one-trick series ─────────────────────────────


def anti_series(rounds):
    """Resolve ``rounds`` maps of the tournament preset and reveal every ban:
    2+2 on map 1, then 5+5 per map, all distinct items."""
    steps: list[pbr.ResolvedStep] = []
    rows = []
    next_item = iter(range(1000, 1200))
    for round_number in range(1, rounds + 1):
        (step,) = anti_round(round_number, len(steps))
        steps.append(step)
        for side in step.actors:
            rows.append(submission(step.index, side, [next(next_item) for _ in range(step.count)]))
    return steps, rows


@pytest.mark.parametrize(
    ("round_number", "carried", "active"),
    [(1, 0, 4), (2, 0, 10), (3, 10, 20), (4, 10, 20), (5, 10, 20)],
)
def test_carried_bans_follow_the_lifetime_math(round_number, carried, active):
    steps, rows = anti_series(round_number)
    carried_now = pbr.carried_bans(steps, rows, round_number)
    new_now = sum(step.count * len(step.actors) for step in steps if step.round == round_number)
    assert len(carried_now) == carried
    assert len(carried_now) + new_now == active


def test_carried_bans_keep_their_origin_round_and_side():
    steps, rows = anti_series(3)
    carried = pbr.carried_bans(steps, rows, 3)
    assert {ban.from_round for ban in carried} == {2}
    assert {ban.actor for ban in carried} == {HOME, AWAY}


def test_a_duplicate_carried_ban_is_kept_once():
    steps = [anti_round(1, 0)[0], anti_round(2, 1)[0]]
    rows = [
        submission(1, HOME, [(1, 201), (10, 202), (11, 203), (20, 204), (21, 205)]),
        submission(1, AWAY, [(1, 101), (12, 102), (13, 103), (22, 104), (23, 105)]),
    ]
    carried = pbr.carried_bans(steps, rows, 3)
    assert len(carried) == 9
    assert [ban.actor for ban in carried if ban.item_id == 1] == [HOME]


# ── eligibility and targets ─────────────────────────────────────────────────


def test_target_role_match_answers_per_opponent_player():
    (step,) = anti_round(2, 0)
    eligible = pbr.eligible_items(step, HOME, ctx(round=2))
    assert eligible.by_target is not None
    assert set(eligible.by_target[201]) == set(TANKS)  # away's tank
    assert set(eligible.by_target[202]) == set(DAMAGE)
    assert set(eligible.item_ids) == set(ALL_ITEMS)


def test_a_role_less_player_can_be_banned_anything():
    (step,) = anti_round(2, 0)
    flex = {HOME: (pbr.TargetPlayer(201, None),), AWAY: HOME_PLAYERS}
    eligible = pbr.eligible_items(step, HOME, ctx(round=2, targets=flex))
    assert set(eligible.by_target[201]) == set(ALL_ITEMS)


def test_banned_by_self_excludes_a_sides_own_earlier_bans():
    steps = open_steps(("ban", [HOME], 1), ("ban", [HOME], 1), round=None)
    steps[1] = steps[1].model_copy(
        update={"eligible": {"NOT": {"type": "banned_by", "params": {"by": "self", "scope": "series"}}}}
    )
    rows = [submission(0, HOME, [1])]
    eligible = pbr.eligible_items(steps[1], HOME, ctx(round=None, steps=steps, submissions=rows))
    assert 1 not in eligible.item_ids
    # The opponent is still free to target it.
    assert 1 in pbr.eligible_items(steps[1], AWAY, ctx(round=None, steps=steps, submissions=rows)).item_ids


def test_pool_filter_drops_candidates_banned_anywhere_in_the_series():
    """The v1 `no_repeat_scope=encounter` rule, as a pool filter."""
    steps = open_steps(("ban", [HOME], 1))
    rows = [submission(0, HOME, [1])]
    pool_filter = {"NOT": {"type": "banned_by", "params": {"by": "any", "scope": "series"}}}
    context = ctx(round=2, steps=steps, submissions=rows)
    assert pbr.filter_pool(pool_filter, [1, 2, 3], context) == [2, 3]
    assert pbr.filter_pool({}, [1, 2, 3], context) == [1, 2, 3]


def test_pool_filter_drops_every_map_of_a_mode_the_series_already_played():
    """Map 1 is the veto's survivor (a decider), map 2 the loser's pick: both their modes are done, while a mode
    that was only banned stays open."""
    groups = {1: "control", 2: "control", 3: "escort", 4: "hybrid", 5: "hybrid", 6: "push"}
    # Rounds do not matter to a series-scoped leaf; one round keeps the step indexes contiguous.
    steps = open_steps(("ban", [HOME], 1), ("decider", [None], 1), ("pick", [AWAY], 1))
    rows = [submission(0, HOME, [3]), submission(1, None, [1]), submission(2, AWAY, [4])]
    pool_filter = {"NOT": {"type": "group_picked_by", "params": {"by": "any", "scope": "series"}}}
    context = ctx(round=3, steps=steps, submissions=rows, kind="map", groups=groups)
    assert pbr.filter_pool(pool_filter, [2, 3, 5, 6], context) == [3, 6]


def test_a_step_never_sees_its_own_submissions():
    """Otherwise a blind step's two sides would leak into each other's
    eligibility the moment one of them locked."""
    (step,) = anti_round(1, 0)
    step = step.model_copy(
        update={"eligible": {"NOT": {"type": "banned_by", "params": {"by": "any", "scope": "series"}}}}
    )
    rows = [submission(0, HOME, [1, 2], state="locked")]
    assert 1 in pbr.eligible_items(step, AWAY, ctx(steps=[step], submissions=rows)).item_ids


# ── submission validation ───────────────────────────────────────────────────


def test_a_valid_per_player_ban_draft_passes():
    (step,) = anti_round(2, 0)
    items = [
        {"item_id": 1, "target_player_id": 201},
        {"item_id": 10, "target_player_id": 202},
        {"item_id": 11, "target_player_id": 203},
        {"item_id": 20, "target_player_id": 204},
        {"item_id": 21, "target_player_id": 205},
    ]
    assert pbr.validate_items(step, HOME, items, ctx(round=2), final=True) == []


def test_two_bans_on_one_player_are_rejected():
    (step,) = anti_round(2, 0)
    # Mauga and Zarya are both tanks, and both are aimed at the one tank.
    items = [{"item_id": 1, "target_player_id": 201}, {"item_id": 2, "target_player_id": 201}]
    assert "one_per_target" in pbr.validate_items(step, HOME, items, ctx(round=2))


def test_a_ban_must_match_the_targets_role():
    (step,) = anti_round(2, 0)
    items = [{"item_id": 20, "target_player_id": 201}]  # a support hero on the tank
    assert "item_not_eligible" in pbr.validate_items(step, HOME, items, ctx(round=2))


def test_a_target_step_needs_a_target_and_only_known_players():
    (step,) = anti_round(2, 0)
    assert "target_required" in pbr.validate_items(step, HOME, [{"item_id": 1}], ctx(round=2))
    assert "target_unknown" in pbr.validate_items(step, HOME, [{"item_id": 1, "target_player_id": 101}], ctx(round=2))


def test_targets_are_refused_on_a_step_without_one():
    (step,) = anti_round(1, 0)
    issues = pbr.validate_items(step, HOME, [{"item_id": 1, "target_player_id": 201}], ctx())
    assert "target_not_allowed" in issues


def test_duplicates_over_count_and_unavailable_items_are_rejected():
    (step,) = anti_round(1, 0)
    assert "duplicate_item" in pbr.validate_items(step, HOME, [{"item_id": 1}, {"item_id": 1}], ctx())
    assert "too_many_items" in pbr.validate_items(step, HOME, [{"item_id": 1}, {"item_id": 2}, {"item_id": 3}], ctx())
    assert "item_not_available" in pbr.validate_items(step, HOME, [{"item_id": 999}], ctx())


def test_locking_short_of_min_is_only_an_issue_when_final():
    (step,) = anti_round(1, 0)
    items = [{"item_id": 1}]
    assert pbr.validate_items(step, HOME, items, ctx()) == []
    assert pbr.validate_items(step, HOME, items, ctx(), final=True) == ["not_enough_items"]


def test_max_per_group_scope_round_reproduces_the_v1_unique_role_rule():
    """v1 `unique_attribute_per_side_per_round=role`: one ban per role per side
    per round, counted across the round's steps."""
    steps = open_steps(("ban", [HOME], 1), ("ban", [HOME], 1))
    unique_role = pbr.Constraint(type="max_per_group", params={"max": 1, "scope": "round", "group": None})
    steps = [step.model_copy(update={"constraints": [unique_role]}) for step in steps]
    rows = [submission(0, HOME, [1])]  # a tank, already banned this round
    context = ctx(steps=steps, submissions=rows)

    assert "max_per_group" in pbr.validate_items(steps[1], HOME, [{"item_id": 2}], context)
    assert pbr.validate_items(steps[1], HOME, [{"item_id": 10}], context) == []
    # The other side has its own budget.
    assert pbr.validate_items(steps[1], AWAY, [{"item_id": 2}], context) == []


def test_max_per_group_scope_step_counts_only_the_current_draft():
    step = open_steps(("ban", [HOME], 3))[0].model_copy(
        update={
            "constraints": [pbr.Constraint(type="max_per_group", params={"max": 1, "scope": "step", "group": None})]
        }
    )
    assert "max_per_group" in pbr.validate_items(step, HOME, [{"item_id": 1}, {"item_id": 2}], ctx())
    assert pbr.validate_items(step, HOME, [{"item_id": 1}, {"item_id": 10}, {"item_id": 20}], ctx()) == []


def test_min_per_group_is_checked_on_lock_only():
    step = open_steps(("ban", [HOME], 2))[0].model_copy(
        update={"constraints": [pbr.Constraint(type="min_per_group", params={"min": 1, "group": "support"})]}
    )
    items = [{"item_id": 1}, {"item_id": 2}]
    assert pbr.validate_items(step, HOME, items, ctx()) == []
    assert "min_per_group" in pbr.validate_items(step, HOME, items, ctx(), final=True)


# ── effective min ───────────────────────────────────────────────────────────


def test_effective_min_is_capped_by_what_is_left():
    (step,) = anti_round(1, 0)
    assert pbr.effective_min(step, HOME, ctx()) == 2
    assert pbr.effective_min(step, HOME, ctx(available=[1])) == 1
    assert pbr.effective_min(step, HOME, ctx(available=[])) == 0


def test_effective_min_uses_a_target_matching_when_one_per_target_applies():
    (step,) = anti_round(2, 0)
    # Only two tanks left: the tank target can take one of them, and nobody
    # else can take any -- so at most one of the five bans is possible.
    assert pbr.effective_min(step, HOME, ctx(round=2, available=[1, 2])) == 1
    assert pbr.effective_min(step, HOME, ctx(round=2, available=[1, 10, 11])) == 3
    assert pbr.effective_min(step, HOME, ctx(round=2)) == 5


# ── random fill and system steps ────────────────────────────────────────────


def test_random_fill_completes_a_per_player_draft_without_breaking_a_rule():
    (step,) = anti_round(2, 0)
    for seed in range(20):
        items = pbr.random_fill(step, HOME, [], ctx(round=2), Random(seed))
        assert len(items) == 5
        assert pbr.validate_items(step, HOME, items, ctx(round=2), final=True) == []


def test_random_fill_keeps_an_existing_draft_and_never_repeats_an_item():
    (step,) = anti_round(2, 0)
    started = [{"item_id": 1, "target_player_id": 201}]
    items = pbr.random_fill(step, HOME, started, ctx(round=2), Random(7))
    assert items[0] == started[0]
    assert len({item["item_id"] for item in items}) == 5


def test_random_fill_stops_when_a_constraint_leaves_nothing_to_add():
    step = open_steps(("ban", [HOME], 5))[0].model_copy(
        update={
            "constraints": [pbr.Constraint(type="max_per_group", params={"max": 1, "scope": "step", "group": None})]
        }
    )
    items = pbr.random_fill(step, HOME, [], ctx(), Random(1))
    assert len(items) == 3  # one per role, and no fourth role exists
    assert pbr.validate_items(step, HOME, items, ctx()) == []


def test_random_fill_respects_eligibility():
    step = open_steps(("ban", [HOME], 3))[0].model_copy(
        update={"eligible": {"type": "item_group", "params": {"groups": ["support"]}}}
    )
    items = pbr.random_fill(step, HOME, [], ctx(), Random(3))
    assert {item["item_id"] for item in items} <= set(SUPPORT)


def test_a_decider_settles_one_available_item():
    step = open_steps(("decider", [None], 1))[0]
    items = pbr.resolve_system_step(step, ctx(available=[7, 8]), Random(0))
    assert len(items) == 1
    assert items[0]["item_id"] in (7, 8)


def test_a_decider_with_nothing_left_submits_nothing():
    step = open_steps(("decider", [None], 1))[0]
    assert pbr.resolve_system_step(step, ctx(available=[]), Random(0)) == []


def test_a_system_ban_random_fills_its_count():
    step = open_steps(("ban", [None], 2))[0]
    items = pbr.resolve_system_step(step, ctx(), Random(5))
    assert len(items) == 2


# ── undo and dispute ────────────────────────────────────────────────────────


def test_undo_targets_the_latest_captain_step_not_the_system_one_behind_it():
    steps = open_steps(("ban", [HOME], 1), ("pick", [AWAY], 1), ("decider", [None], 1))
    rows = [submission(0, HOME, [1]), submission(1, AWAY, [2]), submission(2, "system", [3])]
    assert pbr.undo_target(steps, rows) == 1


def test_undo_has_no_target_before_anything_was_applied():
    steps = open_steps(("ban", [HOME], 1))
    assert pbr.undo_target(steps, []) is None
    assert pbr.undo_target(steps, [submission(0, HOME, [], state="draft")]) is None


def test_dispute_is_available_to_a_captain_of_the_latest_revealed_blind_step():
    (step,) = anti_round(1, 0)
    rows = [submission(0, HOME, [1, 2]), submission(0, AWAY, [3, 4])]
    state = pbr.dispute_target([step], rows, actor=HOME)
    assert (state.available, state.step_index, state.attempts_used, state.max) == (True, 0, 0, 1)


def test_dispute_runs_out_of_attempts():
    (step,) = anti_round(1, 0)
    rows = [
        submission(0, HOME, [1, 2], state="voided"),
        submission(0, AWAY, [3, 4], state="voided"),
        submission(0, HOME, [1, 2], attempt=2),
        submission(0, AWAY, [3, 5], attempt=2),
    ]
    state = pbr.dispute_target([step], rows, actor=HOME)
    assert state.available is False
    assert state.attempts_used == 1


def test_dispute_closes_once_a_later_step_started():
    steps = [anti_round(1, 0)[0], *open_steps(("ban", [HOME], 1))]
    steps[1] = steps[1].model_copy(update={"index": 1})
    rows = [
        submission(0, HOME, [1, 2]),
        submission(0, AWAY, [3, 4]),
        submission(1, HOME, [5], state="draft"),
    ]
    assert pbr.dispute_target(steps, rows, actor=HOME).available is False


def test_dispute_is_closed_for_an_open_step_and_for_a_reported_round():
    steps = open_steps(("ban", [HOME], 1))
    rows = [submission(0, HOME, [1])]
    assert pbr.dispute_target(steps, rows, actor=HOME).available is False

    (blind,) = anti_round(1, 0)
    blind_rows = [submission(0, HOME, [1, 2]), submission(0, AWAY, [3, 4])]
    assert pbr.dispute_target([blind], blind_rows, actor=HOME, blocked_rounds=frozenset({1})).available is False


def test_dispute_is_closed_for_a_side_that_did_not_act():
    (step,) = anti_round(1, 0)
    step = step.model_copy(update={"actors": [HOME]})
    rows = [submission(0, HOME, [1, 2])]
    assert pbr.dispute_target([step], rows, actor=AWAY).available is False
    assert pbr.dispute_target([step], rows, actor=HOME).available is True
