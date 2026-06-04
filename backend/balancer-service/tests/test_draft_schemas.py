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

from pydantic import ValidationError  # noqa: E402

from shared.core.enums import DraftAutopickStrategy, DraftFormat, DraftPoolSource  # noqa: E402
from src.schemas import draft as ds  # noqa: E402


def test_create_request_defaults() -> None:
    req = ds.DraftSessionCreateRequest()
    assert req.pool_source == DraftPoolSource.BALANCER_BALANCE
    assert req.format == DraftFormat.SNAKE
    assert req.rounds == 4
    assert req.pick_time_seconds == 45
    assert req.team_size == 5
    assert req.autopick_strategy == DraftAutopickStrategy.BEST_FIT
    assert req.allow_admin_override is True


@pytest.mark.parametrize("rounds", [0, 9, -1])
def test_create_request_rejects_bad_rounds(rounds: int) -> None:
    with pytest.raises(ValidationError):
        ds.DraftSessionCreateRequest(rounds=rounds)


@pytest.mark.parametrize("seconds", [9, 601])
def test_create_request_rejects_bad_pick_time(seconds: int) -> None:
    with pytest.raises(ValidationError):
        ds.DraftSessionCreateRequest(pick_time_seconds=seconds)


def test_order_request_accepts_permutation() -> None:
    req = ds.DraftOrderRequest(
        order=[
            ds.DraftOrderEntry(draft_team_id=10, draft_position=2),
            ds.DraftOrderEntry(draft_team_id=11, draft_position=1),
            ds.DraftOrderEntry(draft_team_id=12, draft_position=3),
        ]
    )
    assert len(req.order) == 3


def test_order_request_rejects_non_permutation() -> None:
    with pytest.raises(ValidationError):
        ds.DraftOrderRequest(
            order=[
                ds.DraftOrderEntry(draft_team_id=10, draft_position=1),
                ds.DraftOrderEntry(draft_team_id=11, draft_position=3),  # gap, no 2
            ]
        )


def test_order_request_rejects_duplicate_team_ids() -> None:
    with pytest.raises(ValidationError):
        ds.DraftOrderRequest(
            order=[
                ds.DraftOrderEntry(draft_team_id=10, draft_position=1),
                ds.DraftOrderEntry(draft_team_id=10, draft_position=2),
            ]
        )


def test_select_request_requires_expected_version() -> None:
    with pytest.raises(ValidationError):
        ds.DraftPickSelectRequest(player_id=5)  # type: ignore[call-arg]
    ok = ds.DraftPickSelectRequest(player_id=5, expected_version=0)
    assert ok.expected_version == 0


def test_patch_request_pick_time_validation() -> None:
    assert ds.DraftSessionPatchRequest().pick_time_seconds is None
    with pytest.raises(ValidationError):
        ds.DraftSessionPatchRequest(pick_time_seconds=5)
