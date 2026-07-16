from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

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

from shared.core.enums import DraftPickStatus, DraftRole  # noqa: E402
from shared.models.balancer.draft import DraftPick, DraftSession  # noqa: E402
from src import openapi_docs, openapi_schemas  # noqa: E402
from src.rpc import draft as draft_rpc  # noqa: E402
from src.schemas import draft as schemas  # noqa: E402
from src.services.draft import board, lifecycle  # noqa: E402


class _FakeBroker:
    def __init__(self) -> None:
        self.subjects: set[str] = set()

    def subscriber(self, subject: str):
        self.subjects.add(subject)

        def decorator(function):
            return function

        return decorator


class _FakeLogger:
    def warning(self, *args, **kwargs) -> None:
        return None


def test_feasibility_and_pick_options_have_typed_public_contracts() -> None:
    feasibility = schemas.DraftFeasibilityResponse(
        is_feasible=False,
        total_open_slots=2,
        matched_slots=1,
        unmatched_slots=[{"team_id": 10, "role": "support", "ordinal": 0}],
        role_deficits=[{"role": "support", "unmatched_slots": 1, "eligible_players": 0}],
        blocking_player_ids=[],
        reason_code="role_shortage",
    )
    options = schemas.DraftPickOptionsResponse(
        pick_id=30,
        pick_version=4,
        draft_team_id=10,
        options=[
            {
                "player_id": 20,
                "role": "support",
                "is_safe": False,
                "reason_code": "role_shortage",
                "unmatched_slots": feasibility.unmatched_slots,
                "blocking_player_ids": [],
                "suggestion_score": None,
            }
        ],
    )

    assert feasibility.unmatched_slots[0].role is DraftRole.SUPPORT
    assert options.pick_version == 4
    assert options.options[0].is_safe is False


def test_role_edit_contract_requires_reason_and_explicit_missing_rank_confirmation() -> None:
    with pytest.raises(ValidationError):
        schemas.DraftRoleEditRequest(
            role="support",
            rank_value=None,
            rank_absence_confirmed=False,
            reason="  ",
            expected_version=2,
        )

    request = schemas.DraftRoleEditRequest(
        role="support",
        rank_value=None,
        rank_absence_confirmed=True,
        reason="Role was missing from registration",
        expected_version=2,
        preview_only=True,
    )
    assert request.role is DraftRole.SUPPORT
    assert request.preview_only is True


def test_seed_contract_supports_dry_run_and_optimistic_version() -> None:
    request = schemas.DraftSeedRequest(preview_only=True, expected_version=7)

    assert request.preview_only is True
    assert request.expected_version == 7

    diff = schemas.DraftSeedDiff(
        teams_before=3,
        teams_after=4,
        players_before=15,
        players_after=20,
        picks_before=12,
        picks_after=16,
        session_version_before=7,
        session_version_after=8,
    )
    assert diff.session_version_after == 8


def test_public_player_metadata_keeps_notes_strips_organizer_keys() -> None:
    public = board.public_additional_info(
        {
            "notes": "registration note shown to captains",
            "admin_notes": "organizer only",
            "audit_reason": "private reason",
            "pronouns": "they/them",
        }
    )

    assert public == {
        "notes": "registration note shown to captains",
        "pronouns": "they/them",
    }


def test_pick_event_payload_contains_resolved_role_rank_and_version() -> None:
    draft = DraftSession(id=1, tournament_id=2, workspace_id=3, current_pick_id=31)
    pick = DraftPick(
        id=30,
        session_id=1,
        overall_no=5,
        round_no=2,
        pick_in_round=1,
        draft_team_id=10,
        picked_player_id=20,
        target_role=DraftRole.SUPPORT.value,
        target_rank_value=2875,
        status=DraftPickStatus.COMPLETED.value,
        version=4,
    )

    payload = draft_rpc._pick_event_payload(draft, pick)

    assert payload["target_role"] == "support"
    assert payload["target_rank_value"] == 2875
    assert payload["pick_version"] == 4


