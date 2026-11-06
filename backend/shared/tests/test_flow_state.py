"""The tournament status derived from its flow nodes (spec §9)."""

from shared.core.enums import FlowNodeKind as K
from shared.core.enums import FlowNodeStatus as S
from shared.core.enums import TournamentStatus
from shared.core.flow_state import FlowNodeState, derive_tournament_status


def n(kind: K, status: S, sink: bool = False) -> FlowNodeState:
    return FlowNodeState(kind=kind, status=status, is_sink=sink)


def test_no_nodes_is_an_announcement() -> None:
    assert derive_tournament_status([]) is TournamentStatus.ANNOUNCEMENT


def test_every_lifecycle_node_in_draft_is_an_announcement() -> None:
    nodes = [n(K.REGISTRATION, S.DRAFT), n(K.FORMATION, S.DRAFT), n(K.STAGE, S.DRAFT), n(K.FILTER, S.PENDING, True)]
    assert derive_tournament_status(nodes) is TournamentStatus.ANNOUNCEMENT


def test_one_lifecycle_node_out_of_draft_is_live() -> None:
    nodes = [n(K.REGISTRATION, S.OPEN), n(K.FORMATION, S.DRAFT), n(K.STAGE, S.DRAFT, True)]
    assert derive_tournament_status(nodes) is TournamentStatus.LIVE


def test_every_sink_done_is_completed() -> None:
    nodes = [n(K.REGISTRATION, S.CLOSED), n(K.STAGE, S.COMPLETED, True), n(K.LEADERBOARD, S.FINAL, True)]
    assert derive_tournament_status(nodes) is TournamentStatus.COMPLETED


def test_a_tentative_pure_sink_keeps_it_live() -> None:
    nodes = [n(K.REGISTRATION, S.CLOSED), n(K.STAGE, S.COMPLETED, True), n(K.LEADERBOARD, S.TENTATIVE, True)]
    assert derive_tournament_status(nodes) is TournamentStatus.LIVE


def test_a_live_stage_sink_keeps_it_live_even_beside_a_completed_one() -> None:
    nodes = [n(K.FORMATION, S.COMPLETED, True), n(K.STAGE, S.LIVE, True), n(K.REGISTRATION, S.CLOSED)]
    assert derive_tournament_status(nodes) is TournamentStatus.LIVE
