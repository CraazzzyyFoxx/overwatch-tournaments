"""Approving a batch writes, per registration, exactly what approving them one at a time writes -- and its
lookups (tournament, players, accounts) stay constant in the batch size."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from uuid import uuid4

for root in (Path(__file__).resolve().parents[1], Path(__file__).resolve().parents[2]):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

import sqlalchemy as sa  # noqa: E402
from sqlalchemy import event  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from shared import models  # noqa: E402
from shared.core.social import normalize_social_handle  # noqa: E402
from shared.models.platform.notification import Notification  # noqa: E402
from shared.services.realtime import Scope  # noqa: E402
from shared.testing import create_test_async_engine  # noqa: E402
from src.services.tournament import events  # noqa: E402

#: Fresh per write (a uuid and a clock), so not part of "the same row".
_VOLATILE = {"event_id", "timestamp"}


class RegistrationBulkApprovalEventsTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    async def asyncSetUp(self):
        self.engine = create_test_async_engine()
        self.session = AsyncSession(self.engine, expire_on_commit=False)
        tag = uuid4().hex
        self.workspace = models.Workspace(slug=f"bulk-{tag}", name="Bulk approval", disciplines_enabled=["overwatch"])
        self.session.add(self.workspace)
        await self.session.flush()
        self.tournament = models.Tournament(
            workspace_id=self.workspace.id, discipline="overwatch", name="Bulk Cup", slug=f"bulk-{tag}"
        )
        self.session.add(self.tournament)
        await self.session.flush()
        self.outbox_floor = await self.session.scalar(
            sa.select(sa.func.coalesce(sa.func.max(models.EventOutbox.id), 0))
        )

        self.auth_ids: list[int] = []
        member_ids = [await self._member(f"{tag}-{index}", account=True) for index in range(3)]
        # A shadow player (no site account) and a registration with no member at all.
        member_ids += [await self._member(f"{tag}-shadow", account=False), None]
        self.registrations = [
            models.Registration(
                tournament_id=self.tournament.id,
                workspace_member_id=member_id,
                status="approved",
                identities=[
                    models.RegistrationIdentity(
                        provider="battlenet",
                        position=0,
                        handle=f"Player{index}#1234",
                        handle_normalized=normalize_social_handle("battlenet", f"Player{index}#1234"),
                    )
                ],
            )
            for index, member_id in enumerate(member_ids)
        ]
        self.session.add_all(self.registrations)
        await self.session.flush()

    async def asyncTearDown(self):
        await self.session.rollback()
        await self.session.close()
        await self.engine.dispose()

    async def _member(self, tag: str, *, account: bool) -> int:
        auth_user_id = None
        if account:
            auth = models.AuthUser(email=f"{tag}@example.test", username=tag)
            self.session.add(auth)
            await self.session.flush()
            auth_user_id = auth.id
            self.auth_ids.append(auth_user_id)
        player = models.User(name=tag, auth_user_id=auth_user_id)
        self.session.add(player)
        await self.session.flush()
        member = models.WorkspaceMember(workspace_id=self.workspace.id, player_id=player.id)
        self.session.add(member)
        await self.session.flush()
        return member.id

    async def _written(self) -> tuple[list, list, tuple]:
        """This transaction's inbox rows, outbox rows and staged page invalidation, minus per-write noise.

        A notification-created event names its row by position, since the two runs write different ids. Outbox
        rows are grouped by routing key: one approval at a time interleaves the two kinds, a batch does not.
        """
        notifications = list(
            await self.session.scalars(
                sa.select(Notification)
                .where(Notification.recipient_auth_user_id.in_(self.auth_ids))
                .order_by(Notification.id)
            )
        )
        position = {row.id: index for index, row in enumerate(notifications)}
        registration_ids = {registration.id for registration in self.registrations}
        outbox = []
        for row in await self.session.scalars(
            sa.select(models.EventOutbox)
            .where(models.EventOutbox.id > self.outbox_floor)
            .order_by(models.EventOutbox.id)
        ):
            payload = {key: value for key, value in row.payload_json.items() if key not in _VOLATILE}
            if payload.get("registration_id") in registration_ids or payload.get("notification_id") in position:
                if "notification_id" in payload:
                    payload["notification_id"] = position[payload["notification_id"]]
                outbox.append((row.event_type, row.exchange, row.routing_key, payload))
        resources, entity_ids = self.session.sync_session.info["realtime_staged"].invalidations[
            Scope.tournament(self.tournament.id)
        ]
        return (
            [
                (n.kind, n.audience, n.recipient_auth_user_id, n.workspace_id, n.source_workspace_id, n.payload_json)
                for n in notifications
            ],
            sorted(outbox, key=lambda row: row[2]),
            (set(resources), {key: list(ids) for key, ids in entity_ids.items()}),
        )

    async def test_a_batch_writes_what_one_approval_at_a_time_writes(self):
        savepoint = await self.session.begin_nested()
        for registration in self.registrations:
            await events.enqueue_registration_approved(self.session, registration)
        one_at_a_time = await self._written()
        await savepoint.rollback()

        await events.enqueue_registrations_approved(self.session, self.registrations)
        batched = await self._written()

        self.assertEqual(one_at_a_time, batched)
        notifications, outbox, (_resources, entity_ids) = batched
        # Only the three account holders have an inbox; every registration gets its event.
        self.assertEqual(self.auth_ids, [row[2] for row in notifications])
        approvals = [payload for *_, payload in outbox if "registration_id" in payload]
        self.assertEqual([r.id for r in self.registrations], [payload["registration_id"] for payload in approvals])
        self.assertEqual(3, len(outbox) - len(approvals))
        self.assertIsNotNone(approvals[3]["user_id"])  # the shadow player is still a player
        self.assertIsNone(approvals[4]["user_id"])  # no member, no player
        self.assertEqual({"registration_ids": [r.id for r in self.registrations]}, entity_ids)

    async def test_the_statements_do_not_grow_with_the_batch(self):
        statements: list[object] = []

        def record(_conn, clauseelement, *_args) -> None:  # noqa: ANN001
            statements.append(clauseelement)

        event.listen(self.engine.sync_engine, "before_execute", record)
        self.addCleanup(event.remove, self.engine.sync_engine, "before_execute", record)

        counts = []
        for batch in (self.registrations[:1], self.registrations[1:]):
            statements.clear()
            await events.enqueue_registrations_approved(self.session, batch)
            counts.append(len(statements))

        # One registration or four: a tournament read, a member/account read, and one INSERT each for the
        # approval events, the inbox rows and their delivery events.
        self.assertEqual([5, 5], counts)