def test_role_edit_result_serializes_before_and_after_feasibility() -> None:
    response = schemas.DraftRoleEditResponse(
        player_id=20,
        role="support",
        player_version=3,
        committed=False,
        before={
            "is_feasible": False,
            "total_open_slots": 1,
            "matched_slots": 0,
            "unmatched_slots": [{"team_id": 10, "role": "support", "ordinal": 0}],
            "role_deficits": [{"role": "support", "unmatched_slots": 1, "eligible_players": 0}],
            "blocking_player_ids": [],
            "reason_code": "role_shortage",
        },
        after={
            "is_feasible": True,
            "total_open_slots": 1,
            "matched_slots": 1,
            "unmatched_slots": [],
            "role_deficits": [],
            "blocking_player_ids": [],
            "reason_code": None,
        },
    )

    assert response.before.is_feasible is False
    assert response.after.is_feasible is True


def test_rpc_registers_feasibility_options_and_role_edit_subjects() -> None:
    broker = _FakeBroker()

    draft_rpc.register(broker, _FakeLogger())

    assert {
        "rpc.balancer.draft.feasibility",
        "rpc.balancer.draft.pick_options",
        "rpc.balancer.draft.player_role_edit",
    } <= broker.subjects


def test_player_updated_event_does_not_expose_private_reason() -> None:
    payload = draft_rpc._player_updated_payload(
        session_id=1,
        player_id=20,
        role=DraftRole.SUPPORT,
        player_version=3,
        is_feasible=True,
    )

    assert payload == {
        "session_id": 1,
        "player_id": 20,
        "role": "support",
        "player_version": 3,
        "is_feasible": True,
    }


def test_admin_override_builds_private_audit_event() -> None:
    event = draft_rpc._override_audit_event(
        session_id=7,
        pick_id=9,
        actor_auth_user_id=11,
        reason=" Captain disconnected ",
        before={"player_id": None, "role": None},
        after={"player_id": 22, "role": "support"},
    )

    assert event.session_id == 7
    assert event.entity_id == 9
    assert event.actor_auth_user_id == 11
    assert event.reason == "Captain disconnected"
    assert event.before_json == {"player_id": None, "role": None}
    assert event.after_json == {"player_id": 22, "role": "support"}


def test_openapi_maps_all_new_draft_contracts() -> None:
    expected = {
        "rpc.balancer.draft.feasibility": (None, schemas.DraftFeasibilityResponse),
        "rpc.balancer.draft.pick_options": (None, schemas.DraftPickOptionsResponse),
        "rpc.balancer.draft.player_role_edit": (schemas.DraftRoleEditRequest, schemas.DraftRoleEditResponse),
    }

    for subject, (request, response) in expected.items():
        operation = openapi_schemas.OPERATIONS[subject]
        assert operation.request is request
        assert operation.response is response
        assert subject in openapi_docs.DOCS

    assert openapi_schemas.OPERATIONS["rpc.balancer.draft.seed"].response is schemas.DraftSeedResponse


def test_seed_version_guard_rejects_stale_preview_and_bumps_on_materialization() -> None:
    draft = DraftSession(id=1, tournament_id=2, workspace_id=3, version=7)

    lifecycle.validate_seed_version(draft, expected_version=7)
    lifecycle.bump_seed_version(draft)

    assert draft.version == 8
    with pytest.raises(Exception) as exc_info:
        lifecycle.validate_seed_version(draft, expected_version=7)
    assert exc_info.value.detail[0]["code"] == "draft_session_stale"


def test_seed_diff_builder_reports_before_and_after_counts() -> None:
    diff = draft_rpc._seed_diff(
        before=(3, 15, 12),
        after=(4, 20, 16),
        version_before=7,
        version_after=8,
    )

    assert diff == schemas.DraftSeedDiff(
        teams_before=3,
        teams_after=4,
        players_before=15,
        players_after=20,
        picks_before=12,
        picks_after=16,
        session_version_before=7,
        session_version_after=8,
    )
