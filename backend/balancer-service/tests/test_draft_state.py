from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

from shared.core import draft_state  # noqa: E402
from shared.core.enums import DraftStatus  # noqa: E402
from shared.core.errors import ApiHTTPException  # noqa: E402

S = DraftStatus

_LEGAL_EDGES = {
    (S.SETUP, S.READY),
    (S.SETUP, S.CANCELLED),
    (S.READY, S.SETUP),
    (S.READY, S.LIVE),
    (S.READY, S.CANCELLED),
    (S.LIVE, S.PAUSED),
    (S.LIVE, S.COMPLETED),
    (S.LIVE, S.CANCELLED),
    (S.PAUSED, S.LIVE),
    (S.PAUSED, S.PAUSED),
    (S.PAUSED, S.CANCELLED),
    (S.COMPLETED, S.PAUSED),
}

_ALL_PAIRS = [(a, b) for a in S for b in S if a != b]


@pytest.mark.parametrize(("current", "target"), sorted(_LEGAL_EDGES))
def test_legal_transitions_allowed(current: DraftStatus, target: DraftStatus) -> None:
    assert draft_state.can_transition(current, target) is True
    draft_state.validate_transition(current, target)  # must not raise


@pytest.mark.parametrize(("current", "target"), [p for p in _ALL_PAIRS if p not in _LEGAL_EDGES])
def test_illegal_transitions_rejected(current: DraftStatus, target: DraftStatus) -> None:
    assert draft_state.can_transition(current, target) is False
    with pytest.raises(ApiHTTPException):
        draft_state.validate_transition(current, target)


def test_cancelled_state_has_no_outgoing_edges() -> None:
    for target in S:
        if target == S.CANCELLED:
            continue
        assert draft_state.can_transition(S.CANCELLED, target) is False


def test_completed_is_not_reachable_by_admin_only_states() -> None:
    # COMPLETED is a system transition reached only from LIVE.
    reachable_into_completed = {a for a in S if draft_state.can_transition(a, S.COMPLETED)}
    assert reachable_into_completed == {S.LIVE}


def test_validate_transition_error_code() -> None:
    with pytest.raises(ApiHTTPException) as exc_info:
        draft_state.validate_transition(S.COMPLETED, S.LIVE)
    detail = exc_info.value.detail
    assert any(item["code"] == "invalid_draft_transition" for item in detail)
