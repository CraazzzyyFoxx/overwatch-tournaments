from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from pydantic import ValidationError  # noqa: E402

from shared.core.enums import (  # noqa: E402
    DraftAutopickStrategy,
    DraftFormat,
    DraftPoolSource,
    DraftStatus,
)
from shared.domain.roster_shape import parse_roster_slots  # noqa: E402
from shared.models.balancer.draft import DraftSession  # noqa: E402
from shared.schemas.roster_slots import RosterShapeRead  # noqa: E402
from src import schemas  # noqa: E402
from src.domain.draft import rules  # noqa: E402


def test_create_request_defaults() -> None:
    req = schemas.DraftSessionCreateRequest()
    assert req.pool_source == DraftPoolSource.BALANCER_BALANCE
    assert req.format == DraftFormat.SNAKE
    assert req.pick_time_seconds == 45
    assert req.autopick_strategy == DraftAutopickStrategy.BEST_FIT
    assert req.allow_admin_override is True


def test_create_request_no_longer_carries_the_roster_size() -> None:
    # The shape owns both, so neither may reappear as a request field.
    assert "rounds" not in schemas.DraftSessionCreateRequest.model_fields
    assert "team_size" not in schemas.DraftSessionCreateRequest.model_fields


def test_create_request_ignores_a_stale_client_sending_rounds_or_team_size() -> None:
    # Pydantic's default `extra="ignore"`: the keys are accepted and dropped, so
    # an old admin bundle keeps working and cannot influence the created session.
    req = schemas.DraftSessionCreateRequest(rounds=7, team_size=11)

    assert not hasattr(req, "rounds")
    assert not hasattr(req, "team_size")
    assert req.model_dump() == schemas.DraftSessionCreateRequest().model_dump()


def test_lifecycle_rejects_rounds_that_do_not_match_the_shape() -> None:
    with pytest.raises(Exception) as exc_info:
        rules.validate_draft_rounds(rounds=3, shape=parse_roster_slots({"flex": 6}))

    assert exc_info.value.detail[0]["code"] == "invalid_roster_shape"


def test_lifecycle_accepts_rounds_equal_to_the_shape_minus_the_captain() -> None:
    rules.validate_draft_rounds(rounds=5, shape=parse_roster_slots({"flex": 6}))


def test_session_read_reports_the_shape_and_never_a_scalar_team_size() -> None:
    assert "team_size" not in schemas.DraftSessionRead.model_fields
    assert schemas.DraftSessionRead.model_fields["roster_shape"].annotation is RosterShapeRead


def test_session_read_from_session_projects_the_resolved_shape() -> None:
    # A transient row has no column defaults applied (those land on INSERT), so
    # every non-nullable field is spelled out here.
    shape = parse_roster_slots({"tank": 1, "flex": 5})
    read = schemas.DraftSessionRead.from_session(
        DraftSession(
            id=1,
            tournament_id=2,
            workspace_id=3,
            status=DraftStatus.SETUP.value,
            format=DraftFormat.SNAKE.value,
            rounds=shape.draft_rounds,
            pick_time_seconds=45,
            overtime_seconds=0,
            pool_source=DraftPoolSource.BALANCER_BALANCE.value,
            autopick_strategy=DraftAutopickStrategy.BEST_FIT.value,
            allow_admin_override=True,
            settings_json={},
            version=1,
        ),
        shape=shape,
    )

    assert read.rounds == 5
    assert read.roster_shape.team_size == 6
    assert read.roster_shape.draft_rounds == 5
    assert read.roster_shape.has_role_slots is True
    assert read.roster_shape.slots == {"tank": 1, "flex": 5}


def test_roster_shape_read_is_one_class_shared_with_tournament_service() -> None:
    # A second copy in balancer-service would be the mirror this feature removes.
    from src.schemas import RosterShapeRead as balancer_read

    assert balancer_read is RosterShapeRead


@pytest.mark.parametrize("seconds", [9, 601])
def test_create_request_rejects_bad_pick_time(seconds: int) -> None:
    with pytest.raises(ValidationError):
        schemas.DraftSessionCreateRequest(pick_time_seconds=seconds)


def test_order_request_accepts_permutation() -> None:
    req = schemas.DraftOrderRequest(
        order=[
            schemas.DraftOrderEntry(draft_team_id=10, draft_position=2),
            schemas.DraftOrderEntry(draft_team_id=11, draft_position=1),
            schemas.DraftOrderEntry(draft_team_id=12, draft_position=3),
        ]
    )
    assert len(req.order) == 3


def test_order_request_rejects_non_permutation() -> None:
    with pytest.raises(ValidationError):
        schemas.DraftOrderRequest(
            order=[
                schemas.DraftOrderEntry(draft_team_id=10, draft_position=1),
                schemas.DraftOrderEntry(draft_team_id=11, draft_position=3),  # gap, no 2
            ]
        )


def test_order_request_rejects_duplicate_team_ids() -> None:
    with pytest.raises(ValidationError):
        schemas.DraftOrderRequest(
            order=[
                schemas.DraftOrderEntry(draft_team_id=10, draft_position=1),
                schemas.DraftOrderEntry(draft_team_id=10, draft_position=2),
            ]
        )


def test_select_request_requires_expected_version() -> None:
    with pytest.raises(ValidationError):
        schemas.DraftPickSelectRequest(player_id=5)  # type: ignore[call-arg]
    ok = schemas.DraftPickSelectRequest(player_id=5, expected_version=0)
    assert ok.expected_version == 0


def test_patch_request_pick_time_validation() -> None:
    assert schemas.DraftSessionPatchRequest().pick_time_seconds is None
    with pytest.raises(ValidationError):
        schemas.DraftSessionPatchRequest(pick_time_seconds=5)


@pytest.mark.parametrize("seconds", [-1, 301])
def test_create_request_rejects_overtime_outside_the_allowed_window(seconds: int) -> None:
    with pytest.raises(ValidationError):
        schemas.DraftSessionCreateRequest(overtime_seconds=seconds)


def test_create_request_defaults_to_no_overtime() -> None:
    # 0 keeps the pre-overtime behaviour: an expired clock autopicks at once.
    assert schemas.DraftSessionCreateRequest().overtime_seconds == 0
    assert schemas.DraftSessionCreateRequest(overtime_seconds=300).overtime_seconds == 300


def test_patch_request_overtime_is_optional_and_range_checked() -> None:
    assert schemas.DraftSessionPatchRequest().overtime_seconds is None
    assert schemas.DraftSessionPatchRequest(overtime_seconds=0).overtime_seconds == 0
    with pytest.raises(ValidationError):
        schemas.DraftSessionPatchRequest(overtime_seconds=301)


@pytest.mark.parametrize("seconds", [4, 301])
def test_extend_request_rejects_seconds_outside_the_allowed_window(seconds: int) -> None:
    with pytest.raises(ValidationError):
        schemas.DraftPickExtendRequest(expected_version=0, seconds=seconds)


def test_extend_request_requires_the_optimistic_token() -> None:
    with pytest.raises(ValidationError):
        schemas.DraftPickExtendRequest(seconds=30)
    ok = schemas.DraftPickExtendRequest(expected_version=3, seconds=30)
    assert (ok.expected_version, ok.seconds) == (3, 30)
