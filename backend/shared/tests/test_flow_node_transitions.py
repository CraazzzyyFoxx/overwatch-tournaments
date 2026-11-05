"""Per-kind node lifecycles (spec §5) and the derived tournament status (§9)."""

from __future__ import annotations

import itertools

import pytest

from shared.core.enums import FlowNodeKind as K
from shared.core.enums import FlowNodeStatus as S
from shared.core.enums import TournamentStatus as T
from shared.core.errors import ApiHTTPException
from shared.core.flow_state import (
    FlowNodeState,
    can_transition,
    derive_tournament_status,
    tournament_status_after,
    validate_transition,
)

_ALLOWED = {
    K.REGISTRATION: {
        (S.DRAFT, S.OPEN),
        (S.OPEN, S.CHECK_IN),
        (S.OPEN, S.CLOSED),
        (S.CHECK_IN, S.CLOSED),
        (S.CLOSED, S.OPEN),
    },
    K.FORMATION: {(S.DRAFT, S.FORMING), (S.FORMING, S.DRAFT), (S.FORMING, S.COMPLETED), (S.COMPLETED, S.FORMING)},
    K.STAGE: {(S.DRAFT, S.READY), (S.READY, S.DRAFT), (S.READY, S.LIVE), (S.LIVE, S.COMPLETED), (S.COMPLETED, S.LIVE)},
}
_STATUSES = {
    K.REGISTRATION: (S.DRAFT, S.OPEN, S.CHECK_IN, S.CLOSED),
    K.FORMATION: (S.DRAFT, S.FORMING, S.COMPLETED),
    K.STAGE: (S.DRAFT, S.READY, S.LIVE, S.COMPLETED),
}
_CASES = [
    (kind, current, target, (current, target) in _ALLOWED[kind])
    for kind, statuses in _STATUSES.items()
    for current, target in itertools.product(statuses, repeat=2)
]


@pytest.mark.parametrize(("kind", "current", "target", "allowed"), _CASES)
def test_transition_matrix(kind, current, target, allowed) -> None:
    assert can_transition(kind, current, target) is allowed


def test_validate_transition_raises_409_invalid_node_transition() -> None:
    with pytest.raises(ApiHTTPException) as caught:
        validate_transition(K.STAGE, S.DRAFT, S.LIVE)
    assert caught.value.status_code == 409
    assert caught.value.detail[0]["code"] == "invalid_node_transition"


@pytest.mark.parametrize("kind", [K.FILTER, K.MERGE, K.SPLIT, K.AGGREGATE, K.LEADERBOARD])
def test_pure_kinds_have_no_admin_transitions(kind) -> None:
    assert not can_transition(kind, S.PENDING, S.FINAL)


def _n(kind, status, sink=False) -> FlowNodeState:
    return FlowNodeState(kind=kind, status=status, is_sink=sink)


def test_derive_all_draft_is_announcement() -> None:
    assert derive_tournament_status([_n(K.REGISTRATION, S.DRAFT), _n(K.STAGE, S.DRAFT, True)]) is T.ANNOUNCEMENT


def test_derive_one_open_registration_is_live() -> None:
    assert derive_tournament_status([_n(K.REGISTRATION, S.OPEN), _n(K.STAGE, S.DRAFT, True)]) is T.LIVE


def test_derive_every_stage_sink_completed_is_completed() -> None:
    nodes = [_n(K.REGISTRATION, S.CLOSED), _n(K.STAGE, S.COMPLETED, True), _n(K.STAGE, S.COMPLETED, True)]
    assert derive_tournament_status(nodes) is T.COMPLETED


def test_derive_pure_sink_final_is_completed() -> None:
    nodes = [_n(K.STAGE, S.COMPLETED), _n(K.LEADERBOARD, S.FINAL, True)]
    assert derive_tournament_status(nodes) is T.COMPLETED


def test_derive_completed_non_sink_with_live_sink_is_live() -> None:
    nodes = [_n(K.STAGE, S.COMPLETED), _n(K.STAGE, S.LIVE, True)]
    assert derive_tournament_status(nodes) is T.LIVE


def test_status_after_archived_stays_archived_while_completed() -> None:
    assert tournament_status_after(T.ARCHIVED, T.COMPLETED) is T.ARCHIVED


def test_status_after_archived_reopened_is_live() -> None:
    assert tournament_status_after(T.ARCHIVED, T.LIVE) is T.LIVE


def test_status_after_completed_follows_derived() -> None:
    assert tournament_status_after(T.COMPLETED, T.LIVE) is T.LIVE


def test_status_after_announcement_follows_derived() -> None:
    assert tournament_status_after(T.ANNOUNCEMENT, T.LIVE) is T.LIVE
