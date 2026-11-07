"""The graph rules of spec §6: port catalogue, units, validation."""

from shared.core.enums import FlowNodeKind as K
from shared.core.enums import FlowUnit, StageType
from shared.domain.flow.validate import (
    FlowEdgeSpec,
    FlowNodeSpec,
    resolve_ports,
    topological_order,
    validate_flow,
)


def node(id, kind, config=None, *, stage_id=None, stage_type=None) -> FlowNodeSpec:
    return FlowNodeSpec(id=id, kind=kind, config=config or {}, stage_id=stage_id, stage_type=stage_type)


def edge(id, source, source_port, target, target_port) -> FlowEdgeSpec:
    return FlowEdgeSpec(
        id=id, source_node_id=source, source_port=source_port, target_node_id=target, target_port=target_port
    )


REG = node(1, K.REGISTRATION)
FORM = node(2, K.FORMATION, {"mode": "balancer"})
GROUPS = node(3, K.STAGE, stage_id=30, stage_type=StageType.ROUND_ROBIN)
TOP = node(4, K.FILTER, {"mode": "per_item_top", "n": 2, "per_item": {"301": 2}})
PLAYOFF = node(5, K.STAGE, stage_id=50, stage_type=StageType.SINGLE_ELIMINATION)
LEGACY_NODES = [REG, FORM, GROUPS, TOP, PLAYOFF]
LEGACY_EDGES = [
    edge(1, 1, "participants", 2, "players"),
    edge(2, 2, "teams", 3, "participants"),
    edge(3, 3, "ranking", 4, "ranking"),
    edge(4, 4, "passed", 5, "participants"),
]


def codes(issues, severity="error"):
    return [(i.code, i.node_id, i.edge_id) for i in issues if i.severity == severity]


def test_a_legacy_graph_is_clean() -> None:
    assert validate_flow(LEGACY_NODES, LEGACY_EDGES) == []


def test_a_cycle_is_an_error() -> None:
    a, b = node(6, K.FILTER, {"mode": "top", "n": 1}), node(7, K.FILTER, {"mode": "top", "n": 1})
    issues = validate_flow([a, b], [edge(1, 6, "passed", 7, "ranking"), edge(2, 7, "passed", 6, "ranking")])
    assert codes(issues) == [("cycle", 6, None)]


def test_an_unknown_node_or_port_is_an_error() -> None:
    issues = validate_flow([REG, FORM], [edge(1, 1, "nope", 2, "players"), edge(2, 1, "participants", 99, "players")])
    assert codes(issues) == [("unknown_node", None, 2), ("unknown_port", None, 1)]


def test_teams_into_an_individual_swiss_stage_is_a_unit_mismatch() -> None:
    swiss = node(3, K.STAGE, stage_id=30, stage_type=StageType.INDIVIDUAL_SWISS)
    issues = validate_flow(
        [REG, FORM, swiss], [edge(1, 1, "participants", 2, "players"), edge(2, 2, "teams", 3, "participants")]
    )
    assert codes(issues) == [("unit_mismatch", None, 2)]


def test_teams_dissolve_into_a_formation_and_expand_into_a_player_aggregate() -> None:
    form = node(6, K.FORMATION, {"mode": "draft"})
    agg = node(7, K.AGGREGATE, {"unit": "players", "score": {"preset": "stage_points"}, "mode": "sum_all"})
    issues = validate_flow(
        [REG, FORM, GROUPS, form, agg],
        [
            edge(1, 1, "participants", 2, "players"),
            edge(2, 2, "teams", 3, "participants"),
            edge(3, 3, "ranking", 6, "players"),
            edge(4, 3, "ranking", 7, "inputs"),
        ],
    )
    assert codes(issues) == []


def test_merge_inputs_must_share_a_unit() -> None:
    merge = node(6, K.MERGE)
    issues = validate_flow(
        [REG, FORM, merge],
        [
            edge(1, 1, "participants", 2, "players"),
            edge(2, 1, "participants", 6, "inputs"),
            edge(3, 2, "teams", 6, "inputs"),
        ],
    )
    assert codes(issues) == [("unit_mismatch", None, 3)]


