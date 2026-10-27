"""The Challonge push consumer: only the encounter's current result version reaches Challonge; retry or DLQ by cause."""

from __future__ import annotations

from unittest.mock import ANY, AsyncMock, patch

from shared.core.errors import ApiExc, ApiHTTPException
from shared.schemas.events import ChallongePushRequestedEvent
from shared.tests.encounter_writer_case import EncounterWriterCase
from src.services.encounter import challonge_push_events


class ChallongePushConsumerTests(EncounterWriterCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        async with self.Session() as s:
            # Reopened and re-confirmed since version 2 was requested: 3 is the result that stands.
            (await self.encounter(s)).result_version = 3
            await s.commit()

    async def consume(self, version: int, push: AsyncMock) -> str | None:
        """One delivery of a request for ``version`` of the (Challonge-linked) seeded encounter."""
        request = ChallongePushRequestedEvent(
            tournament_id=self.ids["t"], encounter_id=self.ids["e"], result_version=version, source_service="test"
        )
        with (
            patch.object(challonge_push_events.db, "async_session_maker", self.Session),
            patch.object(
                challonge_push_events,
                "resolve_encounter_challonge",
                AsyncMock(side_effect=lambda _s, ids: dict.fromkeys(ids, 1)),
            ),
            patch.object(challonge_push_events.sync_service, "auto_push_on_confirm", push),
        ):
            return await challonge_push_events.process_challonge_push(request.model_dump(mode="json"))

    async def test_a_superseded_version_is_acked_without_a_push(self) -> None:
        push = AsyncMock()
        self.assertEqual(challonge_push_events.STALE, await self.consume(2, push))
        push.assert_not_awaited()
        self.assertEqual(challonge_push_events.PUSHED, await self.consume(3, push))
        push.assert_awaited_once_with(ANY, self.ids["e"])

    async def test_an_unavailable_challonge_is_retried_and_a_refusal_dead_letters(self) -> None:
        def refused(status: int) -> ApiHTTPException:
            return ApiHTTPException(status_code=status, detail=[ApiExc(code="challonge", msg="no")])

        # A transport failure reaches here as the client's 503 too.
        self.assertIsNone(await self.consume(3, AsyncMock(side_effect=refused(503))))
        with self.assertRaises(ApiHTTPException):
            await self.consume(3, AsyncMock(side_effect=refused(400)))
