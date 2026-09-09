"""Opening REGISTRATION requires a saved registration form.

The status is what the public page announces and what the register button reads,
so entering REGISTRATION without a form advertises a sign-up nobody can complete
— the mismatch the ANNOUNCEMENT phase exists to end. ``force`` is the documented
escape hatch (superuser-only at the RPC layer) for a tournament that genuinely
takes no registrations of its own, e.g. a Challonge-sourced bracket.

No database: the guard is a decision about two repository answers, and both are
faked here. The worker tick's half of the same prerequisite — skip, do not raise
— lives in ``test_auto_transitions.py``.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

os.environ.setdefault("DEBUG", "true")

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

from shared.core.enums import TournamentStatus  # noqa: E402
from shared.core.errors import BaseAPIException  # noqa: E402
from src.services.admin.tournament import tournament_service  # noqa: E402


def _tournament() -> SimpleNamespace:
    return SimpleNamespace(
        id=7,
        status=TournamentStatus.ANNOUNCEMENT,
        is_finished=False,
        auto_transitions_enabled=True,
        stages=[],
    )


def _transition(*, has_form: bool, force: bool = False):
    """Run ``transition_status`` toward REGISTRATION with both repos faked.

    Everything downstream of the guard (outbox, commit, re-read) is patched, so a
    call that returns instead of raising proves the guard let it through.
    """
    tournament = _tournament()
    session = SimpleNamespace(commit=AsyncMock())
    with (
        patch.object(tournament_service.tournament_repo, "get", AsyncMock(return_value=tournament)),
        patch.object(
            tournament_service.registration_form_repo,
            "get_by_tournament",
            AsyncMock(return_value=SimpleNamespace(id=1) if has_form else None),
        ),
        patch("src.services.admin.tournament.enqueue_tournament_state_changed", AsyncMock()),
        patch("src.services.admin.tournament.publish_tournament_invalidation", AsyncMock()),
        patch.object(tournament_service, "_maybe_auto_start_group_stage", AsyncMock()),
        patch.object(tournament_service, "get_tournament", AsyncMock(return_value=tournament)),
    ):
        asyncio.run(
            tournament_service.transition_status(
                session,
                tournament.id,
                TournamentStatus.REGISTRATION,
                force=force,
            )
        )
    return tournament


def test_registration_is_refused_without_a_form() -> None:
    with pytest.raises(BaseAPIException) as excinfo:
        _transition(has_form=False)

    assert excinfo.value.status_code == 409
    # A list of `{code, msg}` dicts — the shape the frontend's `parseApiError` reads.
    assert [detail["code"] for detail in excinfo.value.detail] == ["registration_form_missing"]


def test_the_status_is_left_untouched_when_the_guard_refuses() -> None:
    """The guard runs before the write, so a refused call changes nothing."""
    tournament = _tournament()
    session = SimpleNamespace(commit=AsyncMock())
    with (
        patch.object(tournament_service.tournament_repo, "get", AsyncMock(return_value=tournament)),
        patch.object(tournament_service.registration_form_repo, "get_by_tournament", AsyncMock(return_value=None)),
    ):
        with pytest.raises(BaseAPIException):
            asyncio.run(tournament_service.transition_status(session, tournament.id, TournamentStatus.REGISTRATION))

    assert tournament.status is TournamentStatus.ANNOUNCEMENT
    session.commit.assert_not_awaited()


def test_a_saved_form_opens_the_gate() -> None:
    assert _transition(has_form=True).status is TournamentStatus.REGISTRATION


def test_force_opens_it_for_a_tournament_that_takes_no_registrations() -> None:
    assert _transition(has_form=False, force=True).status is TournamentStatus.REGISTRATION


def test_a_tournament_cannot_be_created_with_registration_already_open() -> None:
    """No ``force`` here on purpose: the form belongs to a tournament that does
    not exist yet, so this is never a legitimate request."""
    from src import schemas

    payload = schemas.TournamentCreate(
        workspace_id=1,
        name="Cup",
        start_date="2026-01-01",
        end_date="2026-01-02",
        status=TournamentStatus.REGISTRATION,
    )
    with pytest.raises(BaseAPIException) as excinfo:
        asyncio.run(tournament_service.create_tournament(SimpleNamespace(), payload))

    assert excinfo.value.status_code == 409
    assert [detail["code"] for detail in excinfo.value.detail] == ["registration_form_missing"]