def test_a_second_edge_into_a_single_input_port_is_an_error_but_not_into_a_multi_one() -> None:
    issues = validate_flow(LEGACY_NODES, [*LEGACY_EDGES, edge(9, 2, "teams", 5, "participants")])
    assert codes(issues) == [("port_taken", None, 9)]
    merge = node(6, K.MERGE)
    assert (
        codes(validate_flow([FORM, merge], [edge(1, 2, "teams", 6, "inputs"), edge(2, 2, "teams", 6, "inputs")])) == []
    )


def test_a_stage_node_needs_its_stage() -> None:
    assert codes(validate_flow([node(3, K.STAGE)], [])) == [("stage_without_stage_id", 3, None)]


def test_aggregate_n_cannot_exceed_its_inputs() -> None:
    def agg(n, mode="sum_best_n"):
        return node(7, K.AGGREGATE, {"unit": "teams", "score": {"preset": "stage_points"}, "mode": mode, "n": n})

    two = [edge(1, 3, "ranking", 7, "inputs"), edge(2, 5, "ranking", 7, "inputs")]
    assert codes(validate_flow([GROUPS, PLAYOFF, agg(3)], two)) == [("aggregate_n_exceeds_inputs", 7, None)]
    assert codes(validate_flow([GROUPS, PLAYOFF, agg(2)], two)) == []
    for mode in ("sum_all", "average"):  # N is unused by these modes
        assert codes(validate_flow([GROUPS, PLAYOFF, agg(3, mode)], two)) == []


def test_an_unparseable_config_is_an_error() -> None:
    issues = validate_flow([node(2, K.FORMATION, {}), node(4, K.FILTER, {"mode": "top"})], [])
    assert codes(issues) == [("invalid_config", 2, None), ("invalid_config", 4, None)]


def test_a_team_intake_registration_feeds_only_a_registered_formation() -> None:
    reg = node(1, K.REGISTRATION, {"intake": "team"})
    wired = [edge(1, 1, "participants", 2, "players")]
    assert codes(validate_flow([reg, FORM], wired)) == [("team_intake_target", None, 1)]
    assert codes(validate_flow([reg, node(2, K.FORMATION, {"mode": "registered"})], wired)) == []


def test_a_ranking_by_role_feeds_only_a_leaderboard() -> None:
    agg = node(
        7, K.AGGREGATE, {"unit": "players", "score": {"preset": "stage_points"}, "mode": "sum_all", "by_role": True}
    )
    feed = edge(1, 3, "ranking", 7, "inputs")
    board, top = node(8, K.LEADERBOARD), node(9, K.FILTER, {"mode": "top", "n": 8})
    assert codes(validate_flow([GROUPS, agg, board], [feed, edge(2, 7, "ranking", 8, "ranking")])) == []
    assert codes(validate_flow([GROUPS, agg, top], [feed, edge(2, 7, "ranking", 9, "ranking")])) == [
        ("aggregate_by_role_target", None, 2)
    ]


def test_warnings_do_not_block() -> None:
    issues = validate_flow(
        [FORM, GROUPS, TOP], [edge(1, 2, "teams", 3, "participants"), edge(2, 3, "ranking", 4, "ranking")]
    )
    assert codes(issues) == []
    assert codes(issues, "warning") == [("missing_input", 2, None), ("sink_not_terminal", 4, None)]


def test_resolve_ports_expands_split_buckets_with_their_units() -> None:
    split = node(6, K.SPLIT, {"buckets": [{"name": "High", "size": 4}, {"name": "Low"}]})
    swiss = node(7, K.STAGE, stage_id=70, stage_type=StageType.INDIVIDUAL_SWISS)
    ports = resolve_ports([FORM, split, swiss], [edge(1, 2, "teams", 6, "ranking")])
    assert [(p.name, p.direction, p.unit) for p in ports[6]] == [
        ("ranking", "in", FlowUnit.TEAMS),
        ("bucket_1", "out", FlowUnit.TEAMS),
        ("bucket_2", "out", FlowUnit.TEAMS),
    ]
    assert [(p.name, p.unit) for p in ports[7]] == [("participants", FlowUnit.PLAYERS), ("ranking", FlowUnit.PLAYERS)]


def test_topological_order_is_by_id_and_none_on_a_cycle() -> None:
    assert topological_order([3, 1, 2], [(1, 3), (2, 3)]) == [1, 2, 3]
    assert topological_order([1, 2], [(1, 2), (2, 1)]) is None
