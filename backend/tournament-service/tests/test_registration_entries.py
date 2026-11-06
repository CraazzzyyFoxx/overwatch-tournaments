"""Participation per registration node: one profile, one entry per intake (spec §4.5, plan Review Focus 1)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from shared import models
from shared.core.errors import ApiHTTPException
from shared.core.errors import BaseAPIException as HTTPException
from shared.domain.forms import FormField, FormSchema, FormSection
from shared.services.division_grid import cache as division_grid_cache
from shared.services.ontology import project_disciplines
from src.schemas.registration import RegistrationSubmit
from src.services.admin.tournament import tournament_service
from src.services.flow.engine import flow_engine
from src.services.registration import sheet_sync
from src.services.registration.lifecycle import lifecycle_service
from src.services.registration.service import TeamPlacement, registration_service
from src.services.registration.teams import teams_service
from tests._flow_case import FlowCase

_SCHEMA = FormSchema(
    sections=[
        FormSection(
            key="accounts",
            fields=[
                FormField(key="identity_battlenet", kind="builtin", required=True),
                FormField(key="public_notes", kind="builtin"),
            ],
        )
    ]
)


class EntryTests(FlowCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await self._seed_discipline()
        self.a = await self.node("registration", "open", name="Day 1")
        self.b = await self.node("registration", "open", name="Day 2")
        async with self.Session() as s:
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
        self.addAsyncCleanup(self._drop_accounts)

    async def _seed_discipline(self) -> None:
        async with self.Session() as s:
            await project_disciplines(s)
            await s.commit()

    async def _drop_accounts(self) -> None:
        async with self.Session() as s:
            await s.execute(sa.delete(models.User).where(models.User.auth_user_id.in_(self._account_ids)))
            await s.execute(sa.delete(models.AuthUser).where(models.AuthUser.id.in_(self._account_ids)))
            await s.commit()

    @property
    def _account_ids(self) -> list[int]:
        return [self.user.id, *getattr(self, "_extra_accounts", [])]

    def _submit(self) -> RegistrationSubmit:
        return RegistrationSubmit(
            form_version_id=self.version_id, answers={"identity_battlenet": [f"E{self.tag[-6:]}#1234"]}
        )

    async def _sign_up(self, node_id: int) -> int:
        async with self.Session() as s:
            entry = await registration_service.write_public_registration(
                s,
                tournament_id=self.tournament_id,
                auth_user=self.user,
                body=self._submit(),
                registration_node_id=node_id,
            )
            return entry.registration_id

    async def _entries(self) -> dict[int, models.RegistrationEntry]:
        async with self.Session() as s:
            rows = await s.scalars(
                sa.select(models.RegistrationEntry)
                .join(models.Registration, models.Registration.id == models.RegistrationEntry.registration_id)
                .where(models.Registration.tournament_id == self.tournament_id)
            )
            return {row.registration_node_id: row for row in rows}

    async def _member(self, index: int) -> tuple[int, int]:
        """A workspace member with an account: ``(workspace_member_id, auth_user_id)``."""
        async with self.Session() as s:
            account = models.AuthUser(
                email=f"{self.tag}-m{index}@example.test", username=f"{self.tag}_m{index}", hashed_password="x"
            )
            s.add(account)
            await s.flush()
            player = models.User(name=f"{self.tag}-m{index}", auth_user_id=account.id)
            s.add(player)
            await s.flush()
            member = models.WorkspaceMember(workspace_id=self.workspace_id, player_id=player.id)
            s.add(member)
            await s.commit()
        self._extra_accounts = [*getattr(self, "_extra_accounts", []), account.id]
        return member.id, account.id

    async def test_same_member_two_nodes_one_profile_two_entries(self) -> None:
        first = await self._sign_up(self.a)
        second = await self._sign_up(self.b)
        self.assertEqual(first, second)
        async with self.Session() as s:
            registrations = await s.scalar(
                sa.select(sa.func.count())
                .select_from(models.Registration)
                .where(models.Registration.tournament_id == self.tournament_id)
            )
        entries = await self._entries()
        self.assertEqual(1, registrations)
        self.assertEqual({self.a, self.b}, set(entries))
        self.assertEqual(["pending", "pending"], [entries[self.a].status, entries[self.b].status])

    async def test_same_member_two_nodes_approve_is_per_node(self) -> None:
        registration_id = await self._sign_up(self.a)
        await self._sign_up(self.b)
        async with self.Session() as s:
            await lifecycle_service.approve_registration(s, self.a, registration_id, reviewed_by=self.actor.id)
        entries = await self._entries()
        self.assertEqual("approved", entries[self.a].status)
        self.assertIsNotNone(entries[self.a].reviewed_at)
        self.assertEqual("pending", entries[self.b].status)
        self.assertIsNone(entries[self.b].reviewed_at)

    async def test_same_member_two_nodes_admin_list_is_per_node(self) -> None:
        registration_id = await self._sign_up(self.a)
        await self._sign_up(self.b)
        async with self.Session() as s:
            await lifecycle_service.approve_registration(s, self.a, registration_id, reviewed_by=self.actor.id)
        async with self.Session() as s:
            in_a = await lifecycle_service.list_registration_reads(
                s, registration_node_id=self.a, workspace_id=self.workspace_id
            )
            in_b = await lifecycle_service.list_registration_reads(
                s, registration_node_id=self.b, workspace_id=self.workspace_id
            )
        self.assertEqual([(self.a, "approved")], [(read.registration_node_id, read.status) for read in in_a])
        self.assertEqual([(self.b, "pending")], [(read.registration_node_id, read.status) for read in in_b])

    async def test_same_member_two_nodes_withdraw_is_per_node(self) -> None:
        await self._sign_up(self.a)
        await self._sign_up(self.b)
        async with self.Session() as s:
            entry = await registration_service.get_registration(s, self.b, self.user.id)
            await registration_service.withdraw_registration(s, entry)
        entries = await self._entries()
        self.assertEqual(["pending", "withdrawn"], [entries[self.a].status, entries[self.b].status])

    async def test_entry_unique_per_node(self) -> None:
        registration_id = await self._sign_up(self.a)
        async with self.Session() as s:
            s.add(models.RegistrationEntry(registration_node_id=self.a, registration_id=registration_id))
            with self.assertRaises(IntegrityError):
                await s.flush()
            await s.rollback()
        async with self.Session() as s:
            await s.execute(
                sa.update(models.RegistrationEntry)
                .where(models.RegistrationEntry.registration_node_id == self.a)
                .values(deleted_at=datetime.now(UTC))
            )
            s.add(models.RegistrationEntry(registration_node_id=self.a, registration_id=registration_id))
            await s.commit()

    async def test_check_in_is_per_node(self) -> None:
        registration_id = await self._sign_up(self.a)
        await self._sign_up(self.b)
        async with self.Session() as s:
            await lifecycle_service.check_in_registration(s, self.a, registration_id, checked_in_by=self.actor.id)
        entries = await self._entries()
        self.assertEqual((True, False), (entries[self.a].checked_in, entries[self.b].checked_in))
        self.assertIsNotNone(entries[self.a].checked_in_at)

    async def test_team_check_in_checks_in_every_member_entry_of_the_node(self) -> None:
        (m1, u1), (m2, _u2) = await self._member(1), await self._member(2)
        async with self.Session() as s:
            team = models.RegistrationTeam(
                tournament_id=self.tournament_id,
                registration_node_id=self.a,
                workspace_id=self.workspace_id,
                name="T",
                name_normalized="t",
                status="complete",
            )
            s.add(team)
            await s.flush()
            registrations = [
                models.Registration(
                    tournament_id=self.tournament_id, workspace_member_id=m, registration_team_id=team.id
                )
                for m in (m1, m2)
            ]
            s.add_all(registrations)
            await s.flush()
            team.captain_registration_id = registrations[0].id
            for registration in registrations:
                s.add(
                    models.RegistrationEntry(
                        registration_node_id=self.a, registration_id=registration.id, status="approved"
                    )
                )
            await s.execute(sa.update(models.FlowNode).where(models.FlowNode.id == self.a).values(status="check_in"))
            await s.commit()
            team_id = team.id
        async with self.Session() as s:
            captain = await s.get(models.AuthUser, u1)
            await teams_service.check_in_roster(s, team_id=team_id, auth_user=captain, registration_node_id=self.a)
        async with self.Session() as s:
            rows = (
                await s.execute(
                    sa.select(models.RegistrationEntry.registration_node_id, models.RegistrationEntry.checked_in)
                    .join(models.Registration, models.Registration.id == models.RegistrationEntry.registration_id)
                    .where(models.Registration.tournament_id == self.tournament_id)
                )
            ).all()
        self.assertEqual([(self.a, True), (self.a, True)], sorted(rows))

    async def test_sheet_sync_creates_entries_in_the_feed_node(self) -> None:
        mapping = {
            "targets": {
                "source_record_key": {"mode": "columns", "columns": ["BattleTag"], "parser": "battle_tag"},
                "identity_battlenet": {"mode": "columns", "columns": ["BattleTag"], "parser": "battle_tag_list"},
            }
        }
        async with self.Session() as s:
            s.add(
                models.RegistrationGoogleSheetFeed(
                    tournament_id=self.tournament_id,
                    registration_node_id=self.b,
                    source_url="http://sheet.example/entries",
                    sheet_id="sheet-entries",
                    mapping_config_json=mapping,
                )
            )
            await s.commit()

        async def _fetch(*_args, **_kwargs):
            return [["BattleTag"], [f"S{uuid.uuid4().hex[:8]}#4321"]]

        with patch.object(sheet_sync, "fetch_google_sheet_rows", _fetch):
            async with self.Session() as s:
                result = await sheet_sync.sheet_sync_service.sync_google_sheet_feed(s, self.tournament_id)
        self.assertEqual(1, result.created, result.errors)
        entries = await self._entries()
        self.assertEqual({self.b}, set(entries))

    async def test_registration_output_is_approved_entries_of_the_node(self) -> None:
        (m1, _), (m2, _) = await self._member(1), await self._member(2)
        async with self.Session() as s:
            for member, approved_in in ((m1, self.a), (m2, self.b)):
                registration = models.Registration(tournament_id=self.tournament_id, workspace_member_id=member)
                s.add(registration)
                await s.flush()
                for node in (self.a, self.b):
                    s.add(
                        models.RegistrationEntry(
                            registration_node_id=node,
                            registration_id=registration.id,
                            status="approved" if node == approved_in else "pending",
                        )
                    )
            await s.execute(sa.update(models.FlowNode).where(models.FlowNode.id == self.a).values(status="closed"))
            await s.commit()
        async with self.Session() as s:
            await flow_engine.recompute(s, self.tournament_id)
            await s.commit()
            members = list(
                await s.scalars(
                    sa.select(models.FlowNodeResult.workspace_member_id)
                    .where(models.FlowNodeResult.node_id == self.a, models.FlowNodeResult.port == "participants")
                    .order_by(models.FlowNodeResult.rank)
                )
            )
        self.assertEqual([m1], members)

    async def _team_in(self, node_id: int, name: str) -> int:
        async with self.Session() as s:
            team = models.RegistrationTeam(
                workspace_id=self.workspace_id,
                tournament_id=self.tournament_id,
                registration_node_id=node_id,
                name=name,
                name_normalized=name.lower(),
                status="forming",
            )
            s.add(team)
            await s.commit()
            return team.id

    async def _profile_on_team_of(self, registration_id: int, node_id: int, name: str) -> int:
        """A registering team in ``node_id`` with the profile seated on it; the team's id."""
        team_id = await self._team_in(node_id, name)
        async with self.Session() as s:
            await s.execute(
                sa.update(models.Registration)
                .where(models.Registration.id == registration_id)
                .values(registration_team_id=team_id, team_slot_code="tank")
            )
            await s.commit()
        return team_id

    async def _profile(self, registration_id: int) -> models.Registration:
        async with self.Session() as s:
            return await s.scalar(
                sa.select(models.Registration)
                .where(models.Registration.id == registration_id)
                .options(selectinload(models.Registration.identities))
            )

    async def test_a_second_intake_sign_up_updates_the_profile_answers(self) -> None:
        registration_id = await self._sign_up(self.a)
        async with self.Session() as s:
            await registration_service.write_public_registration(
                s,
                tournament_id=self.tournament_id,
                auth_user=self.user,
                body=RegistrationSubmit(
                    form_version_id=self.version_id,
                    answers={"identity_battlenet": [f"E{self.tag[-6:]}#1234"], "public_notes": "day two"},
                ),
                registration_node_id=self.b,
            )
        self.assertEqual("day two", (await self._profile(registration_id)).public_notes)

    async def test_a_second_intake_sign_up_leaves_what_an_earlier_review_locked(self) -> None:
        registration_id = await self._sign_up(self.a)
        async with self.Session() as s:
            await lifecycle_service.approve_registration(s, self.a, registration_id, reviewed_by=self.actor.id)
        async with self.Session() as s:
            await registration_service.write_public_registration(
                s,
                tournament_id=self.tournament_id,
                auth_user=self.user,
                body=RegistrationSubmit(
                    form_version_id=self.version_id,
                    answers={"identity_battlenet": [f"Other{self.tag[-6:]}#9999"], "public_notes": "kept"},
                ),
                registration_node_id=self.b,
            )
        profile = await self._profile(registration_id)
        self.assertEqual([f"E{self.tag[-6:]}#1234"], [identity.handle for identity in profile.identities])
        self.assertEqual("kept", profile.public_notes)

    async def test_a_captain_cannot_take_a_member_off_the_team_of_another_intake(self) -> None:
        registration_id = await self._sign_up(self.a)
        first_team = await self._profile_on_team_of(registration_id, self.a, "Day One")
        second_team = await self._team_in(self.b, "Day Two")
        async with self.Session() as s:
            with self.assertRaises(ApiHTTPException) as refused:
                await registration_service.write_public_registration(
                    s,
                    tournament_id=self.tournament_id,
                    auth_user=self.user,
                    body=self._submit(),
                    registration_node_id=self.b,
                    team_placement=TeamPlacement(registration_team_id=second_team, slot_code="tank"),
                )
        self.assertEqual((409, "already_on_team"), (refused.exception.status_code, refused.exception.detail[0]["code"]))
        self.assertEqual(first_team, (await self._profile(registration_id)).registration_team_id)

    async def test_the_organizer_cannot_move_a_member_across_intakes_either(self) -> None:
        registration_id = await self._sign_up(self.a)
        first_team = await self._profile_on_team_of(registration_id, self.a, "Day One")
        second_team = await self._team_in(self.b, "Day Two")
        await self._sign_up(self.b)
        async with self.Session() as s:
            with self.assertRaises(ApiHTTPException) as refused:
                await teams_service.place_member_as_organizer(
                    s,
                    tournament_id=self.tournament_id,
                    team_id=second_team,
                    registration_id=registration_id,
                    slot_code="tank",
                )
        self.assertEqual((409, "already_on_team"), (refused.exception.status_code, refused.exception.detail[0]["code"]))
        self.assertEqual(first_team, (await self._profile(registration_id)).registration_team_id)

    async def _manual(self, node_id: int) -> models.RegistrationEntry:
        async with self.Session() as s:
            return await lifecycle_service.create_manual_registration(
                s,
                node_id,
                display_name=None,
                admin_notes=None,
                answers={"identity_battlenet": [f"E{self.tag[-6:]}#1234"]},
                roles=[],
            )

    async def test_an_admin_adds_an_existing_profile_to_another_node(self) -> None:
        registration_id = await self._sign_up(self.a)

        entry = await self._manual(self.b)

        self.assertEqual((registration_id, self.b, "approved"), (entry.registration_id, self.b, entry.status))
        self.assertEqual({self.a, self.b}, set(await self._entries()))
        with self.assertRaises(HTTPException) as again:
            await self._manual(self.b)
        self.assertEqual(409, again.exception.status_code)

    async def test_an_admin_adds_back_an_entry_they_deleted(self) -> None:
        registration_id = await self._sign_up(self.a)
        async with self.Session() as s:
            await lifecycle_service.soft_delete_registration(s, self.a, registration_id, deleted_by=self.actor.id)

        entry = await self._manual(self.a)

        self.assertEqual(registration_id, entry.registration_id)
        self.assertIsNone(entry.deleted_at)

    async def test_a_feed_with_synced_rows_stays_on_its_node(self) -> None:
        mapping = {
            "targets": {
                "source_record_key": {"mode": "columns", "columns": ["BattleTag"], "parser": "battle_tag"},
                "identity_battlenet": {"mode": "columns", "columns": ["BattleTag"], "parser": "battle_tag_list"},
            }
        }
        async with self.Session() as s:
            s.add(
                models.RegistrationGoogleSheetFeed(
                    tournament_id=self.tournament_id,
                    registration_node_id=self.b,
                    source_url="https://docs.google.com/spreadsheets/d/sheet-lock/edit",
                    sheet_id="sheet-lock",
                    mapping_config_json=mapping,
                )
            )
            await s.commit()

        async def _move_to(node_id: int) -> models.RegistrationGoogleSheetFeed:
            async with self.Session() as s:
                return await sheet_sync.sheet_sync_service.upsert_google_sheet_feed(
                    s,
                    self.tournament_id,
                    registration_node_id=node_id,
                    source_url="https://docs.google.com/spreadsheets/d/sheet-lock/edit",
                    title=None,
                    auto_sync_enabled=False,
                    auto_sync_interval_seconds=300,
                    mapping_config_json=None,
                    value_mapping_json=None,
                )

        # Nothing synced yet: the feed is still free to move.
        self.assertEqual(self.a, (await _move_to(self.a)).registration_node_id)
        await _move_to(self.b)

        async def _fetch(*_args, **_kwargs):
            return [["BattleTag"], [f"S{uuid.uuid4().hex[:8]}#4321"]]

        with patch.object(sheet_sync, "fetch_google_sheet_rows", _fetch):
            async with self.Session() as s:
                result = await sheet_sync.sheet_sync_service.sync_google_sheet_feed(s, self.tournament_id)
        self.assertEqual(1, result.created, result.errors)

        with self.assertRaises(ApiHTTPException) as refused:
            await _move_to(self.a)
        self.assertEqual(
            (409, "feed_node_locked"), (refused.exception.status_code, refused.exception.detail[0]["code"])
        )

    async def test_deleting_a_tournament_clears_what_restricts_its_nodes(self) -> None:
        await self._sign_up(self.a)
        formation = await self.node("formation")
        member, _account = await self._member(1)
        async with self.Session() as s:
            s.add(
                models.RegistrationGoogleSheetFeed(
                    tournament_id=self.tournament_id,
                    registration_node_id=self.b,
                    source_url="https://docs.google.com/spreadsheets/d/sheet-del/edit",
                    sheet_id="sheet-del",
                )
            )
            team = models.Team(
                balancer_name="Cup", name="Cup", tournament_id=self.tournament_id, formation_node_id=formation
            )
            s.add(team)
            await s.flush()
            s.add(
                models.Player(
                    name="P",
                    tournament_id=self.tournament_id,
                    formation_node_id=formation,
                    workspace_member_id=member,
                    team_id=team.id,
                )
            )
            await s.commit()
        await self._team_in(self.a, "Day One")

        # The guard the delete has to clear: a node cannot go while any of these still points at it.
        async with self.Session() as s:
            with self.assertRaises(IntegrityError):
                await s.execute(sa.delete(models.FlowNode).where(models.FlowNode.id == self.a))

        with (
            patch.object(division_grid_cache, "invalidate_tournament", AsyncMock()),
            patch.object(division_grid_cache, "invalidate_workspace", AsyncMock()),
        ):
            async with self.Session() as s:
                await tournament_service.delete_tournament(s, self.tournament_id)

        async with self.Session() as s:
            self.assertIsNone(await s.get(models.Tournament, self.tournament_id))
            self.assertEqual(
                0,
                await s.scalar(
                    sa.select(sa.func.count())
                    .select_from(models.FlowNode)
                    .where(models.FlowNode.tournament_id == self.tournament_id)
                ),
            )
