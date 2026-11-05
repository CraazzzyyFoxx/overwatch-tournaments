"""Self-withdrawal is final once a participant has checked in.

Check-in is what turns the registration list into an attendee list, and the
balancer/draft are run against it. A participant dropping themselves after that
silently invalidates a composed roster, so ``reg_service.registration_service.withdraw_registration``
(the public ``DELETE /registration/me`` path) refuses with 409. The admin path
(``lifecycle.withdraw_registration``) is deliberately NOT gated -- organizers
own that call.

Runs under stdlib unittest -- no pytest-asyncio in this repo.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared import models  # noqa: E402
from shared.core.errors import BaseAPIException as HTTPException  # noqa: E402
from src.services.registration import service as reg_service  # noqa: E402


class _RecordingSession:
    """Stands in for the AsyncSession: only ``info`` and ``commit`` are touched
    on the happy path (``register_tournament_realtime_update`` stashes into
    ``info``)."""

    def __init__(self) -> None:
        self.info: dict = {}
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


def _entry(*, checked_in: bool) -> models.RegistrationEntry:
    return models.RegistrationEntry(
        id=1,
        registration_node_id=3,
        registration=models.Registration(id=1, tournament_id=7),
        status="approved",
        checked_in=checked_in,
    )


class TestPublicWithdrawGuard(IsolatedAsyncioTestCase):
    async def test_checked_in_registration_cannot_be_withdrawn(self) -> None:
        entry = _entry(checked_in=True)
        session = _RecordingSession()

        with self.assertRaises(HTTPException) as caught:
            await reg_service.registration_service.withdraw_registration(session, entry)

        assert caught.exception.status_code == 409
        # The refusal must leave the row alone: a half-applied withdrawal would
        # be worse than either outcome.
        assert entry.status == "approved"
        assert session.commits == 0

    async def test_approved_registration_without_check_in_still_withdraws(self) -> None:
        entry = _entry(checked_in=False)
        session = _RecordingSession()

        await reg_service.registration_service.withdraw_registration(session, entry)

        assert entry.status == "withdrawn"
        assert session.commits == 1
