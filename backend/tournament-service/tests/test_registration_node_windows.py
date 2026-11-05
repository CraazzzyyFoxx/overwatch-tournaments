"""Sign-up and check-in windows per registration node (plan Decision 10) and the node-named announcements."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import sqlalchemy as sa

from shared import models
from shared.core.enums import FlowNodeStatus
from shared.core.errors import ApiHTTPException
from shared.core.errors import BaseAPIException as HTTPException
from shared.domain.forms import FormField, FormSchema, FormSection
from shared.services.ontology import project_disciplines
from shared.services.registration_window import is_check_in_open, is_sign_up_late, is_sign_up_open
from src.schemas.registration import RegistrationSubmit
from src.services.flow.lifecycle import flow_node_service
from src.services.notifications.lifecycle import lifecycle_notifier
from src.services.registration.service import registration_service
from tests._flow_case import FlowCase

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
HOUR = timedelta(hours=1)


def _row(phase: str, starts_at: datetime, ends_at: datetime | None = None) -> SimpleNamespace:
    return SimpleNamespace(phase=phase, starts_at=starts_at, ends_at=ends_at)


class PredicateTests(unittest.TestCase):
    def test_sign_up_open_needs_open_status(self) -> None:
        self.assertFalse(is_sign_up_open("draft", [], NOW, allow_late=False))
        self.assertFalse(is_sign_up_open("closed", [], NOW, allow_late=True))
        # A missing row means the status decides.
        self.assertTrue(is_sign_up_open("open", [], NOW, allow_late=False))

    def test_sign_up_window_bounds_inclusive(self) -> None:
        self.assertTrue(is_sign_up_open("open", [_row("open", NOW, NOW + HOUR)], NOW, allow_late=False))
        self.assertTrue(is_sign_up_open("open", [_row("open", NOW - HOUR, NOW)], NOW, allow_late=False))
        self.assertFalse(is_sign_up_open("open", [_row("open", NOW - 2 * HOUR, NOW - HOUR)], NOW, allow_late=False))
        self.assertFalse(is_sign_up_open("open", [_row("open", NOW + HOUR)], NOW, allow_late=False))
        # Only the ``open`` row counts.
        self.assertTrue(is_sign_up_open("open", [_row("check_in", NOW + HOUR)], NOW, allow_late=False))

    def test_allow_late_lifts_only_ends_at(self) -> None:
        self.assertTrue(is_sign_up_open("open", [_row("open", NOW - 2 * HOUR, NOW - HOUR)], NOW, allow_late=True))
        self.assertFalse(is_sign_up_open("open", [_row("open", NOW + HOUR)], NOW, allow_late=True))

    def test_check_in_status_signs_up_only_with_allow_late(self) -> None:
        self.assertFalse(is_sign_up_open("check_in", [], NOW, allow_late=False))
        self.assertTrue(is_sign_up_open("check_in", [], NOW, allow_late=True))

    def test_sign_up_late_when_check_in_or_past_end(self) -> None:
        self.assertTrue(is_sign_up_late("check_in", [], NOW))
        self.assertTrue(is_sign_up_late("open", [_row("open", NOW - 2 * HOUR, NOW - HOUR)], NOW))
        self.assertFalse(is_sign_up_late("open", [_row("open", NOW - HOUR, NOW + HOUR)], NOW))
        self.assertFalse(is_sign_up_late("open", [_row("open", NOW - HOUR)], NOW))
        self.assertFalse(is_sign_up_late("open", [], NOW))
        self.assertFalse(is_sign_up_late("draft", [_row("open", NOW - 2 * HOUR, NOW - HOUR)], NOW))

    def test_check_in_open_needs_check_in_status_and_window(self) -> None:
        self.assertFalse(is_check_in_open("open", [], NOW))
        self.assertTrue(is_check_in_open("check_in", [], NOW))
        self.assertTrue(is_check_in_open("check_in", [_row("check_in", NOW - HOUR, NOW)], NOW))
        self.assertFalse(is_check_in_open("check_in", [_row("check_in", NOW - 2 * HOUR, NOW - HOUR)], NOW))
        self.assertFalse(is_check_in_open("check_in", [_row("check_in", NOW + HOUR)], NOW))


_SCHEMA = FormSchema(
    sections=[FormSection(key="accounts", fields=[FormField(key="identity_battlenet", kind="builtin", required=True)])]
)


class NodeWindowTests(FlowCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        async with self.Session() as s:
            await project_disciplines(s)
            form = await s.scalar(
                sa.select(models.RegistrationForm).where(models.RegistrationForm.tournament_id == self.tournament_id)
            )
            version = models.RegistrationFormVersion(
                form_id=form.id, number=1, schema_json=_SCHEMA.model_dump(mode="json")
            )
            form.current_version = version
            await s.flush()
            self.version_id = version.id
            self.user = models.AuthUser(
                email=f"{self.tag}-u@example.test", username=f"{self.tag}_u", hashed_password="x"
            )
            s.add(self.user)
            await s.commit()
        self.addAsyncCleanup(self._drop)

    async def _drop(self) -> None:
        async with self.Session() as s:
            await s.execute(sa.delete(models.User).where(models.User.auth_user_id == self.user.id))
            await s.execute(sa.delete(models.AuthUser).where(models.AuthUser.id == self.user.id))
            await s.execute(
                sa.delete(models.Notification).where(models.Notification.source_workspace_id == self.workspace_id)
            )
            await s.execute(sa.delete(models.Notification).where(models.Notification.workspace_id == self.workspace_id))
            await s.commit()

    async def _sign_up(self, node_id: int) -> models.RegistrationEntry:
        async with self.Session() as s:
            return await registration_service.write_public_registration(
                s,
                tournament_id=self.tournament_id,
                auth_user=self.user,
                body=RegistrationSubmit(
                    form_version_id=self.version_id, answers={"identity_battlenet": [f"W{self.tag[-6:]}#1234"]}
                ),
                registration_node_id=node_id,
            )

    async def test_two_nodes_independent_windows(self) -> None:
        a = await self.node("registration", "open", name="Day 1")
        b = await self.node("registration", "draft", name="Day 2")
        entry = await self._sign_up(a)
        self.assertEqual(a, entry.registration_node_id)
        with self.assertRaises(HTTPException) as refused:
            await self._sign_up(b)
        self.assertEqual(400, refused.exception.status_code)

    async def test_auto_approve_read_from_node_config(self) -> None:
        a = await self.node("registration", "open", name="Day 1", config={"auto_approve": True})
        b = await self.node("registration", "open", name="Day 2")
        self.assertEqual("approved", (await self._sign_up(a)).status)
        self.assertEqual("pending", (await self._sign_up(b)).status)

    async def test_opening_without_a_form_is_refused(self) -> None:
        node = await self.node("registration", "draft")
        async with self.Session() as s:
            await s.execute(
                sa.delete(models.RegistrationForm).where(models.RegistrationForm.tournament_id == self.tournament_id)
            )
            await s.commit()
        async with self.Session() as s:
            with self.assertRaises(ApiHTTPException) as caught:
                await flow_node_service.transition(s, node, FlowNodeStatus.OPEN, actor=self.actor)
        self.assertEqual(409, caught.exception.status_code)
        self.assertEqual("registration_form_missing", caught.exception.detail[0]["code"])
        self.assertEqual("draft", await self.node_status(node))

    async def test_registration_opened_notification_names_the_node(self) -> None:
        node = await self.node("registration", "draft", name="Day 3")
        async with self.Session() as s:
            await flow_node_service.transition(s, node, FlowNodeStatus.OPEN, actor=self.actor)
            await s.commit()
        async with self.Session() as s:
            rows = list(
                await s.scalars(
                    sa.select(models.Notification).where(
                        models.Notification.kind == "registration.opened",
                        models.Notification.workspace_id == self.workspace_id,
                    )
                )
            )
        self.assertEqual(1, len(rows))
        self.assertEqual("Day 3", rows[0].payload_json["node_name"])
        self.assertEqual(node, rows[0].payload_json["registration_node_id"])
        self.assertEqual(f"flow_node:{node}", rows[0].dedupe_key)

    async def _check_in_notifications(self, node_id: int) -> list[models.Notification]:
        async with self.Session() as s:
            tournament = await s.get(models.Tournament, self.tournament_id)
            await lifecycle_notifier.on_node_entered(s, tournament, await s.get(models.FlowNode, node_id))
            await s.commit()
        async with self.Session() as s:
            rows = await s.scalars(
                sa.select(models.Notification).where(
                    models.Notification.kind == "check_in.opened",
                    models.Notification.recipient_auth_user_id == self.user.id,
                )
            )
            return list(rows)

    async def test_check_in_notification_goes_to_pending_entries_of_the_node(self) -> None:
        node = await self.node("registration", "check_in", name="Day 3")
        other = await self.node("registration", "open", name="Day 4")
        await self._approved_entry(other)
        self.assertEqual([], await self._check_in_notifications(node))
        await self._approved_entry(node)
        rows = await self._check_in_notifications(node)
        self.assertEqual(1, len(rows))
        self.assertEqual("Day 3", rows[0].payload_json["node_name"])
        self.assertEqual(node, rows[0].payload_json["registration_node_id"])

    async def _approved_entry(self, node_id: int) -> None:
        async with self.Session() as s:
            member = await s.scalar(
                sa.select(models.WorkspaceMember)
                .join(models.User, models.User.id == models.WorkspaceMember.player_id)
                .where(
                    models.User.auth_user_id == self.user.id, models.WorkspaceMember.workspace_id == self.workspace_id
                )
            )
            if member is None:
                player = models.User(name=self.tag, auth_user_id=self.user.id)
                s.add(player)
                await s.flush()
                member = models.WorkspaceMember(workspace_id=self.workspace_id, player_id=player.id)
                s.add(member)
                await s.flush()
            registration = await s.scalar(
                sa.select(models.Registration).where(
                    models.Registration.tournament_id == self.tournament_id,
                    models.Registration.workspace_member_id == member.id,
                )
            )
            if registration is None:
                registration = models.Registration(tournament_id=self.tournament_id, workspace_member_id=member.id)
                s.add(registration)
                await s.flush()
            s.add(
                models.RegistrationEntry(
                    registration_node_id=node_id, registration_id=registration.id, status="approved"
                )
            )
            await s.commit()
