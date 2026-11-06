"""Spec §14: what graph a legacy tournament becomes, and that its status survives."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from shared.core.enums import FlowNodeKind as K
from shared.core.enums import FlowNodeStatus as S
from shared.core.enums import StageType
from shared.domain.flow.legacy import (
    LegacySchedule,
    LegacySourceRef,
    LegacyStage,
    LegacyStageItem,
    LegacyStatusMismatch,
    LegacyTournament,
    PlannedSchedule,
    assert_status_reproduced,
    plan_legacy_flow,
)
from shared.domain.flow.validate import FlowEdgeSpec, FlowNodeSpec, validate_flow

T0 = datetime(2026, 11, 1, tzinfo=UTC)
LIFECYCLE = {K.REGISTRATION, K.FORMATION, K.STAGE}


def item(id, order=0, advance=None):
    return LegacyStageItem(id=id, order=order, advance_count=advance)


def stage(
    id,
    name,
    stage_type="round_robin",
    order=0,
    *,
    active=False,
    published=False,
    completed=False,
    advance=None,
    items=(),
    locked=False,
    qualified=0,
):
    return LegacyStage(
        id=id,
        name=name,
        stage_type=stage_type,
        order=order,
        is_active=active,
        is_published=published,
        is_completed=completed,
        advance_count=advance,
        qualification_locked=locked,
        qualified_count=qualified,
        items=tuple(items),
    )


def tournament(*stages, status="live", formation="balancer", teams=True, check_in=False, refs=(), schedules=()):
    return LegacyTournament(
        id=7,
        status=status,
        team_formation=formation,
        has_teams=teams,
        check_in_used=check_in,
        stages=tuple(stages),
        source_refs=tuple(refs),
        schedules=tuple(schedules),
    )


def statuses(plan):
    return {n.name: n.status for n in plan.nodes if n.kind in LIFECYCLE}


def edges(plan):
    name = {n.key: n.name for n in plan.nodes}
    return {(name[e.source_key], e.source_port, name[e.target_key], e.target_port) for e in plan.edges}


def by_name(plan, name):
    return next(n for n in plan.nodes if n.name == name)


GROUPS = stage(10, "Groups", order=0, published=True, completed=True, items=[item(101, 0), item(102, 1)])
PLAYOFF = stage(20, "Playoff", "single_elimination", 1, active=True, published=True, items=[item(201)])
REFS = [
    LegacySourceRef(20, 101, 1),
    LegacySourceRef(20, 101, 2),
    LegacySourceRef(20, 102, 1),
    LegacySourceRef(20, 102, 2),
]
BASE = {("Registration", "participants", "Teams", "players")}


def test_a_single_stage() -> None:
    plan = plan_legacy_flow(tournament(stage(10, "Main", active=True, published=True)))
    assert statuses(plan) == {"Registration": S.CLOSED, "Teams": S.COMPLETED, "Main": S.LIVE}
    assert edges(plan) == BASE | {("Teams", "teams", "Main", "participants")}
    assert by_name(plan, "Registration").config == {"check_in": False, "intake": "solo"}
    assert by_name(plan, "Teams").config == {"mode": "balancer"}
    assert [n.stage_id for n in plan.nodes] == [None, None, 10]


def test_groups_to_playoff_with_source_refs() -> None:
    plan = plan_legacy_flow(tournament(GROUPS, PLAYOFF, refs=REFS))
    assert edges(plan) == BASE | {
        ("Teams", "teams", "Groups", "participants"),
        ("Groups", "ranking", "Top 2 per group", "ranking"),
        ("Top 2 per group", "passed", "Playoff", "participants"),
    }
    top = by_name(plan, "Top 2 per group")
    assert (top.kind, top.status, top.config) == (
        K.FILTER,
        S.PENDING,
        {"mode": "per_item_top", "n": 2, "per_item": {"101": 2, "102": 2}},
    )


def test_groups_to_playoff_from_advance_count_alone() -> None:
    groups = replace(GROUPS, advance_count=2, items=(item(101, 0, advance=3), item(102, 1)))
    plan = plan_legacy_flow(tournament(groups, PLAYOFF))
    assert ("Top 3 per group", "passed", "Playoff", "participants") in edges(plan)
    assert by_name(plan, "Top 3 per group").config == {"mode": "per_item_top", "n": 3, "per_item": {"101": 3, "102": 2}}


def test_parallel_same_order_stages_share_a_column_and_an_ambiguous_playoff_takes_the_teams() -> None:
    low = stage(10, "Low", advance=2, items=[item(101)])
    high = stage(11, "High", advance=2, items=[item(111)])
    plan = plan_legacy_flow(tournament(low, high, stage(20, "Playoff", "single_elimination", 1)))
    assert edges(plan) == BASE | {("Teams", "teams", x, "participants") for x in ("Low", "High", "Playoff")}
    assert [
        (by_name(plan, x).position_x, by_name(plan, x).position_y)
        for x in ("Registration", "Teams", "Low", "High", "Playoff")
    ] == [(0.0, 0.0), (300.0, 0.0), (600.0, 0.0), (600.0, 150.0), (900.0, 0.0)]


def test_two_source_stages_merge_in_stage_order() -> None:
    low = stage(10, "Low", items=[item(101, 0), item(102, 1)])
    high = stage(11, "High", items=[item(111, 0), item(112, 1)])
    refs = [LegacySourceRef(20, i, p) for i, p in ((101, 1), (101, 2), (102, 1), (102, 2), (111, 1), (112, 1))]
    plan = plan_legacy_flow(tournament(low, high, stage(20, "Playoff", "single_elimination", 1), refs=refs))
    assert edges(plan) == BASE | {
        ("Teams", "teams", "Low", "participants"),
        ("Teams", "teams", "High", "participants"),
        ("Low", "ranking", "Top 2 per group", "ranking"),
        ("High", "ranking", "Top 1 per group", "ranking"),
        ("Top 2 per group", "passed", "Merge", "inputs"),
        ("Top 1 per group", "passed", "Merge", "inputs"),
        ("Merge", "merged", "Playoff", "participants"),
    }
    name = {n.key: n.name for n in plan.nodes}
    into_merge = [name[e.source_key] for e in plan.edges if name[e.target_key] == "Merge"]
    assert into_merge == ["Top 2 per group", "Top 1 per group"]


def test_individual_swiss_locked_with_a_playoff_drafts_its_qualifiers() -> None:
    swiss = stage(10, "Swiss", "individual_swiss", 0, published=True, completed=True, locked=True, qualified=10)
    plan = plan_legacy_flow(tournament(swiss, PLAYOFF, formation="draft"))
    assert edges(plan) == {
        ("Registration", "participants", "Swiss", "participants"),
        ("Swiss", "ranking", "Top 10", "ranking"),
        ("Top 10", "passed", "Teams", "players"),
        ("Teams", "teams", "Playoff", "participants"),
    }
    assert by_name(plan, "Top 10").config == {"mode": "top", "n": 10}
    assert by_name(plan, "Teams").config == {"mode": "draft"}


def test_individual_swiss_not_yet_locked_keeps_the_plain_formation() -> None:
    swiss = stage(10, "Swiss", "individual_swiss", 0, active=True, published=True)
    plan = plan_legacy_flow(tournament(swiss, PLAYOFF, formation="draft"))
    assert edges(plan) == BASE | {
        ("Registration", "participants", "Swiss", "participants"),
        ("Teams", "teams", "Playoff", "participants"),
    }


@pytest.mark.parametrize(
    ("status", "registration", "teams", "groups", "playoff"),
    [
        ("announcement", S.DRAFT, S.DRAFT, S.DRAFT, S.DRAFT),
        ("registration", S.OPEN, S.COMPLETED, S.COMPLETED, S.LIVE),
        ("check_in", S.CHECK_IN, S.COMPLETED, S.COMPLETED, S.LIVE),
        ("draft", S.CLOSED, S.COMPLETED, S.COMPLETED, S.LIVE),
        ("live", S.CLOSED, S.COMPLETED, S.COMPLETED, S.LIVE),
        ("playoffs", S.CLOSED, S.COMPLETED, S.COMPLETED, S.LIVE),
        ("completed", S.CLOSED, S.COMPLETED, S.COMPLETED, S.COMPLETED),
        ("archived", S.CLOSED, S.COMPLETED, S.COMPLETED, S.COMPLETED),
    ],
)
def test_each_old_status_maps_and_reproduces(status, registration, teams, groups, playoff) -> None:
    t = tournament(GROUPS, PLAYOFF, refs=REFS, status=status)
    plan = plan_legacy_flow(t)
    assert statuses(plan) == {"Registration": registration, "Teams": teams, "Groups": groups, "Playoff": playoff}
    assert_status_reproduced(t, plan)


@pytest.mark.parametrize(
    ("t", "expected"),
    [
        (
            tournament(stage(10, "Only", active=True, published=True), status="completed", teams=False),
            {"Teams": S.COMPLETED, "Only": S.COMPLETED},
        ),
        (
            tournament(GROUPS, replace(PLAYOFF, is_completed=True), refs=REFS, status="live"),
            {"Teams": S.COMPLETED, "Groups": S.COMPLETED, "Playoff": S.LIVE},
        ),
        (tournament(status="live"), {"Teams": S.FORMING}),
        (
            tournament(stage(10, "Only", active=True, published=True), status="announcement"),
            {"Teams": S.DRAFT, "Only": S.DRAFT},
        ),
        (tournament(status="completed", teams=False), {"Teams": S.COMPLETED}),
    ],
    ids=["finished-unflagged", "live-all-flagged", "live-no-stages", "announcement-with-teams", "finished-empty"],
)
def test_status_clamps_keep_the_tournament_status(t, expected) -> None:
    plan = plan_legacy_flow(t)
    assert {k: v for k, v in statuses(plan).items() if k != "Registration"} == expected
    assert_status_reproduced(t, plan)


def test_registration_and_check_in_schedules_move_to_the_registration_node() -> None:
    t1, t2, t3 = T0 + timedelta(days=1), T0 + timedelta(days=2), T0 + timedelta(days=3)
    t = tournament(
        status="registration",
        check_in=True,
        schedules=[
            LegacySchedule("registration", T0, None),
            LegacySchedule("check_in", t1, t2),
            LegacySchedule("live", t3, None),
        ],
    )
    plan = plan_legacy_flow(t)
    assert plan.schedules == (PlannedSchedule(0, "open", T0, None), PlannedSchedule(0, "check_in", t1, t2))
    assert by_name(plan, "Registration").config["check_in"] is True


def test_formation_modes_and_team_intake() -> None:
    def configs(formation):
        plan = plan_legacy_flow(tournament(formation=formation))
        return by_name(plan, "Registration").config["intake"], by_name(plan, "Teams").config["mode"]

    assert [configs(f) for f in ("balancer", "draft", "registration", "solo", "weird")] == [
        ("solo", "balancer"),
        ("solo", "draft"),
        ("team", "registered"),
        ("solo", "manual"),
        ("solo", "manual"),
    ]


def test_a_ref_to_an_unknown_item_is_ignored() -> None:
    plan = plan_legacy_flow(tournament(GROUPS, PLAYOFF, refs=[LegacySourceRef(20, 999, 1)]))
    assert ("Teams", "teams", "Playoff", "participants") in edges(plan)
    assert not [n for n in plan.nodes if n.kind == K.FILTER]


LOOPING_REFS = {
    "self": [LegacySourceRef(20, 101, 1), LegacySourceRef(20, 201, 1)],
    "mutual": [LegacySourceRef(20, 101, 1), LegacySourceRef(10, 201, 1)],
}


@pytest.mark.parametrize("refs", LOOPING_REFS.values(), ids=LOOPING_REFS)
def test_refs_that_do_not_come_from_an_earlier_stage_are_ignored(refs) -> None:
    t = tournament(GROUPS, PLAYOFF, refs=refs)
    plan = plan_legacy_flow(t)
    assert ("Groups", "ranking", "Top 1 per group", "ranking") in edges(plan)
    assert ("Playoff", "ranking", "Top 1 per group", "ranking") not in edges(plan)
    assert ("Teams", "teams", "Groups", "participants") in edges(plan)
    assert_status_reproduced(t, plan)


def test_an_explicit_zero_advance_on_an_item_reads_as_the_stage_default() -> None:
    # Same reading as group_advance_counts in the wiring code: 0 is "no override" (the API rejects it anyway).
    groups = replace(GROUPS, advance_count=2, items=(item(101, 0, advance=0), item(102, 1, advance=3)))
    plan = plan_legacy_flow(tournament(groups, PLAYOFF))
    assert by_name(plan, "Top 3 per group").config == {"mode": "per_item_top", "n": 3, "per_item": {"101": 2, "102": 3}}


def test_a_status_mismatch_aborts_with_the_tournament_named() -> None:
    t = tournament(stage(10, "Main", active=True, published=True))
    plan = plan_legacy_flow(t)
    broken = replace(plan, nodes=tuple(replace(n, status=S.DRAFT) for n in plan.nodes))
    with pytest.raises(LegacyStatusMismatch, match="tournament 7"):
        assert_status_reproduced(t, broken)


def test_every_planned_graph_validates_without_errors() -> None:
    swiss = stage(10, "Swiss", "individual_swiss", 0, published=True, completed=True, locked=True, qualified=10)
    cases = [
        tournament(stage(10, "Main")),
        tournament(GROUPS, PLAYOFF, refs=REFS),
        tournament(replace(GROUPS, advance_count=2), PLAYOFF),
        tournament(swiss, PLAYOFF, formation="draft"),
        tournament(formation="registration"),
        *(tournament(GROUPS, PLAYOFF, refs=refs) for refs in LOOPING_REFS.values()),
    ]
    for t in cases:
        plan = plan_legacy_flow(t)
        types = {s.id: StageType(s.stage_type) for s in t.stages}
        nodes = [FlowNodeSpec(n.key, n.kind, n.config, n.stage_id, types.get(n.stage_id)) for n in plan.nodes]
        specs = [
            FlowEdgeSpec(i, e.source_key, e.source_port, e.target_key, e.target_port) for i, e in enumerate(plan.edges)
        ]
        assert [i for i in validate_flow(nodes, specs) if i.severity == "error"] == [], t
