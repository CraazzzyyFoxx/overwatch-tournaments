"""The batched lifecycle fan-out: ``on_encounters_changed`` and ``notify_users``.

Same in-memory SQLite fixture as ``test_lifecycle_notifications.py``; asserted
on the rows written, plus one statement count -- the point of the batch is that
the reads do not grow with the number of encounters.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from shared.core import enums
from shared.models.platform.outbox import EventOutbox
from shared.services.notifications import PersonalNotification, notify_users
from src.services.notifications.lifecycle import lifecycle_notifier
from tests.test_lifecycle_notifications import TOURNAMENT_ID, WORKSPACE_ID, _LifecycleTestCase

_CHECK_IN = {"tournament_id": TOURNAMENT_ID, "tournament_name": "Autumn Cup"}


class BatchedEncounterScheduledTests(_LifecycleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.teams = [
            self.fx.team(f"T{index}", self.fx.member(f"P{index}", auth_user_id=800 + index)) for index in range(6)
        ]
        self.later = datetime.now(UTC) + timedelta(days=1)

    def _team(self, index: int) -> int:
        return self.teams[index].id

    async def test_each_announceable_encounter_reaches_both_rosters_once(self) -> None:
        preview_stage = self.fx.stage()
        timed = self.fx.encounter(teams=[self._team(0), self._team(1)], scheduled_at=self.later)
        untimed = self.fx.encounter(teams=[self._team(2), self._team(3)], scheduled_at=None)
        preview = self.fx.encounter(teams=[self._team(4), self._team(5)], scheduled_at=None, stage_id=preview_stage.id)
        half_seated = self.fx.encounter(teams=[self._team(4), None], scheduled_at=None)
        played = self.fx.encounter(
            teams=[self._team(4), self._team(5)],
            scheduled_at=None,
            status=enums.EncounterStatus.COMPLETED,
        )

        await lifecycle_notifier.on_encounters_changed(self.fx.shim, [timed, untimed, preview, half_seated, played])

        rows = self.fx.notifications("encounter.scheduled")
        self.assertEqual([800, 801, 802, 803], self.fx.recipients("encounter.scheduled"))
        by_encounter = {row.payload_json["encounter_id"]: row.payload_json for row in rows}
        self.assertEqual({timed.id, untimed.id}, set(by_encounter))
        self.assertEqual(["T0", "T1"], by_encounter[timed.id]["team_names"])
        self.assertNotIn("scheduled_at", by_encounter[untimed.id])
        self.assertTrue(all(row.source_workspace_id == WORKSPACE_ID for row in rows))
        # Bulk default: personal rows only, no channel posts.
        self.assertEqual([], self.fx.broadcasts())

    async def test_a_repeated_batch_writes_nothing_new(self) -> None:
        encounters = [
            self.fx.encounter(teams=[self._team(0), self._team(1)], scheduled_at=self.later),
            self.fx.encounter(teams=[self._team(2), self._team(3)], scheduled_at=self.later),
        ]

        await lifecycle_notifier.on_encounters_changed(self.fx.shim, encounters)
        await lifecycle_notifier.on_encounters_changed(self.fx.shim, encounters)

        self.assertEqual(4, len(self.fx.notifications("encounter.scheduled")))

    async def test_channel_posts_once_per_announced_encounter(self) -> None:
        encounters = [
            self.fx.encounter(teams=[self._team(0), self._team(1)], scheduled_at=self.later),
            self.fx.encounter(teams=[self._team(2), None], scheduled_at=self.later),
        ]

        await lifecycle_notifier.on_encounters_changed(self.fx.shim, encounters, channel=True)

        self.assertEqual(1, len(self.fx.broadcasts()))

    async def test_reads_do_not_grow_with_the_batch(self) -> None:
        one = [self.fx.encounter(teams=[self._team(0), self._team(1)], scheduled_at=self.later)]
        three = [
            self.fx.encounter(teams=[self._team(2), self._team(3)], scheduled_at=self.later),
            self.fx.encounter(teams=[self._team(4), self._team(5)], scheduled_at=self.later),
            self.fx.encounter(teams=[self._team(0), self._team(5)], scheduled_at=self.later),
        ]

        selects: list[str] = []

        def count(conn, cursor, statement, *args) -> None:  # noqa: ANN001, ANN002
            if statement.lstrip().upper().startswith("SELECT"):
                selects.append(statement)

        sa.event.listen(self.fx.engine, "before_cursor_execute", count)
        self.addCleanup(sa.event.remove, self.fx.engine, "before_cursor_execute", count)

        await lifecycle_notifier.on_encounters_changed(self.fx.shim, one)
        for_one = len(selects)
        selects.clear()
        await lifecycle_notifier.on_encounters_changed(self.fx.shim, three)

        self.assertEqual(for_one, len(selects))
        self.assertEqual(8, len(self.fx.notifications("encounter.scheduled")))


class NotifyUsersTests(_LifecycleTestCase):
    async def test_a_repeat_inside_the_batch_and_an_existing_row_are_both_skipped(self) -> None:
        def row(recipient: int) -> PersonalNotification:
            return PersonalNotification(recipient, dict(_CHECK_IN), "tournament:10", WORKSPACE_ID)

        await notify_users(self.fx.shim, kind="check_in.opened", notifications=[row(601)])

        written = await notify_users(
            self.fx.shim,
            kind="check_in.opened",
            notifications=[row(601), row(602), row(602), row(603)],
        )

        self.assertEqual([602, 603], [item.recipient_auth_user_id for item in written])
        self.assertEqual([601, 602, 603], self.fx.recipients("check_in.opened"))

    async def test_every_written_row_gets_its_delivery_event(self) -> None:
        written = await notify_users(
            self.fx.shim,
            kind="check_in.opened",
            notifications=[PersonalNotification(recipient, dict(_CHECK_IN)) for recipient in (701, 702)],
        )

        delivered = self.fx.session.scalars(
            sa.select(EventOutbox).where(EventOutbox.routing_key == "notification.created")
        ).all()
        self.assertEqual(
            sorted(row.id for row in written),
            sorted(event.payload_json["notification_id"] for event in delivered),
        )
